from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .metrics import track_metrics
from .runs import active_tracks_for_run, normalize_tracks
from .schema import Track, read_events, utc_now_iso

OPENAI_BASE_URL = "https://api.openai.com/v1"
TRACK_PROJECT_ENV: dict[Track, str] = {
    "plain-codex": "SIM_OPENAI_PROJECT_PLAIN",
    "workerbee-codex": "SIM_OPENAI_PROJECT_WORKERBEE",
}


@dataclass(frozen=True)
class CodexApiAuthResult:
    track: Track
    codex_home: Path
    codex_bin: str
    api_key_env: str
    returncode: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def event_payload(self) -> dict[str, object]:
        return {
            "phase": "auth_prepare",
            "auth_method": "api_key",
            "api_key_env": self.api_key_env,
            "codex_home": str(self.codex_home),
            "codex_bin": self.codex_bin,
            "returncode": self.returncode,
        }


def prepare_codex_api_auth(
    *,
    track: Track,
    api_key_env: str,
    codex_home: Path,
    codex_bin: str = "codex",
) -> CodexApiAuthResult:
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"{api_key_env} is not set")
    codex_home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    result = subprocess.run(  # noqa: S603 - caller selects the Codex executable.
        [codex_bin, "login", "--with-api-key"],
        input=api_key,
        text=True,
        env=env,
        capture_output=True,
        check=False,
    )
    return CodexApiAuthResult(
        track=track,
        codex_home=codex_home,
        codex_bin=codex_bin,
        api_key_env=api_key_env,
        returncode=result.returncode,
    )


