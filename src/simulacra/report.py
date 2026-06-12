from __future__ import annotations

import json
from pathlib import Path

from .codex_events import aggregate_usage
from .runs import TRACKS
from .schema import read_events


def render_run_report(run_root: Path) -> str:
    lines = [f"# Simulation Run Report: {run_root.name}", ""]
    manifest_path = run_root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        lines.extend(
            [
                f"- Created: `{manifest.get('created_at', 'unknown')}`",
                f"- Padawan: `{manifest.get('padawan_root', '')}`",
                f"- k1s: `{manifest.get('k1s_root', '')}`",
                f"- WorkerBee: `{manifest.get('workerbee_root', '')}`",
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
    for track in TRACKS:
        events = read_events(run_root / track / "events.jsonl")
        prompts = [event for event in events if event.event_type == "human_prompt"]
        commands = [
            event
            for event in events
            if event.event_type in {"command", "ae_command", "workerbee_tool"}
        ]
        workerbee_actions = [event for event in events if event.event_type == "workerbee_tool"]
        evidence = [event for event in events if event.event_type == "evidence"]
        violations = [event for event in events if event.event_type == "protocol_violation"]
        usage = aggregate_usage(events)
        missing = _missing_measurements(
            prompts=bool(prompts),
            commands=bool(commands),
            evidence=bool(evidence),
            usage=any(usage.values()),
        )
        completeness = "complete" if not missing else f"incomplete ({', '.join(missing)})"
        lines.extend(
            [
                f"## {track}",
                "",
                f"- Measurement completeness: {completeness}",
                f"- Events: {len(events)}",
                f"- Human prompts: {len(prompts)}",
                f"- Commands: {len(commands)}",
                f"- WorkerBee actions: {len(workerbee_actions)}",
                f"- Evidence artifacts: {len(evidence)}",
                f"- Protocol violations: {len(violations)}",
                f"- Input tokens: {usage['input_tokens']}",
                f"- Cached input tokens: {usage['cached_input_tokens']}",
                f"- Output tokens: {usage['output_tokens']}",
                f"- Reasoning output tokens: {usage['reasoning_output_tokens']}",
                "",
            ]
        )
    return "\n".join(lines)


def _missing_measurements(
    *, prompts: bool, commands: bool, evidence: bool, usage: bool
) -> list[str]:
    missing = []
    if not prompts:
        missing.append("human_prompt")
    if not commands:
        missing.append("command/tool")
    if not evidence:
        missing.append("evidence")
    if not usage:
        missing.append("token usage")
    return missing
