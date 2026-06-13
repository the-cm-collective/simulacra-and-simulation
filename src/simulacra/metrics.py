from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .codex_events import aggregate_usage
from .schema import SimulationEvent

REQUIRED_EVIDENCE_PHASES = ("local", "k1s-dev-a")
EVIDENCE_PHASE_ALIASES = {
    "local": {"local", "workerbee-local", "podman-local"},
    "k1s-dev-a": {"k1s-dev-a"},
}


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
    human_commands: int
    codex_commands: int
    ae_actions: int
    human_actions: int
    operator_touches: int
    automation_actions: int
    workerbee_actions: int
    evidence: int
    evidence_phases: tuple[str, ...]
    violations: int
    codex_turns_started: int
    codex_turns_missing_usage: int
    usage_snapshots: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    final_turn_input_tokens: int
    max_turn_input_tokens: int
    final_cached_turn_input_tokens: int
    max_cached_turn_input_tokens: int
    completeness: str
    duration: DurationWindow


def track_metrics(events: list[SimulationEvent]) -> TrackMetrics:
    prompts = [event for event in events if event.event_type == "human_prompt"]
    command_events = [event for event in events if event.event_type == "command"]
    human_commands = [event for event in command_events if event.source == "human"]
    codex_commands = [event for event in command_events if event.source in {"codex", "simctl"}]
    ae_actions = [event for event in events if event.event_type == "ae_command"]
    human_actions = [event for event in events if event.event_type == "human_action"]
    workerbee_actions = [event for event in events if event.event_type == "workerbee_tool"]
    evidence = [event for event in events if event.event_type == "evidence"]
    evidence_phases = tuple(
        sorted({str(event.payload.get("phase") or "unspecified") for event in evidence})
    )
    violations = [event for event in events if event.event_type == "protocol_violation"]
    operator_touches = len(prompts) + len(human_commands) + len(ae_actions) + len(human_actions)
    automation_actions = len(workerbee_actions) + len(codex_commands)
    usage = aggregate_usage(events)
    usage_snapshots = _usage_snapshots(events)
    codex_turns_started = _codex_turns_started(events)
    codex_turns_missing_usage = max(0, codex_turns_started - len(usage_snapshots))
    missing = _missing_measurements(
        prompts=bool(prompts),
        commands=bool(command_events or ae_actions or workerbee_actions or human_actions),
        evidence=bool(evidence),
        evidence_phases=evidence_phases,
        usage=any(usage.values()),
        codex_turns_missing_usage=codex_turns_missing_usage,
    )
    return TrackMetrics(
        events=len(events),
        prompts=len(prompts),
        commands=len(command_events) + len(ae_actions),
        human_commands=len(human_commands),
        codex_commands=len(codex_commands),
        ae_actions=len(ae_actions),
        human_actions=len(human_actions),
        operator_touches=operator_touches,
        automation_actions=automation_actions,
        workerbee_actions=len(workerbee_actions),
        evidence=len(evidence),
        evidence_phases=evidence_phases,
        violations=len(violations),
        codex_turns_started=codex_turns_started,
        codex_turns_missing_usage=codex_turns_missing_usage,
        usage_snapshots=len(usage_snapshots),
        input_tokens=usage["input_tokens"],
        cached_input_tokens=usage["cached_input_tokens"],
        output_tokens=usage["output_tokens"],
        reasoning_output_tokens=usage["reasoning_output_tokens"],
        final_turn_input_tokens=_final_usage_value(usage_snapshots, "input_tokens"),
        max_turn_input_tokens=_max_usage_value(usage_snapshots, "input_tokens"),
        final_cached_turn_input_tokens=_final_usage_value(usage_snapshots, "cached_input_tokens"),
        max_cached_turn_input_tokens=_max_usage_value(usage_snapshots, "cached_input_tokens"),
        completeness="complete" if not missing else f"incomplete ({', '.join(missing)})",
        duration=duration_window(events),
    )


def is_operator_touch(event: SimulationEvent) -> bool:
    return (
        event.event_type == "human_prompt"
        or (event.event_type == "command" and event.source == "human")
        or event.event_type == "ae_command"
        or event.event_type == "human_action"
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
    *,
    prompts: bool,
    commands: bool,
    evidence: bool,
    evidence_phases: tuple[str, ...],
    usage: bool,
    codex_turns_missing_usage: int,
) -> list[str]:
    missing = []
    if not prompts:
        missing.append("human_prompt")
    if not commands:
        missing.append("command/tool/action")
    if not evidence:
        missing.append("evidence")
    else:
        phase_set = set(evidence_phases)
        for phase in REQUIRED_EVIDENCE_PHASES:
            accepted = EVIDENCE_PHASE_ALIASES.get(phase, {phase})
            if not phase_set.intersection(accepted):
                missing.append(f"{phase} evidence")
    if not usage:
        missing.append("token usage")
    elif codex_turns_missing_usage:
        missing.append(f"codex usage partial ({codex_turns_missing_usage} turn)")
    return missing


def _codex_turns_started(events: list[SimulationEvent]) -> int:
    return sum(
        1
        for event in events
        if event.event_type == "codex_event" and event.payload.get("raw_type") == "turn.started"
    )


def _usage_snapshots(events: list[SimulationEvent]) -> list[dict[str, object]]:
    snapshots = []
    for event in events:
        usage = event.payload.get("usage")
        if isinstance(usage, dict):
            snapshots.append(usage)
    return snapshots


def _final_usage_value(snapshots: list[dict[str, object]], key: str) -> int:
    if not snapshots:
        return 0
    return int(snapshots[-1].get(key) or 0)


def _max_usage_value(snapshots: list[dict[str, object]], key: str) -> int:
    if not snapshots:
        return 0
    return max(int(snapshot.get(key) or 0) for snapshot in snapshots)