def reconcile_openai_usage(
    *,
    run_root: Path,
    admin_key_env: str = "OPENAI_ADMIN_KEY",
    track_project_ids: dict[str, str],
    track_api_key_ids: dict[str, str | None] | None = None,
    start_time: str | int | float | None = None,
    end_time: str | int | float | None = None,
    window_pad_seconds: int = 600,
    usage_json: Path | None = None,
    costs_json: Path | None = None,
    base_url: str = OPENAI_BASE_URL,
    tracks: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    active_tracks = (
        normalize_tracks(tracks) if tracks is not None else active_tracks_for_run(run_root)
    )
    track_api_key_ids = track_api_key_ids or {}
    started, ended = _reconciliation_window(
        run_root,
        start_time=start_time,
        end_time=end_time,
        window_pad_seconds=window_pad_seconds,
    )
    cost_started, cost_ended = _cost_window(started, ended)
    source = "offline_fixture" if usage_json or costs_json else "openai_admin_api"
    if usage_json:
        usage_raw = _read_json(usage_json)
    else:
        usage_raw = _fetch_openai_usage(
            base_url=base_url,
            admin_key=_admin_key(admin_key_env),
            start_time=started,
            end_time=ended,
            project_ids=list(track_project_ids.values()),
        )
    if costs_json:
        costs_raw = _read_json(costs_json)
    else:
        costs_raw = _fetch_openai_costs(
            base_url=base_url,
            admin_key=_admin_key(admin_key_env),
            start_time=cost_started,
            end_time=cost_ended,
            project_ids=list(track_project_ids.values()),
        )

    usage_by_track = _aggregate_usage_by_track(
        usage_raw,
        tracks=active_tracks,
        track_project_ids=track_project_ids,
        track_api_key_ids=track_api_key_ids,
    )
    costs_by_track = _aggregate_costs_by_track(
        costs_raw,
        tracks=active_tracks,
        track_project_ids=track_project_ids,
        track_api_key_ids=track_api_key_ids,
    )
    events_by_track = {
        track: read_events(run_root / track / "events.jsonl") for track in active_tracks
    }
    track_results: dict[str, object] = {}
    for track in active_tracks:
        metrics = track_metrics(events_by_track.get(track, []))
        usage = usage_by_track.get(track, _empty_usage())
        costs = costs_by_track.get(track, _empty_costs())
        provider_input = int(usage["input_tokens"])
        delta_captured = provider_input - metrics.input_tokens
        delta_all_in = provider_input - metrics.estimated_all_in_input_tokens
        track_results[track] = {
            "project_id": track_project_ids.get(track),
            "api_key_id": track_api_key_ids.get(track),
            "usage": usage,
            "costs": costs,
            "comparison": {
                "captured_codex_input_tokens": metrics.input_tokens,
                "estimated_all_in_input_tokens": metrics.estimated_all_in_input_tokens,
                "provider_input_delta_vs_captured": delta_captured,
                "provider_input_delta_vs_estimated_all_in": delta_all_in,
                "provider_input_delta_vs_captured_pct": _delta_pct(delta_captured, provider_input),
                "provider_input_delta_vs_estimated_all_in_pct": _delta_pct(
                    delta_all_in, provider_input
                ),
                "match_basis": _match_basis(
                    provider_input=provider_input,
                    captured_input=metrics.input_tokens,
                    estimated_all_in=metrics.estimated_all_in_input_tokens,
                ),
            },
        }
    return {
        "schema_version": "simulacra.openai-billing.v1",
        "source": source,
        "fetched_at": utc_now_iso(),
        "window_started_at": _iso(started),
        "window_ended_at": _iso(ended),
        "window_pad_seconds": int(window_pad_seconds),
        "cost_window_started_at": _iso(cost_started),
        "cost_window_ended_at": _iso(cost_ended),
        "usage_raw": usage_raw,
        "costs_raw": costs_raw,
        "tracks": track_results,
    }


def billing_event_payload(
    *,
    reconciliation: dict[str, object],
    track: Track,
    raw_usage_path: Path,
    raw_costs_path: Path,
    reconciliation_path: Path,
    run_root: Path,
) -> dict[str, object]:
    tracks = reconciliation.get("tracks") if isinstance(reconciliation.get("tracks"), dict) else {}
    track_result = tracks.get(track) if isinstance(tracks, dict) else {}
    if not isinstance(track_result, dict):
        track_result = {}
    usage = track_result.get("usage") if isinstance(track_result.get("usage"), dict) else {}
    costs = track_result.get("costs") if isinstance(track_result.get("costs"), dict) else {}
    comparison = (
        track_result.get("comparison") if isinstance(track_result.get("comparison"), dict) else {}
    )
    return {
        "phase": "provider_reconciliation",
        "provider": "openai",
        "source": reconciliation.get("source"),
        "auth_method": "api_key",
        "project_id": track_result.get("project_id"),
        "api_key_id": track_result.get("api_key_id"),
        "window_started_at": reconciliation.get("window_started_at"),
        "window_ended_at": reconciliation.get("window_ended_at"),
        "cost_window_started_at": reconciliation.get("cost_window_started_at"),
        "cost_window_ended_at": reconciliation.get("cost_window_ended_at"),
        "provider_input_tokens": int(usage.get("input_tokens") or 0),
        "provider_cached_input_tokens": int(usage.get("input_cached_tokens") or 0),
        "provider_output_tokens": int(usage.get("output_tokens") or 0),
        "provider_input_audio_tokens": int(usage.get("input_audio_tokens") or 0),
        "provider_output_audio_tokens": int(usage.get("output_audio_tokens") or 0),
        "provider_model_requests": int(usage.get("num_model_requests") or 0),
        "provider_costs_by_currency": costs.get("amount_by_currency") or {},
        "provider_cost_value": costs.get("primary_amount_value"),
        "provider_cost_currency": costs.get("primary_amount_currency"),
        "line_items": costs.get("line_items") or [],
        "groups": usage.get("groups") or [],
        "captured_codex_input_tokens": comparison.get("captured_codex_input_tokens"),
        "estimated_all_in_input_tokens": comparison.get("estimated_all_in_input_tokens"),
        "provider_input_delta_vs_captured": comparison.get("provider_input_delta_vs_captured"),
        "provider_input_delta_vs_estimated_all_in": comparison.get(
            "provider_input_delta_vs_estimated_all_in"
        ),
        "provider_input_delta_vs_captured_pct": comparison.get(
            "provider_input_delta_vs_captured_pct"
        ),
        "provider_input_delta_vs_estimated_all_in_pct": comparison.get(
            "provider_input_delta_vs_estimated_all_in_pct"
        ),
        "match_basis": comparison.get("match_basis"),
        "raw_usage_file": _display_path(raw_usage_path, run_root),
        "raw_costs_file": _display_path(raw_costs_path, run_root),
        "reconciliation_file": _display_path(reconciliation_path, run_root),
    }


def normalized_reconciliation(reconciliation: dict[str, object]) -> dict[str, object]:
    return {
        key: value for key, value in reconciliation.items() if key not in {"usage_raw", "costs_raw"}
    }


def _fetch_openai_usage(
    *,
    base_url: str,
    admin_key: str,
    start_time: datetime,
    end_time: datetime,
    project_ids: list[str],
) -> dict[str, object]:
    params: dict[str, object] = {
        "start_time": int(start_time.timestamp()),
        "end_time": int(end_time.timestamp()),
        "bucket_width": "1m",
        "project_ids": project_ids,
        "group_by": ["project_id", "api_key_id", "model", "batch", "service_tier"],
        "limit": 31,
    }
    return _fetch_paginated(
        f"{base_url.rstrip('/')}/organization/usage/completions",
        admin_key=admin_key,
        params=params,
    )


def _fetch_openai_costs(
    *,
    base_url: str,
    admin_key: str,
    start_time: datetime,
    end_time: datetime,
    project_ids: list[str],
) -> dict[str, object]:
    params: dict[str, object] = {
        "start_time": int(start_time.timestamp()),
        "end_time": int(end_time.timestamp()),
        "bucket_width": "1d",
        "project_ids": project_ids,
        "group_by": ["project_id", "api_key_id", "line_item"],
        "limit": 31,
    }
    return _fetch_paginated(
        f"{base_url.rstrip('/')}/organization/costs",
        admin_key=admin_key,
        params=params,
    )


def _fetch_paginated(
    url: str,
    *,
    admin_key: str,
    params: dict[str, object],
) -> dict[str, object]:
    pages = []
    page: str | None = None
    while True:
        query = dict(params)
        if page:
            query["page"] = page
        response = _http_get_json(url, admin_key=admin_key, params=query)
        pages.append(response)
        if not response.get("has_more") or not response.get("next_page"):
            break
        page = str(response["next_page"])
    data = [
        bucket
        for response in pages
        for bucket in response.get("data", [])
        if isinstance(bucket, dict)
    ]
    return {
        "object": "page",
        "data": data,
        "has_more": False,
        "next_page": None,
        "page_count": len(pages),
    }


def _http_get_json(
    url: str,
    *,
    admin_key: str,
    params: dict[str, object],
) -> dict[str, object]:
    request_url = f"{url}?{urlencode(params, doseq=True)}"
    request = Request(  # noqa: S310 - fixed OpenAI/admin URL supplied by caller or tests.
        request_url,
        headers={
            "Authorization": f"Bearer {admin_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed OpenAI/admin URL.
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"OpenAI admin API request failed: HTTP {exc.code}: {detail}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("OpenAI admin API returned a non-object JSON response")
    return payload


def _aggregate_usage_by_track(
    usage_raw: dict[str, object],
    *,
    tracks: tuple[Track, ...],
    track_project_ids: dict[str, str],
    track_api_key_ids: dict[str, str | None],
) -> dict[str, dict[str, object]]:
    aggregate = {track: _empty_usage() for track in tracks}
    project_to_track = {project_id: track for track, project_id in track_project_ids.items()}
    for result in _iter_results(usage_raw):
        project_id = result.get("project_id")
        track = project_to_track.get(str(project_id))
        if track not in aggregate:
            continue
        expected_key = track_api_key_ids.get(track)
        api_key_id = result.get("api_key_id")
        if expected_key and str(api_key_id) != expected_key:
            continue
        item = aggregate[track]
        for key in (
            "input_tokens",
            "input_cached_tokens",
            "output_tokens",
            "input_audio_tokens",
            "output_audio_tokens",
            "num_model_requests",
        ):
            item[key] = int(item[key]) + int(result.get(key) or 0)
        item["groups"].append(_usage_group(result))
    return aggregate


def _aggregate_costs_by_track(
    costs_raw: dict[str, object],
    *,
    tracks: tuple[Track, ...],
    track_project_ids: dict[str, str],
    track_api_key_ids: dict[str, str | None],
) -> dict[str, dict[str, object]]:
    aggregate = {track: _empty_costs() for track in tracks}
    project_to_track = {project_id: track for track, project_id in track_project_ids.items()}
    for result in _iter_results(costs_raw):
        project_id = result.get("project_id")
        track = project_to_track.get(str(project_id))
        if track not in aggregate:
            continue
        expected_key = track_api_key_ids.get(track)
        api_key_id = result.get("api_key_id")
        if expected_key and str(api_key_id) != expected_key:
            continue
        amount = result.get("amount") if isinstance(result.get("amount"), dict) else {}
        currency = str(amount.get("currency") or "unknown")
        value = float(amount.get("value") or 0.0)
        item = aggregate[track]
        amounts = item["amount_by_currency"]
        amounts[currency] = round(float(amounts.get(currency, 0.0)) + value, 8)
        item["line_items"].append(_cost_line_item(result, value=value, currency=currency))
    for item in aggregate.values():
        amounts = item["amount_by_currency"]
        if amounts:
            currency, value = sorted(amounts.items())[0]
            item["primary_amount_currency"] = currency
            item["primary_amount_value"] = value
    return aggregate


def _iter_results(raw: dict[str, object]) -> Iterable[dict[str, object]]:
    data = raw.get("data") if isinstance(raw.get("data"), list) else []
    for bucket in data:
        if not isinstance(bucket, dict):
            continue
        results = bucket.get("results") if isinstance(bucket.get("results"), list) else []
        for result in results:
            if isinstance(result, dict):
                yield result


def _usage_group(result: dict[str, object]) -> dict[str, object]:
    return {
        key: result.get(key)
        for key in (
            "project_id",
            "api_key_id",
            "model",
            "batch",
            "service_tier",
            "input_tokens",
            "input_cached_tokens",
            "output_tokens",
            "input_audio_tokens",
            "output_audio_tokens",
            "num_model_requests",
        )
        if result.get(key) is not None
    }


def _cost_line_item(
    result: dict[str, object],
    *,
    value: float,
    currency: str,
) -> dict[str, object]:
    return {
        "project_id": result.get("project_id"),
        "api_key_id": result.get("api_key_id"),
        "line_item": result.get("line_item"),
        "quantity": result.get("quantity"),
        "amount_value": value,
        "amount_currency": currency,
    }


def _empty_usage() -> dict[str, object]:
    return {
        "input_tokens": 0,
        "input_cached_tokens": 0,
        "output_tokens": 0,
        "input_audio_tokens": 0,
        "output_audio_tokens": 0,
        "num_model_requests": 0,
        "groups": [],
    }


def _empty_costs() -> dict[str, object]:
    return {
        "amount_by_currency": {},
        "primary_amount_value": None,
        "primary_amount_currency": None,
        "line_items": [],
    }


def _match_basis(
    *,
    provider_input: int,
    captured_input: int,
    estimated_all_in: int,
) -> str:
    if provider_input <= 0:
        return "no_provider_usage"
    tolerance = max(500, int(provider_input * 0.05))
    if abs(provider_input - captured_input) <= tolerance:
        return "captured_codex"
    if abs(provider_input - estimated_all_in) <= tolerance:
        return "estimated_all_in"
    return "mismatch"


def _delta_pct(delta: int, provider_input: int) -> float | None:
    if provider_input <= 0:
        return None
    return round((delta / provider_input) * 100, 3)


def _reconciliation_window(
    run_root: Path,
    *,
    start_time: str | int | float | None,
    end_time: str | int | float | None,
    window_pad_seconds: int,
) -> tuple[datetime, datetime]:
    if start_time is not None and end_time is not None:
        started = _parse_time(start_time)
        ended = _parse_time(end_time)
    else:
        started, ended = _event_window(run_root)
    pad = timedelta(seconds=max(0, int(window_pad_seconds)))
    return started - pad, ended + pad


def _event_window(run_root: Path) -> tuple[datetime, datetime]:
    timestamps = []
    for track in active_tracks_for_run(run_root):
        for event in read_events(run_root / track / "events.jsonl"):
            if event.event_type in {"checkpoint", "mcp_observation", "billing_reconciliation"}:
                continue
            if event.summary.lower().startswith("preflight "):
                continue
            try:
                timestamp = _parse_time(event.timestamp)
            except ValueError:
                continue
            timestamps.append(timestamp)
    if not timestamps:
        now = datetime.now(UTC)
        return now - timedelta(minutes=1), now
    return min(timestamps), max(timestamps)


def _cost_window(started: datetime, ended: datetime) -> tuple[datetime, datetime]:
    start_day = datetime(started.year, started.month, started.day, tzinfo=UTC)
    end_day = datetime(ended.year, ended.month, ended.day, tzinfo=UTC) + timedelta(days=1)
    return start_day, end_day


def _parse_time(value: str | int | float) -> datetime:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), UTC)
    text = str(value)
    if text.isdigit():
        return datetime.fromtimestamp(float(text), UTC)
    try:
        return datetime.fromtimestamp(float(text), UTC)
    except ValueError:
        pass
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} does not contain a JSON object")
    return value


def _admin_key(admin_key_env: str) -> str:
    admin_key = os.environ.get(admin_key_env)
    if not admin_key:
        raise RuntimeError(f"{admin_key_env} is not set")
    return admin_key


def _display_path(path: Path, run_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(run_root.resolve()))
    except ValueError:
        return str(path)
