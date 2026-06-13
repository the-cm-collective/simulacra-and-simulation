from __future__ import annotations

from simulacra.metrics import is_operator_touch, track_metrics
from simulacra.schema import SimulationEvent


def test_operator_touches_exclude_workerbee_actions() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="human_prompt",
            source="human",
            summary="prompted Codex",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="command",
            source="human",
            summary="ran manual wrapper command",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="human_action",
            source="human",
            summary="copied logs",
            payload={"kind": "copy_logs"},
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="ae_command",
            source="ae",
            summary="checked k1s deployment",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="workerbee_tool",
            source="workerbee",
            summary="deployed workload",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="command",
            source="codex",
            summary="ran automated command",
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.prompts == 1
    assert metrics.human_commands == 1
    assert metrics.human_actions == 1
    assert metrics.ae_actions == 1
    assert metrics.operator_touches == 4
    assert metrics.workerbee_actions == 1
    assert metrics.codex_commands == 1
    assert metrics.automation_actions == 2
    assert not is_operator_touch(events[4])


def test_token_metrics_separate_cumulative_usage_from_turn_input_snapshots() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn one",
            payload={
                "usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 2,
                    "output_tokens": 3,
                    "reasoning_output_tokens": 1,
                }
            },
        ),
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn two",
            payload={
                "usage": {
                    "input_tokens": 25,
                    "cached_input_tokens": 8,
                    "output_tokens": 4,
                    "reasoning_output_tokens": 2,
                }
            },
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.usage_snapshots == 2
    assert metrics.input_tokens == 35
    assert metrics.cached_input_tokens == 10
    assert metrics.output_tokens == 7
    assert metrics.reasoning_output_tokens == 3
    assert metrics.final_turn_input_tokens == 25
    assert metrics.max_turn_input_tokens == 25
    assert metrics.final_cached_turn_input_tokens == 8
    assert metrics.max_cached_turn_input_tokens == 8


def test_evidence_phases_are_reported() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="evidence",
            source="playwright",
            summary="local evidence",
            payload={"phase": "local"},
        ),
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="evidence",
            source="playwright",
            summary="ha evidence",
            payload={"phase": "k1s-dev-a"},
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.evidence == 2
    assert metrics.evidence_phases == ("k1s-dev-a", "local")


def test_completeness_requires_final_k1s_dev_a_evidence() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="human_prompt",
            source="human",
            summary="asked codex to implement feature",
        ),
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="command",
            source="human",
            summary="ran local validation",
        ),
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="evidence",
            source="playwright",
            summary="local evidence",
            payload={"phase": "local"},
        ),
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn completed",
            payload={"usage": {"input_tokens": 10}},
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.completeness == "incomplete (k1s-dev-a evidence)"

    events.append(
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="evidence",
            source="playwright",
            summary="ha evidence",
            payload={"phase": "k1s-dev-a"},
        )
    )

    metrics = track_metrics(events)

    assert metrics.completeness == "complete"


def test_workerbee_local_phase_counts_as_local_evidence() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="human_prompt",
            source="human",
            summary="asked codex to use workerbee",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="workerbee_tool",
            source="workerbee",
            summary="deployed local profile",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="evidence",
            source="playwright",
            summary="workerbee local evidence",
            payload={"phase": "workerbee-local"},
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="evidence",
            source="playwright",
            summary="ha evidence",
            payload={"phase": "k1s-dev-a"},
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn completed",
            payload={"usage": {"input_tokens": 10}},
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.evidence_phases == ("k1s-dev-a", "workerbee-local")
    assert metrics.completeness == "complete"


def test_codex_turn_started_without_usage_marks_usage_partial() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn started",
            payload={"raw_type": "turn.started"},
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn completed",
            payload={"usage": {"input_tokens": 10}},
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.codex_turns_started == 1
    assert metrics.usage_snapshots == 1
    assert metrics.codex_turns_missing_usage == 0

    events.insert(
        0,
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="interrupted turn",
            payload={"raw_type": "turn.started"},
        ),
    )

    metrics = track_metrics(events)

    assert metrics.codex_turns_started == 2
    assert metrics.usage_snapshots == 1
    assert metrics.codex_turns_missing_usage == 1
    assert "codex usage partial (1 turn)" in metrics.completeness
