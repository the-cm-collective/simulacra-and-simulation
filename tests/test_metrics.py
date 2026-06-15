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


def test_token_metrics_delta_cumulative_usage_but_keep_context_snapshots() -> None:
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
    assert metrics.input_tokens == 25
    assert metrics.cached_input_tokens == 8
    assert metrics.output_tokens == 4
    assert metrics.reasoning_output_tokens == 2
    assert metrics.final_turn_input_tokens == 25
    assert metrics.max_turn_input_tokens == 25
    assert metrics.final_cached_turn_input_tokens == 8
    assert metrics.max_cached_turn_input_tokens == 8


def test_token_metrics_treat_decreased_snapshot_as_new_session() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn one",
            payload={"usage": {"input_tokens": 25, "cached_input_tokens": 8}},
        ),
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="fresh session turn",
            payload={"usage": {"input_tokens": 10, "cached_input_tokens": 2}},
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.input_tokens == 35
    assert metrics.cached_input_tokens == 10
    assert metrics.final_turn_input_tokens == 10
    assert metrics.max_turn_input_tokens == 25


def test_mcp_observation_tokens_are_added_to_estimated_all_in_input() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn one",
            payload={"usage": {"input_tokens": 100, "output_tokens": 5}},
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="mcp_observation",
            source="simctl",
            summary="measured WorkerBee status artifact",
            payload={
                "mcp_visible": True,
                "included_in_codex_usage": False,
                "byte_count": 400,
                "token_count": 75,
            },
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="mcp_observation",
            source="simctl",
            summary="already counted WorkerBee artifact",
            payload={
                "mcp_visible": True,
                "included_in_codex_usage": True,
                "byte_count": 200,
                "token_count": 25,
            },
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="mcp_observation",
            source="simctl",
            summary="hidden diagnostic artifact",
            payload={"mcp_visible": False, "byte_count": 1000, "token_count": 250},
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.input_tokens == 100
    assert metrics.mcp_observation_events == 2
    assert metrics.mcp_observation_bytes == 600
    assert metrics.mcp_observation_input_tokens == 100
    assert metrics.mcp_observation_included_input_tokens == 25
    assert metrics.estimated_all_in_input_tokens == 175


def test_provider_reconciliation_metrics_use_latest_event() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn completed",
            payload={
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 10,
                    "output_tokens": 5,
                    "reasoning_output_tokens": 0,
                }
            },
            timestamp="2026-06-14T00:00:00+00:00",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="billing_reconciliation",
            source="openai-admin-api",
            summary="old reconciliation",
            payload={
                "phase": "provider_reconciliation",
                "provider_input_tokens": 50,
                "provider_cached_input_tokens": 5,
                "provider_output_tokens": 2,
                "provider_model_requests": 1,
                "provider_cost_value": 0.001,
                "provider_cost_currency": "usd",
                "match_basis": "mismatch",
            },
            timestamp="2026-06-14T00:01:00+00:00",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="billing_reconciliation",
            source="openai-admin-api",
            summary="latest reconciliation",
            payload={
                "phase": "provider_reconciliation",
                "provider_input_tokens": 100,
                "provider_cached_input_tokens": 10,
                "provider_output_tokens": 5,
                "provider_model_requests": 2,
                "provider_cost_value": 0.002,
                "provider_cost_currency": "usd",
                "provider_input_delta_vs_captured": 0,
                "provider_input_delta_vs_estimated_all_in": 0,
                "match_basis": "captured_codex",
            },
            timestamp="2026-06-14T00:02:00+00:00",
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.provider_reconciliation_events == 2
    assert metrics.provider_input_tokens == 100
    assert metrics.provider_cached_input_tokens == 10
    assert metrics.provider_output_tokens == 5
    assert metrics.provider_model_requests == 2
    assert metrics.provider_cost_value == 0.002
    assert metrics.provider_cost_currency == "usd"
    assert metrics.provider_input_delta_vs_captured == 0
    assert metrics.provider_match_basis == "captured_codex"


