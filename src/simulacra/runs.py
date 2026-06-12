from __future__ import annotations

import json
from pathlib import Path

from .config import Paths
from .schema import SimulationEvent, Track, append_event, utc_now_iso

TRACKS: tuple[Track, ...] = ("plain-codex", "workerbee-codex")

RUNTIME_POLICY = {
    "plain-codex": {
        "local_container_runtime": "podman",
        "compose_engine": "podman compose or podman-compose",
        "workerbee_allowed": False,
        "docker_allowed_in_measured_run": False,
        "k1s_actions": "ae CLI or Hive dashboard only",
    },
    "workerbee-codex": {
        "local_container_runtime": "workerbee native containerd profile",
        "workerbee_target": "profile",
        "default_profile": "k1s-dev-min-sqlite",
        "ha_profile": "k1s-ha-min",
        "podman_project_runtime_allowed_in_measured_run": False,
    },
}


def init_run(paths: Paths, run_id: str) -> dict[str, Path]:
    run_root = paths.runs_dir / run_id
    created: dict[str, Path] = {"run_root": run_root}
    for track in TRACKS:
        track_root = run_root / track
        for child in ("codex", "commands", "evidence/screenshots", "evidence/video", "reports"):
            (track_root / child).mkdir(parents=True, exist_ok=True)
        append_event(
            track_root / "events.jsonl",
            SimulationEvent(
                run_id=run_id,
                track=track,
                event_type="checkpoint",
                source="simctl",
                summary="run initialized",
                payload={"track_root": str(track_root)},
            ),
        )
        created[track] = track_root
    manifest = {
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "tracks": {track: str(run_root / track) for track in TRACKS},
        "padawan_root": str(paths.padawan_root),
        "k1s_root": str(paths.k1s_root),
        "workerbee_root": str(paths.workerbee_root),
        "runtime_policy": RUNTIME_POLICY,
    }
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return created
