from __future__ import annotations

from simulacra.schema import SimulationEvent


def test_event_round_trip() -> None:
    event = SimulationEvent(
        run_id="calib-001",
        track="plain-codex",
        event_type="human_prompt",
        source="human",
        summary="Start",
        payload={"n": 1},
    )

    loaded = SimulationEvent.from_json(event.to_json())

    assert loaded == event
