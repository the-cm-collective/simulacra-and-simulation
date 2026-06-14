from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .schema import SimulationEvent, Track, utc_now_iso


def normalize_codex_jsonl(path: Path, *, run_id: str, track: Track) -> list[SimulationEvent]:
    events: list[SimulationEvent] = []
    if not path.exists():
        return events
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            events.append(
                SimulationEvent(
                    run_id=run_id,
                    track=track,
                    event_type="codex_event_parse_error",
                    source="codex-jsonl",
                    summary=f"Could not parse Codex JSONL line {line_no}",
                    payload={
                        "line_no": line_no,
                        "error": str(exc),
                        "source_file": str(path),
                        "source_sha256": source_sha256,
                    },
                )
            )
            continue
        events.append(
            _normalize_raw_event(
                raw,
                run_id=run_id,
                track=track,
                line_no=line_no,
                source_file=path,
                source_sha256=source_sha256,
            )
        )
    return events


def aggregate_usage(events: Iterable[SimulationEvent]) -> dict[str, int]:
    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    for event in events:
        usage = event.payload.get("usage")
        if not isinstance(usage, dict):
            continue
        for key in totals:
            totals[key] += int(usage.get(key) or 0)
    return totals


def _normalize_raw_event(
    raw: dict[str, Any],
    *,
    run_id: str,
    track: Track,
    line_no: int,
    source_file: Path,
    source_sha256: str,
) -> SimulationEvent:
    event_type = str(raw.get("type") or "unknown")
    payload: dict[str, Any] = {
        "line_no": line_no,
        "raw_type": event_type,
        "source_file": str(source_file),
        "source_sha256": source_sha256,
    }
    summary = event_type
    item = raw.get("item")
    if isinstance(item, dict):
        payload["item_type"] = item.get("type")
        payload["item_status"] = item.get("status")
        if command := item.get("command"):
            payload["command"] = command
            summary = f"command: {command}"
        elif text := item.get("text"):
            summary = f"{event_type}: {str(text)[:120]}"
    if usage := raw.get("usage"):
        payload["usage"] = usage
        summary = "codex turn completed with usage"
    if thread_id := raw.get("thread_id"):
        payload["thread_id"] = thread_id
    return SimulationEvent(
        run_id=run_id,
        track=track,
        event_type="codex_event",
        source="codex-jsonl",
        summary=summary,
        payload=payload,
        timestamp=str(raw.get("timestamp") or utc_now_iso()),
    )
