from __future__ import annotations

import json
from pathlib import Path

from .config import Paths
from .scenario import DEFAULT_RUNTIME_POLICY, Scenario, load_scenario
from .schema import SimulationEvent, Track, append_event, utc_now_iso

TRACKS: tuple[Track, ...] = ("plain-codex", "workerbee-codex")

RUNTIME_POLICY = DEFAULT_RUNTIME_POLICY


def normalize_tracks(tracks: list[str] | tuple[str, ...] | None = None) -> tuple[Track, ...]:
    if not tracks:
        return TRACKS
    allowed = set(TRACKS)
    normalized: list[Track] = []
    for track in tracks:
        if track not in allowed:
            raise ValueError(f"Unsupported track: {track}")
        if track not in normalized:
            normalized.append(track)  # type: ignore[arg-type]
    if not normalized:
        return TRACKS
    return tuple(normalized)


def ops_mode_for_tracks(tracks: tuple[Track, ...]) -> str:
    return "comparison" if tuple(tracks) == TRACKS else "single-lane"


def active_tracks_from_manifest(manifest: dict[str, object]) -> tuple[Track, ...]:
    explicit = manifest.get("active_tracks")
    if isinstance(explicit, list):
        return normalize_tracks([str(track) for track in explicit])
    tracks = manifest.get("tracks")
    if isinstance(tracks, dict):
        ordered = [track for track in TRACKS if track in tracks]
        if ordered:
            return normalize_tracks(ordered)
    return TRACKS


def active_tracks_for_run(run_root: Path) -> tuple[Track, ...]:
    manifest_path = run_root / "manifest.json"
    if not manifest_path.exists():
        return TRACKS
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return TRACKS
    if not isinstance(manifest, dict):
        return TRACKS
    return active_tracks_from_manifest(manifest)


def is_comparison_run(run_root: Path) -> bool:
    return ops_mode_for_tracks(active_tracks_for_run(run_root)) == "comparison"


def runtime_policy_for_tracks(
    runtime_policy: dict[str, object],
    tracks: tuple[Track, ...],
) -> dict[str, object]:
    return {track: runtime_policy.get(track, {}) for track in tracks}


def init_run(
    paths: Paths,
    run_id: str,
    scenario: Scenario | None = None,
    tracks: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Path]:
    resolved = scenario or load_scenario(paths.repo_root)
    active_tracks = normalize_tracks(tracks)
    run_root = paths.runs_dir / run_id
    created: dict[str, Path] = {"run_root": run_root}
    for track in active_tracks:
        track_root = run_root / track
        for child in (
            "codex",
            "commands",
            "evidence/screenshots",
            "evidence/video",
            "prompts",
            "reports",
        ):
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
    runtime_policy = runtime_policy_for_tracks(resolved.runtime_policy, active_tracks)
    manifest = {
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "ops_mode": ops_mode_for_tracks(active_tracks),
        "report_mode": ops_mode_for_tracks(active_tracks),
        "all_tracks": list(TRACKS),
        "active_tracks": list(active_tracks),
        "tracks": {track: str(run_root / track) for track in active_tracks},
        "target_label": resolved.target_label,
        "target_root": str(resolved.target_root),
        "feature_prompt": resolved.feature_prompt,
        "padawan_root": str(resolved.target_root),
        "k1s_root": str(resolved.k1s_root),
        "workerbee_root": str(resolved.workerbee_root),
        "runtime_policy": runtime_policy,
        "scenario": resolved.to_manifest(),
    }
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return created
