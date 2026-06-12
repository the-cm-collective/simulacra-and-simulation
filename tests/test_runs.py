from __future__ import annotations

import json
from pathlib import Path

from simulacra.config import Paths
from simulacra.runs import init_run
from simulacra.schema import read_events


def test_init_run_creates_track_state(tmp_path: Path) -> None:
    paths = Paths(
        repo_root=tmp_path,
        padawan_root=tmp_path / "padawan",
        k1s_root=tmp_path / "k1s",
        workerbee_root=tmp_path / "workerbee",
    )

    created = init_run(paths, "calib-001")

    assert created["run_root"] == tmp_path / ".local" / "runs" / "calib-001"
    manifest = json.loads((created["run_root"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runtime_policy"]["plain-codex"]["local_container_runtime"] == "podman"
    assert manifest["runtime_policy"]["workerbee-codex"]["workerbee_target"] == "profile"
    for track in ("plain-codex", "workerbee-codex"):
        assert (created[track] / "events.jsonl").exists()
        events = read_events(created[track] / "events.jsonl")
        assert events[0].event_type == "checkpoint"
