from __future__ import annotations

import json
from pathlib import Path

from simulacra.openai_billing import (
    billing_event_payload,
    normalized_reconciliation,
    reconcile_openai_usage,
)
from simulacra.schema import SimulationEvent, append_event


def test_reconcile_openai_usage_aggregates_project_usage_and_costs(tmp_path: Path) -> None:
    run_root = tmp_path / ".local" / "runs" / "r1"
    for track in ("plain-codex", "workerbee-codex"):
        (run_root / track).mkdir(parents=True)
    _codex_usage(run_root, "plain-codex", input_tokens=1200)
    _codex_usage(run_root, "workerbee-codex", input_tokens=900)
    usage_json = tmp_path / "usage.json"
    costs_json = tmp_path / "costs.json"
    usage_json.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "start_time": 1,
                        "end_time": 2,
                        "results": [
                            {
                                "project_id": "proj_plain",
                                "api_key_id": "key_plain",
                                "model": "gpt-test",
                                "input_tokens": 1200,
                                "input_cached_tokens": 200,
                                "output_tokens": 100,
                                "num_model_requests": 2,
                            },
                            {
                                "project_id": "proj_wb",
                                "api_key_id": "key_wb",
                                "model": "gpt-test",
                                "input_tokens": 900,
                                "input_cached_tokens": 100,
                                "output_tokens": 80,
                                "num_model_requests": 1,
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    costs_json.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "start_time": 1,
                        "end_time": 2,
                        "results": [
                            {
                                "project_id": "proj_plain",
                                "api_key_id": "key_plain",
                                "line_item": "responses",
                                "amount": {"value": 0.0123, "currency": "usd"},
                            },
                            {
                                "project_id": "proj_wb",
                                "api_key_id": "key_wb",
                                "line_item": "responses",
                                "amount": {"value": 0.0087, "currency": "usd"},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = reconcile_openai_usage(
        run_root=run_root,
        track_project_ids={"plain-codex": "proj_plain", "workerbee-codex": "proj_wb"},
        track_api_key_ids={"plain-codex": "key_plain", "workerbee-codex": "key_wb"},
        usage_json=usage_json,
        costs_json=costs_json,
    )

    plain = result["tracks"]["plain-codex"]
    workerbee = result["tracks"]["workerbee-codex"]
    assert plain["usage"]["input_tokens"] == 1200
    assert plain["usage"]["input_cached_tokens"] == 200
    assert plain["usage"]["num_model_requests"] == 2
    assert plain["costs"]["primary_amount_value"] == 0.0123
    assert plain["comparison"]["match_basis"] == "captured_codex"
    assert workerbee["usage"]["input_tokens"] == 900
    assert workerbee["comparison"]["provider_input_delta_vs_captured"] == 0
    assert "usage_raw" not in normalized_reconciliation(result)


def test_billing_event_payload_is_sanitized(tmp_path: Path) -> None:
    run_root = tmp_path / ".local" / "runs" / "r1"
    run_root.mkdir(parents=True)
    reconciliation = {
        "source": "offline_fixture",
        "window_started_at": "2026-06-14T00:00:00+00:00",
        "window_ended_at": "2026-06-14T00:01:00+00:00",
        "cost_window_started_at": "2026-06-14T00:00:00+00:00",
        "cost_window_ended_at": "2026-06-15T00:00:00+00:00",
        "tracks": {
            "plain-codex": {
                "project_id": "proj_plain",
                "api_key_id": "key_plain",
                "usage": {
                    "input_tokens": 10,
                    "input_cached_tokens": 2,
                    "output_tokens": 1,
                    "num_model_requests": 1,
                    "groups": [],
                },
                "costs": {
                    "primary_amount_value": 0.001,
                    "primary_amount_currency": "usd",
                    "amount_by_currency": {"usd": 0.001},
                    "line_items": [],
                },
                "comparison": {
                    "match_basis": "captured_codex",
                    "provider_input_delta_vs_captured": 0,
                    "provider_input_delta_vs_estimated_all_in": 0,
                },
            }
        },
    }

    payload = billing_event_payload(
        reconciliation=reconciliation,
        track="plain-codex",
        raw_usage_path=run_root / "billing" / "openai" / "usage-completions.raw.json",
        raw_costs_path=run_root / "billing" / "openai" / "costs.raw.json",
        reconciliation_path=run_root / "billing" / "reconciliation.json",
        run_root=run_root,
    )

    text = json.dumps(payload, sort_keys=True)
    assert "provider_input_tokens" in payload
    assert "sk-" not in text
    assert "raw_usage_file" in payload


def _codex_usage(run_root: Path, track: str, *, input_tokens: int) -> None:
    append_event(
        run_root / track / "events.jsonl",
        SimulationEvent(
            run_id="r1",
            track=track,  # type: ignore[arg-type]
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn completed",
            payload={
                "raw_type": "turn.completed",
                "usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": 0,
                    "output_tokens": 1,
                    "reasoning_output_tokens": 0,
                },
            },
            timestamp="2026-06-14T00:00:00+00:00",
        ),
    )
