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
    context_management_actions: int
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
    prompt_chars: int
    prompt_bytes: int
    prompt_metadata_count: int
    prompt_metadata_missing: int
    max_prompt_chars: int
    max_prompt_bytes: int
    copied_context_bytes: int
    copied_context_available_bytes: int
    copied_context_sources: int
    copied_context_truncated_sources: int
    copied_context_by_class: dict[str, int]
    completeness: str
    raw_duration: DurationWindow
    observed_duration: DurationWindow
    duration: DurationWindow
    manual_time_tax_seconds: float
    manual_time_tax_label: str
    lane_idle_seconds: float
    lane_idle_label: str


def track_metrics(events: list[SimulationEvent]) -> TrackMetrics:
    prompts = [event for event in events if event.event_type == "human_prompt"]
    command_events = [event for event in events if event.event_type == "command"]
    human_commands = [event for event in command_events if event.source == "human"]
    codex_commands = [event for event in command_events if event.source in {"codex", "simctl"}]
    ae_actions = [event for event in events if event.event_type == "ae_command"]
    human_actions = [event for event in events if event.event_type == "human_action"]
    context_management_actions = [
        event for event in human_actions if event.payload.get("kind") == "context_management"
    ]
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
    prompt_stats = _prompt_stats(prompts)
    missing = _missing_measurements(
        prompts=bool(prompts),
        commands=bool(command_events or ae_actions or workerbee_actions or human_actions),
        evidence=bool(evidence),
        evidence_phases=evidence_phases,
        usage=any(usage.values()),
        codex_turns_missing_usage=codex_turns_missing_usage,
    )
    raw_duration = duration_window(events)
    observed_duration = measured_duration_window(events)
    manual_time_tax_seconds = manual_time_tax(events)
    adjusted_duration = add_duration_tax(observed_duration, manual_time_tax_seconds)
    lane_idle_seconds = checkpoint_idle_seconds(events)
    return TrackMetrics(
        events=len(events),
        prompts=len(prompts),
        commands=len(command_events) + len(ae_actions),
        human_commands=len(human_commands),
        codex_commands=len(codex_commands),
        ae_actions=len(ae_actions),
        human_actions=len(human_actions),
        context_management_actions=len(context_management_actions),
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
        prompt_chars=prompt_stats["prompt_chars"],
        prompt_bytes=prompt_stats["prompt_bytes"],
        prompt_metadata_count=prompt_stats["prompt_metadata_count"],
        prompt_metadata_missing=prompt_stats["prompt_metadata_missing"],
        max_prompt_chars=prompt_stats["max_prompt_chars"],
        max_prompt_bytes=prompt_stats["max_prompt_bytes"],
        copied_context_bytes=prompt_stats["copied_context_bytes"],
        copied_context_available_bytes=prompt_stats["copied_context_available_bytes"],
        copied_context_sources=prompt_stats["copied_context_sources"],
        copied_context_truncated_sources=prompt_stats["copied_context_truncated_sources"],
        copied_context_by_class=prompt_stats["copied_context_by_class"],
        completeness="complete" if not missing else f"incomplete ({', '.join(missing)})",
        raw_duration=raw_duration,
        observed_duration=observed_duration,
        duration=adjusted_duration,
        manual_time_tax_seconds=manual_time_tax_seconds,
        manual_time_tax_label=format_duration(manual_time_tax_seconds),
        lane_idle_seconds=lane_idle_seconds,
        lane_idle_label=format_duration(lane_idle_seconds),
    )


def is_operator_touch(event: SimulationEvent) -> bool:
    return (
        event.event_type == "human_prompt"
        or (event.event_type == "command" and event.source == "human")
        or event.event_type == "ae_command"
        or event.event_type == "human_action"
    )


def run_duration(events_by_track: dict[str, list[SimulationEvent]]) -> DurationWindow:
    return measured_duration_window(
        [event for events in events_by_track.values() for event in events]
    )


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


