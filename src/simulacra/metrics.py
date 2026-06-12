from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .codex_events import aggregate_usage
from .schema import SimulationEvent


@dataclass(frozen=True)
class DurationWindow:
    started_at: str
    ended_at: str
    seconds: float | None
    label: str


@dataclass(frozen=True)
class TrackMetrics:
    events: int
    prompts: int
    commands: int
    workerbee_actions: int
    evidence: int
    violations: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    completeness: str
    duration: DurationWindow


def track_metrics(events: list[SimulationEvent]) -> TrackMetrics:
    prompts = [event for event in events if event.event_type == "human_prompt"]
    commands = [
        event for event in events if event.event_type in {"command", "ae_command", "workerbee_tool"}
    ]
    workerbee_actions = [event for event in events if event.event_type == "workerbee_tool"]
    evidence = [event for event in events if event.event_type == "evidence"]
    violations = [event for event in events if event.event_type == "protocol_violation"]
    usage = aggregate_usage(events)
    missing = _missing_measurements(
        prompts=bool(prompts),
        commands=bool(commands),
        evidence=bool(evidence),
        usage=any(usage.values()),
    )
    return TrackMetrics(
        events=len(events),
        prompts=len(prompts),
        commands=len(commands),
        workerbee_actions=len(workerbee_actions),
        evidence=len(evidence),
        violations=len(violations),
        input_tokens=usage["input_tokens"],
        cached_input_tokens=usage["cached_input_tokens"],
        output_tokens=usage["output_tokens"],
        reasoning_output_tokens=usage["reasoning_output_tokens"],
        completeness="complete" if not missing else f"incomplete ({', '.join(missing)})",
        duration=duration_window(events),
    )


def run_duration(events_by_track: dict[str, list[SimulationEvent]]) -> DurationWindow:
    return duration_window([event for events in events_by_track.values() for event in events])


def duration_window(events: list[SimulationEvent]) -> DurationWindow:
    parsed = sorted(
        (item for item in (_parse_timestamp(event.timestamp) for event in events) if item),
    )
    if not parsed:
        return DurationWindow(started_at="n/a", ended_at="n/a", seconds=None, label="n/a")
    started = parsed[0]
    ended = parsed[-1]
    seconds = max(0.0, (ended - started).total_seconds())
    return DurationWindow(
        started_at=started.isoformat(),
        ended_at=ended.isoformat(),
        seconds=seconds,
        label=format_duration(seconds),
    )


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _missing_measurements(
    *, prompts: bool, commands: bool, evidence: bool, usage: bool
) -> list[str]:
    missing = []
    if not prompts:
        missing.append("human_prompt")
    if not commands:
        missing.append("command/tool")
    if not evidence:
        missing.append("evidence")
    if not usage:
        missing.append("token usage")
    return missing
