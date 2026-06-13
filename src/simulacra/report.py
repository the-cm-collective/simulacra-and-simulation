from __future__ import annotations

import json
from pathlib import Path

from .metrics import run_duration, track_metrics
from .runs import TRACKS
from .schema import read_events


def render_run_report(run_root: Path) -> str:
    lines = [f"# Simulation Run Report: {run_root.name}", ""]
    events_by_track = {track: read_events(run_root / track / "events.jsonl") for track in TRACKS}
    duration = run_duration(events_by_track)
    manifest_path = run_root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        lines.extend(
            [
                f"- Created: `{manifest.get('created_at', 'unknown')}`",
                f"- Padawan: `{manifest.get('padawan_root', '')}`",
                f"- k1s: `{manifest.get('k1s_root', '')}`",
                f"- WorkerBee: `{manifest.get('workerbee_root', '')}`",
                f"- Start-to-finish runtime: `{duration.label}`",
                f"- First event: `{duration.started_at}`",
                f"- Last event: `{duration.ended_at}`",
                "",
            ]
        )
        runtime_policy = manifest.get("runtime_policy", {})
        if isinstance(runtime_policy, dict):
            lines.extend(["## Runtime Policy", ""])
            for track, policy in runtime_policy.items():
                if isinstance(policy, dict):
                    summary = ", ".join(f"{key}={value}" for key, value in policy.items())
                    lines.append(f"- `{track}`: {summary}")
            lines.append("")
        if manifest.get("partial_preview"):
            lines.extend(
                [
                    "## Partial Preview",
                    "",
                    "- Status: partial measurement preview, not a clean paired baseline",
                    f"- Plain reference run: `{manifest.get('plain_reference_run', 'unknown')}`",
                    f"- Note: {manifest.get('plain_reference_note', '')}",
                    "",
                ]
            )
    for track in TRACKS:
        metrics = track_metrics(events_by_track[track])
        lines.extend(
            [
                f"## {track}",
                "",
                f"- Measurement completeness: {metrics.completeness}",
                f"- Runtime: {metrics.duration.label}",
                f"- First event: `{metrics.duration.started_at}`",
                f"- Last event: `{metrics.duration.ended_at}`",
                f"- Events: {metrics.events}",
                f"- Human prompts: {metrics.prompts}",
                f"- Operator touches: {metrics.operator_touches}",
                f"- Human commands: {metrics.human_commands}",
                f"- Human actions: {metrics.human_actions}",
                f"- AE actions: {metrics.ae_actions}",
                f"- Shell/AE commands: {metrics.commands}",
                f"- Codex commands: {metrics.codex_commands}",
                f"- WorkerBee actions: {metrics.workerbee_actions}",
                f"- Automation actions: {metrics.automation_actions}",
                f"- Evidence artifacts: {metrics.evidence}",
                f"- Evidence phases: {_format_phases(metrics.evidence_phases)}",
                f"- Protocol violations: {metrics.violations}",
                f"- Codex turns started: {metrics.codex_turns_started}",
                f"- Codex usage snapshots: {metrics.usage_snapshots}",
                f"- Codex turns missing usage: {metrics.codex_turns_missing_usage}",
                f"- Cumulative billed input tokens: {metrics.input_tokens}",
                f"- Cumulative cached input tokens: {metrics.cached_input_tokens}",
                f"- Cumulative output tokens: {metrics.output_tokens}",
                f"- Cumulative reasoning output tokens: {metrics.reasoning_output_tokens}",
                f"- Final Codex turn input tokens: {metrics.final_turn_input_tokens}",
                f"- Max Codex turn input tokens: {metrics.max_turn_input_tokens}",
                f"- Final cached turn input tokens: {metrics.final_cached_turn_input_tokens}",
                f"- Max cached turn input tokens: {metrics.max_cached_turn_input_tokens}",
                "",
            ]
        )
    return "\n".join(lines)


def _format_phases(phases: tuple[str, ...]) -> str:
    return ", ".join(phases) if phases else "none"
