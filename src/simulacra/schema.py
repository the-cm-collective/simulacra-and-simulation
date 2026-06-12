from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = "simulacra.event.v1"
Track = Literal["plain-codex", "workerbee-codex"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class SimulationEvent:
    run_id: str
    track: Track
    event_type: str
    source: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now_iso)
    schema_version: str = SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> SimulationEvent:
        data = json.loads(line)
        payload = data.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        return cls(
            run_id=str(data["run_id"]),
            track=data["track"],
            event_type=str(data["event_type"]),
            source=str(data["source"]),
            summary=str(data["summary"]),
            payload=payload,
            timestamp=str(data["timestamp"]),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )


def append_event(path: Path, event: SimulationEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(event.to_json() + "\n")


def read_events(path: Path) -> list[SimulationEvent]:
    if not path.exists():
        return []
    return [
        SimulationEvent.from_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