def test_runtime_excludes_checkpoint_idle_and_applies_manual_time_tax() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="checkpoint",
            source="simctl",
            summary="run initialized",
            timestamp="2026-06-13T00:00:00+00:00",
        ),
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="human_prompt",
            source="human",
            summary="first measured prompt",
            timestamp="2026-06-13T00:05:00+00:00",
        ),
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="human_action",
            source="human",
            summary="manual cert setup",
            payload={"duration_seconds": 60},
            timestamp="2026-06-13T00:06:00+00:00",
        ),
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="evidence",
            source="playwright",
            summary="final evidence",
            timestamp="2026-06-13T00:07:00+00:00",
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.raw_duration.seconds == 420
    assert metrics.observed_duration.seconds == 120
    assert metrics.manual_time_tax_seconds == 60
    assert metrics.duration.seconds == 180
    assert metrics.lane_idle_seconds == 300


def test_runtime_excludes_shared_preflight_lead_in() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="checkpoint",
            source="simctl",
            summary="run initialized",
            timestamp="2026-06-13T00:00:00+00:00",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="workerbee_tool",
            source="workerbee",
            summary="preflight WorkerBee Caddy route isolation",
            timestamp="2026-06-13T00:00:03+00:00",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="human_prompt",
            source="human",
            summary="first lane prompt",
            timestamp="2026-06-13T00:10:00+00:00",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="evidence",
            source="playwright",
            summary="final evidence",
            timestamp="2026-06-13T00:11:00+00:00",
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.raw_duration.seconds == 660
    assert metrics.observed_duration.seconds == 60
    assert metrics.duration.seconds == 60
    assert metrics.lane_idle_seconds == 600


def test_runtime_excludes_generated_mcp_observations() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="human_prompt",
            source="human",
            summary="first lane prompt",
            timestamp="2026-06-13T00:00:00+00:00",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="evidence",
            source="playwright",
            summary="final evidence",
            timestamp="2026-06-13T00:05:00+00:00",
        ),
        SimulationEvent(
            run_id="r1",
            track="workerbee-codex",
            event_type="mcp_observation",
            source="simctl",
            summary="late generated artifact measurement",
            timestamp="2026-06-13T00:30:00+00:00",
            payload={"token_count": 10, "byte_count": 40},
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.raw_duration.seconds == 1800
    assert metrics.observed_duration.seconds == 300
    assert metrics.duration.seconds == 300


def test_prompt_and_copied_context_metrics_are_reported() -> None:
    events = [
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="human_prompt",
            source="human",
            summary="small prompt",
            payload={"prompt": "small", "prompt_byte_count": 5, "prompt_char_count": 5},
        ),
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="human_prompt",
            source="human",
            summary="copied logs",
            payload={
                "prompt": "copied logs",
                "prompt_byte_count": 11,
                "prompt_char_count": 11,
                "prompt_metadata": {
                    "copied_context_class": "local_logs",
                    "total_embedded_bytes": 100,
                    "total_available_bytes": 140,
                    "source_count": 2,
                    "truncated_source_count": 1,
                },
            },
        ),
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="human_action",
            source="human",
            summary="summarized context",
            payload={"kind": "context_management"},
        ),
    ]

    metrics = track_metrics(events)

    assert metrics.prompt_bytes == 16
    assert metrics.max_prompt_bytes == 11
    assert metrics.prompt_metadata_count == 1
    assert metrics.prompt_metadata_missing == 1
    assert metrics.copied_context_bytes == 100
    assert metrics.copied_context_available_bytes == 140
    assert metrics.copied_context_sources == 2
    assert metrics.copied_context_truncated_sources == 1
    assert metrics.copied_context_by_class == {"local_logs": 100}
    assert metrics.context_management_actions == 1


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
