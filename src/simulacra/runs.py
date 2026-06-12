from __future__ import annotations

import json
from pathlib import Path

from .config import Paths
from .schema import SimulationEvent, Track, append_event, utc_now_iso

TRACKS: tuple[Track, ...] = ("plain-codex", "workerbee-codex")


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
    }
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return created
