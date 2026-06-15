from __future__ import annotations

import json
from pathlib import Path

from simulacra.config import default_paths
from simulacra.runs import init_run
from simulacra.scenario import load_scenario
from simulacra.schema import read_events


def test_init_run_creates_track_state(tmp_path: Path) -> None:
    scenario = load_scenario(
        tmp_path,
        overrides=[
            f"target.repo_root={tmp_path / 'custom-app'}",
            "target.label=CustomApp",
            "target.feature_prompt=Build the custom app feature.",
            f"k1s.repo_root={tmp_path / 'k1s'}",
            f"workerbee.repo_root={tmp_path / 'workerbee'}",
        ],
    )
    paths = default_paths(tmp_path, scenario=scenario)

    created = init_run(paths, "calib-001", scenario=scenario)

    assert created["run_root"] == tmp_path / ".local" / "runs" / "calib-001"
    manifest = json.loads((created["run_root"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["target_label"] == "CustomApp"
    assert manifest["target_root"] == str(tmp_path / "custom-app")
    assert manifest["feature_prompt"] == "Build the custom app feature."
    assert manifest["scenario"]["target"]["label"] == "CustomApp"
    assert manifest["scenario"]["target"]["repo_root"] == str(tmp_path / "custom-app")
    assert manifest["padawan_root"] == str(tmp_path / "custom-app")
    assert manifest["runtime_policy"]["plain-codex"]["local_container_runtime"] == "podman"
    assert manifest["runtime_policy"]["workerbee-codex"]["workerbee_target"] == "profile"
    for track in ("plain-codex", "workerbee-codex"):
        assert (created[track] / "events.jsonl").exists()
        assert (created[track] / "prompts").is_dir()
        events = read_events(created[track] / "events.jsonl")
        assert events[0].event_type == "checkpoint"


def test_init_run_can_create_single_active_track(tmp_path: Path) -> None:
    scenario = load_scenario(tmp_path)
    paths = default_paths(tmp_path, scenario=scenario)

    created = init_run(paths, "workerbee-only", scenario=scenario, tracks=["workerbee-codex"])

    run_root = tmp_path / ".local" / "runs" / "workerbee-only"
    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ops_mode"] == "single-lane"
    assert manifest["active_tracks"] == ["workerbee-codex"]
    assert sorted(manifest["tracks"]) == ["workerbee-codex"]
    assert "plain-codex" not in created
    assert not (run_root / "plain-codex").exists()
    assert (created["workerbee-codex"] / "events.jsonl").exists()