def measured_duration_window(events: list[SimulationEvent]) -> DurationWindow:
    measured_events = [event for event in events if _is_duration_boundary_event(event)]
    return duration_window(measured_events or events)


def add_duration_tax(window: DurationWindow, seconds: float) -> DurationWindow:
    if window.seconds is None:
        return window
    adjusted = max(0.0, window.seconds + seconds)
    return DurationWindow(
        started_at=window.started_at,
        ended_at=window.ended_at,
        seconds=adjusted,
        label=format_duration(adjusted),
    )


def manual_time_tax(events: list[SimulationEvent]) -> float:
    total = 0.0
    for event in events:
        if event.event_type != "human_action":
            continue
        value = event.payload.get("duration_seconds")
        if value is None:
            continue
        try:
            total += max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    return total


def checkpoint_idle_seconds(events: list[SimulationEvent]) -> float:
    checkpoint_times = [
        parsed
        for event in events
        if event.event_type == "checkpoint"
        if (parsed := _parse_timestamp(event.timestamp)) is not None
    ]
    measured_times = [
        parsed
        for event in events
        if _is_duration_boundary_event(event)
        if (parsed := _parse_timestamp(event.timestamp)) is not None
    ]
    if not checkpoint_times or not measured_times:
        return 0.0
    first_checkpoint = min(checkpoint_times)
    first_measured = min(measured_times)
    return max(0.0, (first_measured - first_checkpoint).total_seconds())


def _is_duration_boundary_event(event: SimulationEvent) -> bool:
    if event.event_type == "checkpoint":
        return False
    return not event.summary.lower().startswith("preflight ")


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


def _prompt_stats(prompts: list[SimulationEvent]) -> dict[str, object]:
    prompt_chars = 0
    prompt_bytes = 0
    prompt_metadata_count = 0
    max_prompt_chars = 0
    max_prompt_bytes = 0
    copied_context_bytes = 0
    copied_context_available_bytes = 0
    copied_context_sources = 0
    copied_context_truncated_sources = 0
    copied_context_by_class: dict[str, int] = {}
    for prompt in prompts:
        text = str(prompt.payload.get("prompt") or "")
        char_count = int(prompt.payload.get("prompt_char_count") or len(text))
        byte_count = int(prompt.payload.get("prompt_byte_count") or len(text.encode("utf-8")))
        prompt_chars += char_count
        prompt_bytes += byte_count
        max_prompt_chars = max(max_prompt_chars, char_count)
        max_prompt_bytes = max(max_prompt_bytes, byte_count)
        metadata = prompt.payload.get("prompt_metadata")
        if not isinstance(metadata, dict):
            continue
        prompt_metadata_count += 1
        context_class = str(metadata.get("copied_context_class") or "other")
        embedded = int(metadata.get("total_embedded_bytes") or 0)
        available = int(metadata.get("total_available_bytes") or 0)
        sources = int(metadata.get("source_count") or 0)
        truncated = int(metadata.get("truncated_source_count") or 0)
        copied_context_bytes += embedded
        copied_context_available_bytes += available
        copied_context_sources += sources
        copied_context_truncated_sources += truncated
        copied_context_by_class[context_class] = (
            copied_context_by_class.get(context_class, 0) + embedded
        )
    return {
        "prompt_chars": prompt_chars,
        "prompt_bytes": prompt_bytes,
        "prompt_metadata_count": prompt_metadata_count,
        "prompt_metadata_missing": max(0, len(prompts) - prompt_metadata_count),
        "max_prompt_chars": max_prompt_chars,
        "max_prompt_bytes": max_prompt_bytes,
        "copied_context_bytes": copied_context_bytes,
        "copied_context_available_bytes": copied_context_available_bytes,
        "copied_context_sources": copied_context_sources,
        "copied_context_truncated_sources": copied_context_truncated_sources,
        "copied_context_by_class": copied_context_by_class,
    }
