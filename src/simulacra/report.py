from __future__ import annotations

import json
from pathlib import Path

from .audit import CORE_METRIC_SPECS, read_audit_report, render_audit_markdown
from .metrics import format_duration, run_duration, track_metrics
from .runs import TRACKS
from .schema import read_events


def render_run_report(run_root: Path) -> str:
    lines = [f"# Simulation Run Report: {run_root.name}", ""]
    events_by_track = {track: read_events(run_root / track / "events.jsonl") for track in TRACKS}
    duration = run_duration(events_by_track)
    manifest_path = run_root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        target_label = str(manifest.get("target_label") or "Padawan")
        target_root = str(manifest.get("target_root") or manifest.get("padawan_root") or "")
        lines.extend(
            [
                f"- Created: `{manifest.get('created_at', 'unknown')}`",
                f"- Target repo ({target_label}): `{target_root}`",
                f"- k1s: `{manifest.get('k1s_root', '')}`",
                f"- WorkerBee: `{manifest.get('workerbee_root', '')}`",
                f"- Start-to-finish runtime: `{duration.label}`",
                f"- First measured event: `{duration.started_at}`",
                f"- Last measured event: `{duration.ended_at}`",
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
            partial_note = str(
                manifest.get("partial_preview_note")
                or "Partial measurement preview, not a clean paired baseline."
            )
            lines.extend(
                [
                    "## Partial Preview",
                    "",
                    "- Status: partial measurement preview, not a clean paired baseline",
                    f"- Plain reference run: `{manifest.get('plain_reference_run', 'unknown')}`",
                    f"- Note: {manifest.get('plain_reference_note', '')}",
                    f"- Scope: {partial_note}",
                    "",
                ]
            )
        if "scenario" not in manifest and manifest.get("padawan_root"):
            lines.extend(
                [
                    "## Calibration Boundary",
                    "",
                    (
                        "- Status: legacy calibration reference, not final "
                        "strict proof-quality comparison evidence"
                    ),
                    "",
                ]
            )
        if manifest.get("lineage") or manifest.get("audit_adjustments"):
            lines.extend(_lineage_lines(manifest))
    audit = read_audit_report(run_root)
    if audit:
        lines.extend([render_audit_markdown(audit), ""])
    else:
        lines.extend(
            [
                "## Audit Status",
                "",
                "- Status: audit not run",
                "- Run `simctl audit-run --run-id <run-id>` before accepting a public baseline.",
                "",
            ]
        )
    lines.extend(_core_scorecard_lines(events_by_track, audit))
    for track in TRACKS:
        metrics = track_metrics(events_by_track[track])
        lines.extend(
            [
                f"## {track}",
                "",
                f"- Measurement completeness: {metrics.completeness}",
                f"- Realistic runtime: {metrics.duration.label}",
                f"- Manual time tax: {metrics.manual_time_tax_label}",
                f"- Pre-tax measured span (diagnostic): {metrics.observed_duration.label}",
                f"- Raw event span (diagnostic): {metrics.raw_duration.label}",
                f"- Checkpoint idle excluded (diagnostic): {metrics.lane_idle_label}",
                f"- First measured event: `{metrics.observed_duration.started_at}`",
                f"- Last measured event: `{metrics.observed_duration.ended_at}`",
                f"- Events: {metrics.events}",
                f"- Human prompts: {metrics.prompts}",
                f"- Operator touches: {metrics.operator_touches}",
                f"- Human commands: {metrics.human_commands}",
                f"- Human actions: {metrics.human_actions}",
                f"- Context-management actions: {metrics.context_management_actions}",
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
                f"- Cumulative prompt bytes: {metrics.prompt_bytes}",
                (f"- Prompt metadata coverage: {metrics.prompt_metadata_count}/{metrics.prompts}"),
                f"- Prompt metadata missing: {metrics.prompt_metadata_missing}",
                f"- Max prompt bytes: {metrics.max_prompt_bytes}",
                f"- Copied context bytes: {metrics.copied_context_bytes}",
                f"- Copied context available bytes: {metrics.copied_context_available_bytes}",
                f"- Copied context sources: {metrics.copied_context_sources}",
                f"- Copied context truncated sources: {metrics.copied_context_truncated_sources}",
                "- Copied context by class: "
                f"{_format_context_classes(metrics.copied_context_by_class)}",
                "",
            ]
        )
    return "\n".join(lines)


def _format_phases(phases: tuple[str, ...]) -> str:
    return ", ".join(phases) if phases else "none"


def _format_context_classes(values: dict[str, int]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(values.items()))


def _core_scorecard_lines(
    events_by_track: dict[str, list[object]],
    audit: dict[str, object],
) -> list[str]:
    metrics_by_track = {track: track_metrics(events) for track, events in events_by_track.items()}
    plain = metrics_by_track.get("plain-codex")
    workerbee = metrics_by_track.get("workerbee-codex")
    audit_missing = not audit
    audit_blocked = bool(audit) and not bool(audit.get("accepted"))
    lines = [
        "## Core Metric Scorecard",
        "",
        (
            "Core metrics are expected to favor WorkerBee in strict realistic runs. "
            "Plain-Codex wins are review-required anomalies unless explicitly waived."
        ),
        "",
        "| Metric | plain-codex | workerbee-codex | Status |",
        "| --- | ---: | ---: | --- |",
    ]
    for spec in CORE_METRIC_SPECS:
        if plain is None or workerbee is None:
            plain_value = workerbee_value = None
        else:
            plain_value = spec.value_fn(plain)
            workerbee_value = spec.value_fn(workerbee)
        if plain_value is None or workerbee_value is None:
            state = "n/a"
        elif audit_missing:
            state = "Review pending"
        elif audit_blocked:
            state = "Blocked"
        elif float(workerbee_value) < float(plain_value):
            state = "WorkerBee advantage"
        elif float(workerbee_value) == float(plain_value):
            state = "Neutral"
        else:
            state = "Plain anomaly"
        lines.append(
            "| "
            f"{spec.label.title()} | "
            f"{_format_score_value(plain_value, spec.unit)} | "
            f"{_format_score_value(workerbee_value, spec.unit)} | "
            f"{state} |"
        )
    lines.append("")
    return lines


def _format_score_value(value: float | int | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "duration":
        return format_duration(float(value))
    rounded = int(round(float(value)))
    if unit == "tokens":
        return f"{rounded:,} tokens"
    if unit == "bytes":
        return f"{rounded:,} bytes"
    return f"{rounded:,}"


def _lineage_lines(manifest: dict[str, object]) -> list[str]:
    lines = ["## Run Lineage", ""]
    lineage = manifest.get("lineage")
    if isinstance(lineage, dict):
        for key in ("source_run_id", "source_run_root", "created_by", "reason"):
            value = lineage.get(key)
            if value:
                label = key.replace("_", " ").title()
                lines.append(f"- {label}: `{value}`")
    adjustments = manifest.get("audit_adjustments")
    if isinstance(adjustments, list) and adjustments:
        lines.extend(["", "### Audit Adjustments", ""])
        for adjustment in adjustments:
            if isinstance(adjustment, dict):
                summary = adjustment.get("summary") or adjustment.get("id") or "adjustment"
                evidence = adjustment.get("evidence")
                line = f"- {summary}"
                if evidence:
                    line = f"{line} (`{evidence}`)"
                lines.append(line)
    lines.append("")
    return lines
