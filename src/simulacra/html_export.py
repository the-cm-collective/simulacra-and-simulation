from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from urllib.parse import quote

from .audit import CORE_METRIC_SPECS, read_audit_report
from .metrics import format_duration, is_operator_touch, run_duration, track_metrics
from .runs import TRACKS
from .scenario import load_scenario
from .schema import SimulationEvent, read_events

IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".webm"}
TEXT_SUFFIXES = {".json", ".jsonl", ".log", ".md", ".txt"}
REPO_ROOT = Path(__file__).resolve().parents[2]
K1S_STATIC_ROOT = REPO_ROOT.parent / "k1s" / "docs" / "site" / "static"
SUN_ICON_PATH = (
    "M480-360q50 0 85-35t35-85q0-50-35-85t-85-35q-50 0-85 35t-35 85q0 50 "
    "35 85t85 35Zm0 80q-83 0-141.5-58.5T280-480q0-83 58.5-141.5T480-680q83 "
    "0 141.5 58.5T680-480q0 83-58.5 141.5T480-280ZM200-440H40v-80h160v80Zm720 "
    "0H760v-80h160v80ZM440-760v-160h80v160h-80Zm0 720v-160h80v160h-80ZM256-650l-101-97 "
    "57-59 96 100-52 56Zm492 496-97-101 53-55 101 97-57 59Zm-98-550 "
    "97-101 59 57-100 96-56-52ZM154-212l101-97 55 53-97 101-59-57Zm326-268Z"
)
MOON_ICON_PATH = (
    "M480-120q-150 0-255-105T120-480q0-150 105-255t255-105q14 0 27.5 "
    "1t26.5 3q-41 29-65.5 75.5T444-660q0 90 63 153t153 63q55 0 "
    "101-24.5t75-65.5q2 13 3 26.5t1 27.5q0 150-105 255T480-120Zm0-80q88 "
    "0 158-48.5T740-375q-20 5-40 8t-40 3q-123 0-209.5-86.5T364-660q0-20 "
    "3-40t8-40q-78 32-126.5 102T200-480q0 116 82 198t198 82Zm-10-270Z"
)


@dataclass(frozen=True)
class HtmlExport:
    output_dir: Path
    pages: list[Path]


@dataclass(frozen=True)
class ChartSeries:
    label: str
    track: str
    stroke: str
    predicate: Callable[[SimulationEvent], bool]


@dataclass(frozen=True)
class ComparisonSpec:
    label: str
    value_fn: Callable[[object], str]
    number_fn: Callable[[object], float | int | None] | None = None
    prefer: str = "neutral"
    unit: str = "count"


def export_run_html(run_root: Path, output_dir: Path | None = None) -> HtmlExport:
    output = output_dir or run_root / "html"
    output.mkdir(parents=True, exist_ok=True)
    _prepare_html_assets(output)
    manifest = _read_json(run_root / "manifest.json")
    events_by_track = {track: read_events(run_root / track / "events.jsonl") for track in TRACKS}
    metrics_by_track = {track: track_metrics(events) for track, events in events_by_track.items()}
    duration = run_duration(events_by_track)
    report_path = run_root / "report.md"
    audit = read_audit_report(run_root)
    pages = [
        _write(
            output / "executive.html",
            _executive_page(run_root, manifest, metrics_by_track, duration, audit),
        ),
        _write(
            output / "index.html",
            _index_page(run_root, output, manifest, metrics_by_track, duration, report_path, audit),
        ),
        _write(
            output / "technical.html",
            _technical_page(run_root, output, manifest, metrics_by_track, duration, audit),
        ),
        _write(
            output / "charts.html",
            _charts_page(run_root, metrics_by_track, events_by_track, audit),
        ),
        _write(output / "timeline.html", _timeline_page(run_root, output, events_by_track)),
        _write(output / "evidence.html", _artifacts_page(run_root, output, events_by_track)),
    ]
    return HtmlExport(output_dir=output, pages=pages)


def _target_prompt_panel(manifest: dict[str, object]) -> str:
    scenario = _scenario_mapping(manifest)
    target = _mapping_value(scenario, "target")
    k1s = _mapping_value(scenario, "k1s")
    workerbee = _mapping_value(scenario, "workerbee")
    target_label = str(manifest.get("target_label") or target.get("label") or "Target")
    target_root = str(
        manifest.get("target_root") or manifest.get("padawan_root") or target.get("repo_root") or ""
    )
    feature_prompt = str(manifest.get("feature_prompt") or target.get("feature_prompt") or "")
    prompt_text = feature_prompt or "No feature/input prompt recorded in this run manifest."
    rows = _meta_rows(
        [
            ("Scenario", scenario.get("name") or "unknown"),
            ("Scenario source", scenario.get("source") or "unknown"),
            ("Target label", target_label),
            ("Target repo", target_root),
            ("k1s repo", manifest.get("k1s_root") or k1s.get("repo_root") or ""),
            (
                "WorkerBee repo",
                manifest.get("workerbee_root") or workerbee.get("repo_root") or "",
            ),
        ]
    )
    return f"""
<section class="panel">
  <h2>Target &amp; Input Prompt</h2>
  <dl class="meta">{rows}</dl>
  <h3>Input Prompt</h3>
  <pre class="prompt-block">{escape(prompt_text)}</pre>
</section>
"""


def _simulation_settings_panel(manifest: dict[str, object]) -> str:
    settings = _review_settings(manifest)
    rows = "".join(
        f"<tr><th>{escape(key)}</th><td>{_setting_value_html(value)}</td></tr>"
        for key, value in _flatten_settings(settings)
    )
    if not rows:
        rows = '<tr><td colspan="2" class="empty">No simulation settings recorded.</td></tr>'
    return f"""
<section class="panel">
  <h2>Simulation Settings</h2>
  <p>
    These values are copied from the frozen run manifest and scenario snapshot.
    They define the measured target, prompt, runtime policy, preflight gates,
    ingress checks, evidence command, and WorkerBee stage patch behavior.
  </p>
  <table class="settings-table">
    <thead><tr><th>Setting</th><th>Value</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
"""


def _lineage_panel(manifest: dict[str, object]) -> str:
    lineage = manifest.get("lineage")
    adjustments = manifest.get("audit_adjustments")
    if not isinstance(lineage, dict) and not (isinstance(adjustments, list) and adjustments):
        return ""
    rows = []
    if isinstance(lineage, dict):
        rows.extend(
            [
                ("Source run", lineage.get("source_run_id")),
                ("Source root", lineage.get("source_run_root")),
                ("Created by", lineage.get("created_by")),
                ("Reason", lineage.get("reason")),
            ]
        )
    adjustment_rows = ""
    if isinstance(adjustments, list) and adjustments:
        rendered = []
        for adjustment in adjustments:
            if not isinstance(adjustment, dict):
                continue
            summary = adjustment.get("summary") or adjustment.get("id") or "adjustment"
            evidence = adjustment.get("evidence")
            if evidence:
                rendered.append(
                    f"<li>{escape(str(summary))} <code>{escape(str(evidence))}</code></li>"
                )
            else:
                rendered.append(f"<li>{escape(str(summary))}</li>")
        if rendered:
            adjustment_rows = f"<h3>Audit Adjustments</h3><ul>{''.join(rendered)}</ul>"
    return f"""
<section class="panel">
  <h2>Run Lineage</h2>
  <dl class="meta">{_meta_rows(rows)}</dl>
  {adjustment_rows}
</section>
"""


def _audit_panel(audit: dict[str, object], *, compact: bool = False) -> str:
    if not audit:
        return """
<section class="panel audit-panel audit-not-run">
  <h2>Audit Status</h2>
  <p><strong>Status:</strong> Audit not run.</p>
  <p>
    Run <code>simctl audit-run --run-id &lt;run-id&gt;</code>
    before accepting a public baseline.
  </p>
</section>
"""
    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    accepted = bool(audit.get("accepted"))
    status = "accepted" if accepted else "blocked"
    status_class = "audit-accepted" if accepted else "audit-blocked"
    findings = audit.get("findings") if isinstance(audit.get("findings"), list) else []
    if compact:
        dict_findings = [finding for finding in findings if isinstance(finding, dict)]
        selected = [finding for finding in dict_findings if finding.get("severity") == "error"] or [
            finding for finding in dict_findings if finding.get("severity") == "warning"
        ][:5]
        rows = "".join(_audit_finding_row(finding) for finding in selected)
    else:
        rows = "".join(
            _audit_finding_row(finding) for finding in findings if isinstance(finding, dict)
        )
    if not rows:
        rows = '<tr><td colspan="4" class="empty">No audit findings.</td></tr>'
    return f"""
<section class="panel audit-panel {status_class}">
  <h2>Audit Status</h2>
  <dl class="meta">
    <dt>Profile</dt><dd><code>{escape(str(audit.get("profile") or "unknown"))}</code></dd>
    <dt>Status</dt><dd><span class="audit-pill {status_class}">{escape(status)}</span></dd>
    <dt>Errors</dt><dd>{summary.get("error", 0)}</dd>
    <dt>Warnings</dt><dd>{summary.get("warning", 0)}</dd>
    <dt>Generated</dt><dd><code>{escape(str(audit.get("generated_at") or "unknown"))}</code></dd>
  </dl>
  <table class="audit-table">
    <thead><tr><th>Severity</th><th>Check</th><th>Track</th><th>Finding</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
"""


def _audit_finding_row(finding: dict[str, object]) -> str:
    severity = str(finding.get("severity") or "")
    check_id = str(finding.get("check_id") or "")
    track = str(finding.get("track") or "run")
    message = str(finding.get("message") or "")
    remediation = finding.get("remediation")
    evidence_ref = finding.get("evidence_ref")
    detail = escape(message)
    if remediation:
        detail += f"<br><strong>Remediation:</strong> {escape(str(remediation))}"
    if evidence_ref:
        detail += f"<br><strong>Evidence:</strong> <code>{escape(str(evidence_ref))}</code>"
    return (
        f'<tr class="audit-row audit-{escape(severity)}">'
        f"<td>{escape(severity)}</td>"
        f"<td><code>{escape(check_id)}</code></td>"
        f"<td>{escape(track)}</td>"
        f"<td>{detail}</td>"
        "</tr>"
    )


def _runtime_measurement_panel(metrics_by_track: dict[str, object]) -> str:
    rows = []
    for track, metrics in metrics_by_track.items():
        rows.append(
            "<tr>"
            f"<th>{escape(track)}</th>"
            f"<td>{escape(metrics.duration.label)}</td>"
            f"<td>{escape(metrics.manual_time_tax_label)}</td>"
            f"<td>{escape(metrics.observed_duration.label)}</td>"
            f"<td>{escape(metrics.raw_duration.label)}</td>"
            f"<td>{escape(metrics.lane_idle_label)}</td>"
            f"<td><code>{escape(metrics.observed_duration.started_at)}</code></td>"
            f"<td><code>{escape(metrics.observed_duration.ended_at)}</code></td>"
            "</tr>"
        )
    return f"""
<section class="panel">
  <h2>Measurement Integrity</h2>
  <p>
    Realistic runtime is the comparable runtime used for deltas and charts:
    pre-tax measured span plus explicit manual time-tax events. Pre-tax measured
    span, raw event span, and checkpoint setup idle are diagnostic fields only;
    they are retained for auditability but are not scored as runtime wins.
  </p>
  <table>
    <thead>
      <tr>
        <th>Track</th><th>Realistic Runtime</th><th>Manual Time Tax</th>
        <th>Pre-Tax Measured Span</th><th>Raw Event Span</th>
        <th>Checkpoint Idle Excluded</th><th>First Real Work Event</th>
        <th>Last Measured Event</th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</section>
"""


def _index_page(
    run_root: Path,
    output_dir: Path,
    manifest: dict[str, object],
    metrics_by_track: dict[str, object],
    duration,
    report_path: Path,
    audit: dict[str, object],
) -> str:
    rows = []
    for track, metrics in metrics_by_track.items():
        rows.append(
            "<tr>"
            f"<th>{escape(track)}</th>"
            f"<td>{escape(metrics.duration.label)}</td>"
            f"<td>{escape(metrics.manual_time_tax_label)}</td>"
            f"<td>{metrics.events}</td>"
            f"<td>{metrics.operator_touches}</td>"
            f"<td>{metrics.prompts}</td>"
            f"<td>{_prompt_metadata_coverage(metrics)}</td>"
            f"<td>{metrics.human_commands}</td>"
            f"<td>{metrics.human_actions}</td>"
            f"<td>{metrics.context_management_actions}</td>"
            f"<td>{metrics.ae_actions}</td>"
            f"<td>{metrics.workerbee_actions}</td>"
            f"<td>{metrics.evidence}</td>"
            f"<td>{escape(', '.join(metrics.evidence_phases) or 'none')}</td>"
            f"<td>{metrics.violations}</td>"
            f"<td>{metrics.codex_turns_started}</td>"
            f"<td>{metrics.usage_snapshots}</td>"
            f"<td>{metrics.codex_turns_missing_usage}</td>"
            f"<td>{metrics.input_tokens}</td>"
            f"<td>{metrics.final_turn_input_tokens}</td>"
            f"<td>{metrics.max_turn_input_tokens}</td>"
            f"<td>{metrics.output_tokens}</td>"
            f"<td>{metrics.prompt_bytes}</td>"
            f"<td>{metrics.max_prompt_bytes}</td>"
            f"<td>{metrics.copied_context_bytes}</td>"
            f"<td>{metrics.copied_context_sources}</td>"
            f"<td>{escape(metrics.completeness)}</td>"
            "</tr>"
        )
    manifest_items = "".join(
        f"<dt>{escape(str(key))}</dt><dd><code>{escape(str(value))}</code></dd>"
        for key, value in manifest.items()
        if key not in {"tracks", "runtime_policy", "scenario"}
    )
    runtime_policy = _json_block(manifest.get("runtime_policy", {}))
    report = (
        report_path.read_text(encoding="utf-8") if report_path.exists() else "report.md not found"
    )
    body = f"""
{_target_prompt_panel(manifest)}
{_lineage_panel(manifest)}
<section class="panel">
  <h2>Run Summary</h2>
  <dl class="meta">{manifest_items}</dl>
  <p><strong>Start-to-finish runtime:</strong> {escape(duration.label)}</p>
  <p><strong>First measured event:</strong> <code>{escape(duration.started_at)}</code></p>
  <p><strong>Last measured event:</strong> <code>{escape(duration.ended_at)}</code></p>
  <p>
    <strong>Operator touches</strong> count human prompts, human shell commands,
    AE/dashboard actions, and explicit human-action events. WorkerBee tool calls
    are automation actions and are shown separately.
  </p>
  <p>
    Token totals are cumulative sums from recorded Codex usage events. Codex
    turn input tokens are per-turn usage snapshots, not literal context-window
    measurements. Missing usage counts indicate Codex turns that started but did
    not emit a completed usage record.
  </p>
</section>
{_audit_panel(audit)}
{_runtime_measurement_panel(metrics_by_track)}
<section class="panel">
  <h2>Track Metrics</h2>
  <table>
    <thead>
      <tr>
        <th>Track</th><th>Realistic Runtime</th><th>Manual Time Tax</th>
        <th>Events</th><th>Operator Touches</th>
        <th>Prompts</th><th>Prompt Metadata</th>
        <th>Human Commands</th><th>Human Actions</th>
        <th>Context Mgmt</th><th>AE Actions</th>
        <th>WorkerBee</th><th>Evidence</th><th>Evidence Phases</th><th>Violations</th>
        <th>Codex Turns</th><th>Usage Snapshots</th><th>Missing Usage</th>
        <th>Cumulative Billed Input</th><th>Final Turn Input</th><th>Max Turn Input</th>
        <th>Cumulative Output</th><th>Cumulative Prompt Bytes</th>
        <th>Max Prompt Bytes</th><th>Copied Context Bytes</th>
        <th>Copied Context Sources</th><th>Completeness</th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Runtime Policy</h2>
  {runtime_policy}
</section>
{_simulation_settings_panel(manifest)}
<section class="panel">
  <h2>Markdown Report</h2>
  <p><a href="{_href(report_path, output_dir)}">Open raw report.md</a></p>
  <pre>{escape(report)}</pre>
</section>
"""
    return _page(run_root.name, "Summary", body)


def _executive_page(
    run_root: Path,
    manifest: dict[str, object],
    metrics_by_track: dict[str, object],
    duration,
    audit: dict[str, object],
) -> str:
    target_label = str(manifest.get("target_label") or "Padawan")
    complete = all(metrics.completeness == "complete" for metrics in metrics_by_track.values())
    violation_count = sum(metrics.violations for metrics in metrics_by_track.values())
    partial_preview = bool(manifest.get("partial_preview"))
    legacy_calibration = _is_legacy_calibration(manifest)
    audit_accepted = not audit or bool(audit.get("accepted"))
    if partial_preview:
        status = "Partial Preview"
    elif legacy_calibration:
        status = "Calibration Reference"
    elif complete and violation_count == 0 and audit_accepted:
        status = "Complete"
    else:
        status = "Needs Review"
    if partial_preview:
        default_note = (
            "The plain-Codex lane is copied from "
            f"{manifest.get('plain_reference_run', 'a prior run')} as "
            "non-contemporaneous reference data. Use this package to review "
            "patched metrics before a full clean paired rerun."
        )
        status_text = (
            "This package is a partial measurement preview. "
            f"{manifest.get('partial_preview_note') or default_note}"
        )
    elif legacy_calibration:
        status_text = (
            "This run predates frozen scenario snapshots and the strict proof "
            "contract. Use it as historical calibration only, not as final "
            "proof-quality comparison evidence."
        )
    elif complete and violation_count == 0 and audit_accepted:
        status_text = (
            "This run produced complete measurement streams for the constrained "
            "plain-Codex path and the WorkerBee direct-containerd path. Both "
            "browser evidence lanes are present, and operator keyboard effort is "
            "reported as operator touches."
        )
    elif audit and not audit_accepted:
        status_text = (
            "This run produced complete evidence streams, but the audit blocks it "
            "as a clean baseline until the listed measurement-contract findings "
            "are rerun or resolved."
        )
    else:
        gaps = "; ".join(
            f"{track}: {metrics.completeness}"
            for track, metrics in metrics_by_track.items()
            if metrics.completeness != "complete"
        )
        status_text = (
            "This run produced useful runtime evidence, but it is not accepted as "
            "a complete baseline comparison until the measurement gaps are rerun "
            f"or resolved. Current gaps: {gaps or 'protocol violations present'}."
        )
    diagnostic_deltas = _audit_blocks_deltas(audit)
    rows = _comparison_rows(metrics_by_track, diagnostic=diagnostic_deltas)
    delta_cards = _delta_cards(metrics_by_track, diagnostic=diagnostic_deltas)
    delta_note = _delta_note(diagnostic=diagnostic_deltas)
    body = f"""
<section class="panel">
  <h2>Executive Summary</h2>
  <p><strong>Status:</strong> {status}</p>
  <p><strong>Start-to-finish runtime:</strong> {escape(duration.label)}</p>
  <p>{escape(status_text)}</p>
</section>
{_target_prompt_panel(manifest)}
{_lineage_panel(manifest)}
{_audit_panel(audit, compact=True)}
{_runtime_measurement_panel(metrics_by_track)}
<section class="panel">
  <h2>Executive Deltas</h2>
  <p>{delta_note}</p>
  <div class="delta-grid">{delta_cards}</div>
</section>
{_core_metric_scorecard_panel(metrics_by_track, audit)}
<section class="panel">
  <h2>Detailed Metric Comparison</h2>
  <table>
    <thead>
      <tr>
        <th>Metric</th>{"".join(f"<th>{escape(track)}</th>" for track in metrics_by_track)}
        <th>WorkerBee Δ</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Interpretation Boundary</h2>
  <p>
    This evidence supports comparison of process and validation behavior:
    operator touches, prompts, command volume, WorkerBee actions, token usage,
    runtime, protocol adherence, and evidence completeness. It does not, by
    itself, prove one track produced higher implementation quality because both
    tracks validated the same already-present {escape(target_label)} feature branch in this
    local baseline.
  </p>
</section>
"""
    return _page(run_root.name, "Executive", body)


def _technical_page(
    run_root: Path,
    output_dir: Path,
    manifest: dict[str, object],
    metrics_by_track: dict[str, object],
    duration,
    audit: dict[str, object],
) -> str:
    caveats = _observed_caveats(run_root)
    if manifest.get("partial_preview"):
        caveats.append(
            "Partial preview package: "
            + str(
                manifest.get("partial_preview_note")
                or (
                    "the plain-codex lane is copied reference data from "
                    f"{manifest.get('plain_reference_run', 'a prior run')}."
                )
            )
        )
    if _is_legacy_calibration(manifest):
        caveats.append(
            "Legacy calibration package: manifest predates frozen scenario snapshots "
            "and strict proof-quality comparison gates."
        )
    for track, metrics in metrics_by_track.items():
        if metrics.completeness != "complete":
            caveats.append(
                f"{track} measurement completeness is {metrics.completeness}; "
                "do not use zero prompt or zero token values as comparative results."
            )
        if metrics.prompt_metadata_missing:
            caveats.append(
                f"{track} is missing prompt metadata on "
                f"{metrics.prompt_metadata_missing} prompt(s); copied-context bytes "
                "for those prompts are unknown, not confirmed zero."
            )
    caveat_items = "".join(f"<li>{escape(item)}</li>" for item in caveats)
    if not caveat_items:
        caveat_items = '<li class="empty">No known caveats detected in command logs.</li>'
    body = f"""
<section class="panel">
  <h2>Technical Summary</h2>
  <p>
    Runtime and event metrics are derived from JSONL event timestamps. Evidence
    artifacts are linked from the run tree rather than copied into the HTML
    package. Operator touches are derived from recorded human prompts, human
    commands, AE/dashboard actions, and explicit human-action events. Codex
    token totals are cumulative per-turn usage sums; turn input metrics are
    final and maximum per-turn input-token usage snapshots. Realistic runtime is
    pre-tax measured span plus explicit manual time tax; raw checkpoint setup
    span is retained separately as a diagnostic.
  </p>
  <dl class="meta">
    <dt>Run</dt><dd><code>{escape(run_root.name)}</code></dd>
    <dt>Start-to-finish runtime</dt><dd>{escape(duration.label)}</dd>
    <dt>First measured event</dt><dd><code>{escape(duration.started_at)}</code></dd>
    <dt>Last measured event</dt><dd><code>{escape(duration.ended_at)}</code></dd>
  </dl>
</section>
{_target_prompt_panel(manifest)}
{_lineage_panel(manifest)}
{_simulation_settings_panel(manifest)}
{_audit_panel(audit)}
{_runtime_measurement_panel(metrics_by_track)}
{_core_metric_scorecard_panel(metrics_by_track, audit)}
<section class="panel">
  <h2>Track Details</h2>
  <table>
    <thead>
      <tr>
        <th>Track</th><th>Realistic Runtime</th><th>Manual Time Tax</th>
        <th>First Real Work Event</th><th>Last Measured Event</th>
        <th>Operator Touches</th><th>Human Commands</th><th>Human Actions</th>
        <th>Context Mgmt</th><th>AE Actions</th><th>WorkerBee Actions</th><th>Evidence</th>
        <th>Evidence Phases</th><th>Protocol Violations</th><th>Usage Snapshots</th>
        <th>Missing Usage</th><th>Cumulative Billed Input</th>
        <th>Final Turn Input</th><th>Max Turn Input</th><th>Cumulative Prompt Bytes</th>
        <th>Prompt Metadata</th><th>Max Prompt Bytes</th><th>Copied Context Bytes</th>
        <th>Copied Context Sources</th>
      </tr>
    </thead>
    <tbody>{_technical_rows(metrics_by_track)}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Observed Caveats</h2>
  <ul>{caveat_items}</ul>
</section>
<section class="panel">
  <h2>Runtime Policy</h2>
  {_json_block(manifest.get("runtime_policy", {}))}
  <h2>Scenario</h2>
  {_json_block(manifest.get("scenario", {}))}
  <p><a href="{_href(run_root / "report.md", output_dir)}">Open raw Markdown report</a></p>
</section>
<section class="panel">
  <h2>Implementation Quality Note</h2>
  <p>
    A quality claim requires independent implementation artifacts per track,
    a fixed rubric, and the same review and test gates applied to both outputs.
    This local baseline currently measures execution and validation process.
    Treat implementation-quality conclusions from these two local runs as
    out of scope unless a future paired run produces separate branches for
    review.
  </p>
</section>
"""
    return _page(run_root.name, "Technical", body)


def _charts_page(
    run_root: Path,
    metrics_by_track: dict[str, object],
    events_by_track: dict[str, list[SimulationEvent]],
    audit: dict[str, object],
) -> str:
    rows = []
    for track, metrics in metrics_by_track.items():
        rows.append(
            "<tr>"
            f"<th>{escape(track)}</th>"
            f"<td>{escape(metrics.duration.label)}</td>"
            f"<td>{escape(metrics.manual_time_tax_label)}</td>"
            f"<td>{metrics.operator_touches}</td>"
            f"<td>{metrics.prompts}</td>"
            f"<td>{metrics.human_commands}</td>"
            f"<td>{metrics.human_actions}</td>"
            f"<td>{metrics.context_management_actions}</td>"
            f"<td>{metrics.ae_actions}</td>"
            f"<td>{metrics.workerbee_actions}</td>"
            f"<td>{metrics.automation_actions}</td>"
            f"<td>{metrics.input_tokens}</td>"
            f"<td>{metrics.cached_input_tokens}</td>"
            f"<td>{metrics.output_tokens}</td>"
            f"<td>{metrics.reasoning_output_tokens}</td>"
            f"<td>{metrics.codex_turns_started}</td>"
            f"<td>{metrics.usage_snapshots}</td>"
            f"<td>{metrics.codex_turns_missing_usage}</td>"
            f"<td>{metrics.final_turn_input_tokens}</td>"
            f"<td>{metrics.max_turn_input_tokens}</td>"
            f"<td>{metrics.prompt_bytes}</td>"
            f"<td>{_prompt_metadata_coverage(metrics)}</td>"
            f"<td>{metrics.max_prompt_bytes}</td>"
            f"<td>{metrics.copied_context_bytes}</td>"
            f"<td>{metrics.copied_context_sources}</td>"
            "</tr>"
        )
    charts = _chart_payload(events_by_track)
    diagnostic_deltas = _audit_blocks_deltas(audit)
    delta_cards = _delta_cards(metrics_by_track, diagnostic=diagnostic_deltas)
    operator_tone = _metric_delta_tone(
        metrics_by_track, lambda metrics: metrics.operator_touches, prefer="lower"
    )
    action_tone = _metric_delta_tone(
        metrics_by_track,
        lambda metrics: metrics.commands + metrics.workerbee_actions,
        prefer="neutral",
    )
    token_tone = _metric_delta_tone(metrics_by_track, lambda metrics: metrics.input_tokens, "lower")
    turn_tone = _metric_delta_tone(
        metrics_by_track, lambda metrics: metrics.max_turn_input_tokens, "lower"
    )
    body = f"""
<section class="panel">
  <h2>Measurement Charts</h2>
  <p>
    Operator touches are a count of recorded human interventions: human prompts,
    human shell commands, AE/dashboard actions, and explicit human-action events.
    WorkerBee tool calls are delegated automation and are graphed separately.
    Cumulative billed token usage is the sum of Codex
    <code>turn.completed</code> usage records over the run. Per-turn input
    usage is charted from each usage snapshot; it can be used as a
    context-pressure proxy only in controlled no-tool probes.
  </p>
  <p>
    Chart timelines are anchored to the first measured non-checkpoint event.
    Checkpoint setup idle is reported in Measurement Integrity rather than
    stretched across the x-axis.
  </p>
  <table>
    <thead>
      <tr>
        <th>Track</th><th>Realistic Runtime</th>
        <th>Manual Time Tax</th><th>Operator Touches</th><th>Prompts</th>
        <th>Human Commands</th><th>Human Actions</th><th>Context Mgmt</th><th>AE Actions</th>
        <th>WorkerBee Actions</th><th>Automation Actions</th>
        <th>Cumulative Billed Input</th><th>Cumulative Cached Input</th>
        <th>Cumulative Output</th><th>Cumulative Reasoning</th>
        <th>Codex Turns</th><th>Usage Snapshots</th><th>Missing Usage</th>
        <th>Final Turn Input</th><th>Max Turn Input</th><th>Cumulative Prompt Bytes</th>
        <th>Prompt Metadata</th><th>Max Prompt Bytes</th><th>Copied Context Bytes</th>
        <th>Copied Context Sources</th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Metric Deltas</h2>
  <p>{_delta_note(diagnostic=diagnostic_deltas)}</p>
  <div class="delta-grid">{delta_cards}</div>
</section>
<div class="chart-grid-layout">
  {_chart_canvas("operatorTouches", "Cumulative Operator Touches", operator_tone)}
  {_chart_canvas("commandActions", "Cumulative Command and Tool Actions", action_tone)}
  {_chart_canvas("tokenUsage", "Cumulative Billed Token Usage", token_tone)}
  {_chart_canvas("turnInput", "Per-Turn Codex Input Tokens", turn_tone)}
  {_chart_canvas("promptContext", "Cumulative Prompt and Copied Context Bytes", token_tone)}
</div>
<script src="assets/chart.umd.min.js"></script>
<script>
  window.SIMULACRA_CHARTS = {_script_json(charts)};
  {_chart_script()}
</script>
"""
    return _page(run_root.name, "Charts", body)


def _timeline_page(
    run_root: Path,
    output_dir: Path,
    events_by_track: dict[str, list[SimulationEvent]],
) -> str:
    events = sorted(
        (event for events in events_by_track.values() for event in events),
        key=lambda event: event.timestamp,
    )
    rows = []
    for event in events:
        rows.append(
            "<tr>"
            f"<td><code>{escape(event.timestamp)}</code></td>"
            f"<td>{escape(event.track)}</td>"
            f"<td>{escape(event.event_type)}</td>"
            f"<td>{escape(event.source)}</td>"
            f"<td>{escape(event.summary)}</td>"
            f"<td>{_payload_preview(event, output_dir)}</td>"
            "</tr>"
        )
    body = f"""
<section class="panel">
  <h2>Event Timeline</h2>
  <table>
    <thead>
      <tr>
        <th>Timestamp</th><th>Track</th><th>Type</th><th>Source</th>
        <th>Summary</th><th>Payload</th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</section>
"""
    return _page(run_root.name, "Timeline", body)


def _artifacts_page(
    run_root: Path,
    output_dir: Path,
    events_by_track: dict[str, list[SimulationEvent]],
) -> str:
    sections = []
    for track, events in events_by_track.items():
        artifacts = _collect_artifacts(run_root, track, events)
        cards = [_artifact_card(artifact, output_dir) for artifact in artifacts]
        if not cards:
            cards = ['<p class="empty">No artifacts found.</p>']
        sections.append(
            f"""
<section class="panel">
  <h2>{escape(track)}</h2>
  <div class="gallery">{"".join(cards)}</div>
</section>
"""
        )
    run_artifacts = [
        artifact
        for artifact in (
            run_root / "manifest.json",
            run_root / "report.md",
            run_root / "audit.md",
            run_root / "audit.json",
            run_root / "audit-adjustments.md",
        )
        if artifact.exists()
    ]
    run_cards = [_artifact_card(artifact, output_dir) for artifact in run_artifacts]
    run_section = f"""
<section class="panel">
  <h2>Run</h2>
  <div class="gallery">{"".join(run_cards)}</div>
</section>
"""
    return _page(run_root.name, "Artifacts", run_section + "".join(sections))


def _chart_payload(events_by_track: dict[str, list[SimulationEvent]]) -> dict[str, object]:
    started, ended = _event_bounds(events_by_track)
    operator_series = [
        ChartSeries(
            label="plain operator touches",
            track="plain-codex",
            stroke="#2563eb",
            predicate=is_operator_touch,
        ),
        ChartSeries(
            label="workerbee operator touches",
            track="workerbee-codex",
            stroke="#16a34a",
            predicate=is_operator_touch,
        ),
    ]
    action_series = [
        ChartSeries(
            label="plain shell/AE commands",
            track="plain-codex",
            stroke="#2f59b9",
            predicate=lambda event: event.event_type in {"command", "ae_command"},
        ),
        ChartSeries(
            label="workerbee shell/AE commands",
            track="workerbee-codex",
            stroke="#0284c7",
            predicate=lambda event: event.event_type in {"command", "ae_command"},
        ),
        ChartSeries(
            label="workerbee tool actions",
            track="workerbee-codex",
            stroke="#f59e0b",
            predicate=lambda event: event.event_type == "workerbee_tool",
        ),
    ]
    return {
        "operatorTouches": {
            "title": "Cumulative Operator Touches",
            "unit": "touches",
            "stepped": True,
            "datasets": _event_count_datasets(events_by_track, operator_series, started, ended),
        },
        "commandActions": {
            "title": "Cumulative Command and Tool Actions",
            "unit": "actions",
            "stepped": True,
            "datasets": _event_count_datasets(events_by_track, action_series, started, ended),
        },
        "tokenUsage": {
            "title": "Cumulative Billed Token Usage",
            "unit": "tokens",
            "stepped": True,
            "datasets": _token_usage_datasets(events_by_track, started, ended),
        },
        "turnInput": {
            "title": "Per-Turn Codex Input Tokens",
            "unit": "input tokens",
            "stepped": False,
            "datasets": _turn_input_datasets(events_by_track),
        },
        "promptContext": {
            "title": "Cumulative Prompt and Copied Context Bytes",
            "unit": "bytes",
            "stepped": True,
            "datasets": _prompt_context_datasets(events_by_track, started, ended),
        },
    }


def _event_bounds(
    events_by_track: dict[str, list[SimulationEvent]],
) -> tuple[datetime | None, datetime | None]:
    timestamps = [
        parsed
        for events in events_by_track.values()
        for event in events
        if event.event_type != "checkpoint"
        if (parsed := _parse_timestamp(event.timestamp)) is not None
    ]
    if not timestamps:
        return None, None
    return min(timestamps), max(timestamps)


def _event_count_datasets(
    events_by_track: dict[str, list[SimulationEvent]],
    series: list[ChartSeries],
    started: datetime | None,
    ended: datetime | None,
) -> list[dict[str, object]]:
    datasets = []
    for item in series:
        points = []
        if started is not None:
            points.append({"x": 0, "y": 0})
        count = 0
        for timestamp, _event in _matching_events(events_by_track, item):
            count += 1
            points.append({"x": _minutes_from(started, timestamp), "y": count})
        if ended is not None:
            points.append({"x": _minutes_from(started, ended), "y": count})
        datasets.append(_dataset(item.label, item.stroke, points))
    return datasets


def _token_usage_datasets(
    events_by_track: dict[str, list[SimulationEvent]],
    started: datetime | None,
    ended: datetime | None,
) -> list[dict[str, object]]:
    specs = [
        ("input_tokens", "billed input"),
        ("cached_input_tokens", "cached input"),
        ("output_tokens", "output"),
        ("reasoning_output_tokens", "reasoning output"),
    ]
    datasets = []
    for track in TRACKS:
        usage_events = _usage_events(events_by_track.get(track, []))
        for key, label in specs:
            total = 0
            points = []
            if started is not None:
                points.append({"x": 0, "y": 0})
            for timestamp, usage in usage_events:
                total += int(usage.get(key) or 0)
                points.append({"x": _minutes_from(started, timestamp), "y": total})
            if ended is not None:
                points.append({"x": _minutes_from(started, ended), "y": total})
            datasets.append(
                _dataset(
                    f"{track} {label}",
                    _usage_color(track, key),
                    points,
                    hidden=key != "input_tokens",
                )
            )
    return datasets


def _turn_input_datasets(
    events_by_track: dict[str, list[SimulationEvent]],
) -> list[dict[str, object]]:
    specs = [
        ("input_tokens", "turn input tokens"),
        ("cached_input_tokens", "cached turn input tokens"),
    ]
    datasets = []
    started, _ended = _event_bounds(events_by_track)
    for track in TRACKS:
        usage_events = _usage_events(events_by_track.get(track, []))
        for key, label in specs:
            points = [
                {"x": _minutes_from(started, timestamp), "y": int(usage.get(key) or 0)}
                for timestamp, usage in usage_events
            ]
            datasets.append(
                _dataset(
                    f"{track} {label}",
                    _usage_color(track, key),
                    points,
                    hidden=key != "input_tokens",
                )
            )
    return datasets


def _prompt_context_datasets(
    events_by_track: dict[str, list[SimulationEvent]],
    started: datetime | None,
    ended: datetime | None,
) -> list[dict[str, object]]:
    datasets = []
    for track in TRACKS:
        prompt_total = 0
        copied_total = 0
        prompt_points = []
        copied_points = []
        if started is not None:
            prompt_points.append({"x": 0, "y": 0})
            copied_points.append({"x": 0, "y": 0})
        prompt_events = [
            event
            for event in events_by_track.get(track, [])
            if event.event_type == "human_prompt" and _parse_timestamp(event.timestamp) is not None
        ]
        for event in sorted(prompt_events, key=lambda item: item.timestamp):
            timestamp = _parse_timestamp(event.timestamp)
            if timestamp is None:
                continue
            text = str(event.payload.get("prompt") or "")
            prompt_total += int(event.payload.get("prompt_byte_count") or len(text.encode("utf-8")))
            metadata = event.payload.get("prompt_metadata")
            if isinstance(metadata, dict):
                copied_total += int(metadata.get("total_embedded_bytes") or 0)
            prompt_points.append({"x": _minutes_from(started, timestamp), "y": prompt_total})
            copied_points.append({"x": _minutes_from(started, timestamp), "y": copied_total})
        if ended is not None:
            prompt_points.append({"x": _minutes_from(started, ended), "y": prompt_total})
            copied_points.append({"x": _minutes_from(started, ended), "y": copied_total})
        datasets.append(
            _dataset(f"{track} prompt bytes", _prompt_color(track, "prompt"), prompt_points)
        )
        datasets.append(
            _dataset(
                f"{track} copied context bytes",
                _prompt_color(track, "copied"),
                copied_points,
            )
        )
    return datasets


def _prompt_color(track: str, key: str) -> str:
    palette = {
        ("plain-codex", "prompt"): "#2563eb",
        ("plain-codex", "copied"): "#0284c7",
        ("workerbee-codex", "prompt"): "#16a34a",
        ("workerbee-codex", "copied"): "#f59e0b",
    }
    return palette.get((track, key), "#4a5565")


def _usage_color(track: str, key: str) -> str:
    palette = {
        ("plain-codex", "input_tokens"): "#2563eb",
        ("workerbee-codex", "input_tokens"): "#16a34a",
        ("plain-codex", "cached_input_tokens"): "#0284c7",
        ("workerbee-codex", "cached_input_tokens"): "#60a5fa",
        ("plain-codex", "output_tokens"): "#f59e0b",
        ("workerbee-codex", "output_tokens"): "#ef4444",
        ("plain-codex", "reasoning_output_tokens"): "#7c3aed",
        ("workerbee-codex", "reasoning_output_tokens"): "#db2777",
    }
    return palette.get((track, key), "#4a5565")


def _usage_events(events: list[SimulationEvent]) -> list[tuple[datetime, dict[str, object]]]:
    usage_events = []
    for event in events:
        timestamp = _parse_timestamp(event.timestamp)
        usage = event.payload.get("usage")
        if timestamp is not None and isinstance(usage, dict):
            usage_events.append((timestamp, usage))
    return sorted(usage_events, key=lambda item: item[0])


def _dataset(
    label: str,
    color: str,
    points: list[dict[str, float | int]],
    *,
    hidden: bool = False,
) -> dict[str, object]:
    return {
        "label": label,
        "borderColor": color,
        "backgroundColor": _hex_to_rgba(color, 0.12),
        "pointBackgroundColor": color,
        "pointBorderColor": "#ffffff",
        "pointBorderWidth": 2,
        "pointRadius": 4,
        "pointHoverRadius": 6,
        "borderWidth": 3,
        "tension": 0.32,
        "fill": False,
        "hidden": hidden,
        "data": points,
    }


def _hex_to_rgba(value: str, alpha: float) -> str:
    value = value.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _minutes_from(started: datetime | None, timestamp: datetime) -> float:
    if started is None:
        return 0
    return round(max(0.0, (timestamp - started).total_seconds() / 60), 3)


def _chart_canvas(chart_id: str, title: str, tone: str = "neutral") -> str:
    escaped_id = escape(chart_id)
    tone_class = _tone_class(tone)
    return f"""
<section class="panel chart-panel {tone_class}">
  <h2>{escape(title)}</h2>
  <div class="chart-shell"><canvas id="{escaped_id}"></canvas></div>
</section>
"""


def _chart_script() -> str:
    return """
(function () {
  var charts = window.SIMULACRA_CHARTS || {};
  if (!window.Chart) {
    document.querySelectorAll('.chart-shell').forEach(function (shell) {
      shell.innerHTML = '<p class="empty">Chart.js asset was not found in this package.</p>';
    });
    return;
  }
  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", "Roboto", sans-serif';
  var instances = [];

  function cssVar(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function chartTheme() {
    return {
      text: cssVar('--k1s-text-muted', '#4a5565'),
      title: cssVar('--k1s-text', '#0f141c'),
      panel: cssVar('--k1s-panel', '#ffffff'),
      border: cssVar('--k1s-border', '#d4d7dd'),
      borderSoft: cssVar('--k1s-border-soft', '#e6e8ec')
    };
  }

  function applyTheme(chart) {
    var theme = chartTheme();
    Chart.defaults.color = theme.text;
    chart.options.plugins.legend.labels.color = theme.text;
    chart.options.plugins.tooltip.backgroundColor = theme.panel;
    chart.options.plugins.tooltip.titleColor = theme.title;
    chart.options.plugins.tooltip.bodyColor = theme.title;
    chart.options.plugins.tooltip.borderColor = theme.border;
    chart.options.scales.x.title.color = theme.text;
    chart.options.scales.x.ticks.color = theme.text;
    chart.options.scales.x.grid.color = theme.borderSoft;
    chart.options.scales.x.border.color = theme.border;
    chart.options.scales.y.title.color = theme.text;
    chart.options.scales.y.ticks.color = theme.text;
    chart.options.scales.y.grid.color = theme.borderSoft;
    chart.options.scales.y.border.color = theme.border;
  }

  Object.keys(charts).forEach(function (id) {
    var canvas = document.getElementById(id);
    if (!canvas) return;
    var cfg = charts[id];
    var chart = new Chart(canvas, {
      type: 'line',
      data: { datasets: cfg.datasets || [] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        parsing: false,
        normalized: true,
        interaction: { mode: 'nearest', intersect: false },
        elements: { line: { stepped: cfg.stepped ? 'after' : false } },
        plugins: {
          legend: {
            position: 'bottom',
            labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8, color: '#4a5565' }
          },
          tooltip: {
            backgroundColor: '#ffffff',
            titleColor: '#0f141c',
            bodyColor: '#0f141c',
            borderColor: '#d4d7dd',
            borderWidth: 1,
            displayColors: true,
            callbacks: {
              title: function (items) {
                if (!items.length) return '';
                return items[0].parsed.x.toFixed(2) + ' min from first measured event';
              },
              label: function (item) {
                return item.dataset.label + ': ' + item.parsed.y.toLocaleString() + ' ' + cfg.unit;
              }
            }
          }
        },
        scales: {
          x: {
            type: 'linear',
            title: { display: true, text: 'Minutes from first measured event', color: '#4a5565' },
            grid: { color: '#e6e8ec' },
            border: { color: '#d4d7dd' },
            ticks: { color: '#4a5565', callback: function (value) { return value + 'm'; } }
          },
          y: {
            beginAtZero: true,
            title: { display: true, text: cfg.unit || 'count', color: '#4a5565' },
            grid: { color: '#e6e8ec' },
            border: { color: '#d4d7dd' },
            ticks: { color: '#4a5565', precision: 0 }
          }
        }
      }
    });
    applyTheme(chart);
    instances.push(chart);
  });
  window.addEventListener('simulacra:themechange', function () {
    instances.forEach(function (chart) {
      applyTheme(chart);
      chart.update('none');
    });
  });
})();
"""


def _cumulative_chart(
    events_by_track: dict[str, list[SimulationEvent]],
    title: str,
    series: list[ChartSeries],
) -> str:
    timed_events = [
        (parsed, event)
        for events in events_by_track.values()
        for event in events
        if (parsed := _parse_timestamp(event.timestamp)) is not None
    ]
    if not timed_events:
        return f'<h2>{escape(title)}</h2><p class="empty">No timestamped events found.</p>'
    started = min(timestamp for timestamp, _event in timed_events)
    ended = max(timestamp for timestamp, _event in timed_events)
    span_seconds = max(1.0, (ended - started).total_seconds())
    width = 920
    height = 300
    left = 64
    right = 24
    top = 36
    bottom = 44
    plot_width = width - left - right
    plot_height = height - top - bottom
    series_events = [_matching_events(events_by_track, item) for item in series]
    max_count = max([len(items) for items in series_events] + [1])

    def x_for(timestamp: datetime) -> float:
        offset = (timestamp - started).total_seconds()
        return left + (offset / span_seconds) * plot_width

    def y_for(count: int) -> float:
        return top + plot_height - (count / max_count) * plot_height

    grid = []
    for index in range(5):
        count = round((max_count / 4) * index)
        y = y_for(count)
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" '
            'class="chart-grid"></line>'
        )
        grid.append(f'<text x="12" y="{y + 4:.1f}" class="chart-axis">{count}</text>')
    grid.append(
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" '
        'class="chart-axis-line"></line>'
    )
    grid.append(
        f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" '
        f'y2="{height - bottom}" class="chart-axis-line"></line>'
    )

    lines = []
    legend = []
    for item, events in zip(series, series_events, strict=True):
        points = [(x_for(started), y_for(0))]
        count = 0
        for timestamp, _event in events:
            x = x_for(timestamp)
            points.append((x, y_for(count)))
            count += 1
            points.append((x, y_for(count)))
        points.append((x_for(ended), y_for(count)))
        point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        lines.append(
            f'<polyline points="{point_text}" fill="none" stroke="{item.stroke}" '
            'stroke-width="3" stroke-linejoin="round" stroke-linecap="round"></polyline>'
        )
        legend.append(
            '<span class="legend-item">'
            f'<span class="legend-swatch" style="background:{item.stroke}"></span>'
            f"{escape(item.label)} ({count})"
            "</span>"
        )

    start_label = _short_time(started)
    end_label = _short_time(ended)
    svg = f"""
<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
  <title>{escape(title)}</title>
  <text x="{left}" y="22" class="chart-title">{escape(title)}</text>
  {"".join(grid)}
  {"".join(lines)}
  <text x="{left}" y="{height - 14}" class="chart-axis">{escape(start_label)}</text>
  <text x="{width - right}" y="{height - 14}" class="chart-axis chart-axis-end">
    {escape(end_label)}
  </text>
</svg>
"""
    return f'<h2>{escape(title)}</h2>{svg}<div class="legend">{"".join(legend)}</div>'


def _matching_events(
    events_by_track: dict[str, list[SimulationEvent]], series: ChartSeries
) -> list[tuple[datetime, SimulationEvent]]:
    events = []
    for event in events_by_track.get(series.track, []):
        timestamp = _parse_timestamp(event.timestamp)
        if timestamp is not None and series.predicate(event):
            events.append((timestamp, event))
    return sorted(events, key=lambda item: item[0])


def _collect_artifacts(run_root: Path, track: str, events: Iterable[SimulationEvent]) -> list[Path]:
    seen: set[Path] = set()
    artifacts: list[Path] = []
    track_root = run_root / track
    for child in ("events.jsonl", "codex", "commands", "evidence", "prompts", "reports"):
        artifact_root = track_root / child
        if artifact_root.is_file() and _is_reviewable(artifact_root):
            _append_artifact(artifacts, seen, artifact_root)
            continue
        if artifact_root.exists():
            for path in sorted(artifact_root.rglob("*")):
                if path.is_file() and _is_reviewable(path):
                    _append_artifact(artifacts, seen, path)
    for event in events:
        if event.event_type != "evidence":
            continue
        for value in _payload_paths(event.payload):
            path = Path(value)
            if not path.is_absolute():
                path = track_root / value
            if path.exists() and _is_reviewable(path):
                _append_artifact(artifacts, seen, path)
    return artifacts


def _payload_paths(payload: dict[str, object]) -> Iterable[str]:
    artifacts = payload.get("artifacts", [])
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, str):
                yield artifact
    summary_path = payload.get("summary_path")
    if isinstance(summary_path, str):
        yield summary_path


def _append_artifact(artifacts: list[Path], seen: set[Path], path: Path) -> None:
    resolved = path.resolve()
    if resolved in seen:
        return
    seen.add(resolved)
    artifacts.append(path)


def _artifact_card(path: Path, output_dir: Path) -> str:
    suffix = path.suffix.lower()
    href = _href(path, output_dir)
    title = escape(path.name)
    if suffix in IMAGE_SUFFIXES:
        preview = f'<a href="{href}"><img src="{href}" alt="{title}"></a>'
    elif suffix in VIDEO_SUFFIXES:
        preview = f'<video controls preload="metadata" src="{href}"></video>'
    elif suffix in TEXT_SUFFIXES:
        preview = f"<details><summary>Preview</summary>{_text_preview(path)}</details>"
    else:
        preview = '<p class="empty">Preview unavailable.</p>'
    return f"""
<article class="artifact">
  <h3>{title}</h3>
  <p><a href="{href}">Open artifact</a></p>
  {preview}
</article>
"""


def _payload_preview(event: SimulationEvent, output_dir: Path) -> str:
    links = []
    for value in _payload_paths(event.payload):
        path = Path(value)
        if path.exists():
            links.append(f'<a href="{_href(path, output_dir)}">{escape(path.name)}</a>')
    command = event.payload.get("command")
    if isinstance(command, str):
        links.append(f"<code>{escape(command[:240])}</code>")
    prompt = event.payload.get("prompt")
    if isinstance(prompt, str):
        links.append(f"<code>{escape(prompt[:240])}</code>")
    return "<br>".join(links) if links else _json_block(event.payload, compact=True)


def _core_metric_scorecard_panel(
    metrics_by_track: dict[str, object],
    audit: dict[str, object],
) -> str:
    rows = []
    plain, workerbee = _plain_workerbee(metrics_by_track)
    audit_missing = not audit
    audit_blocked = _audit_blocks_deltas(audit)
    for spec in CORE_METRIC_SPECS:
        if plain is None or workerbee is None:
            plain_value = workerbee_value = None
        else:
            plain_value = spec.value_fn(plain)
            workerbee_value = spec.value_fn(workerbee)
        if plain_value is None or workerbee_value is None:
            state = "n/a"
            tone = "neutral"
        elif audit_missing:
            state = "Review pending"
            tone = "neutral"
        elif audit_blocked:
            state = "Blocked"
            tone = "neutral"
        elif float(workerbee_value) < float(plain_value):
            state = "WorkerBee advantage"
            tone = "good"
        elif float(workerbee_value) == float(plain_value):
            state = "Neutral"
            tone = "neutral"
        else:
            state = "Plain anomaly"
            tone = "bad"
        rows.append(
            "<tr>"
            f"<th>{escape(spec.label.title())}</th>"
            f"<td>{_score_value(plain_value, spec.unit)}</td>"
            f"<td>{_score_value(workerbee_value, spec.unit)}</td>"
            f'<td><span class="delta-badge {_tone_class(tone)}">{escape(state)}</span></td>'
            "</tr>"
        )
    return f"""
<section class="panel">
  <h2>Core Metric Scorecard</h2>
  <p>
    Core metrics are expected to favor WorkerBee in strict realistic runs.
    Plain-Codex wins are treated as review-required anomalies unless explicitly waived.
  </p>
  <table>
    <thead>
      <tr>
        <th>Metric</th><th>plain-codex</th><th>workerbee-codex</th><th>Status</th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</section>
"""


def _score_value(value: float | int | None, unit: str) -> str:
    if value is None:
        return '<span class="empty">n/a</span>'
    return escape(_format_quantity(value, unit))


def _comparison_rows(metrics_by_track: dict[str, object], *, diagnostic: bool = False) -> str:
    rows = []
    for spec in _comparison_specs():
        rows.append(
            f"<tr><th>{escape(spec.label)}</th>"
            + "".join(
                f"<td>{escape(spec.value_fn(metrics))}</td>"
                for metrics in metrics_by_track.values()
            )
            + _delta_cell(metrics_by_track, spec, diagnostic=diagnostic)
            + "</tr>"
        )
    return "".join(rows)


def _comparison_specs() -> list[ComparisonSpec]:
    return [
        ComparisonSpec("Completeness", lambda metrics: metrics.completeness),
        ComparisonSpec(
            "Realistic runtime",
            lambda metrics: metrics.duration.label,
            lambda metrics: metrics.duration.seconds,
            prefer="lower",
            unit="duration",
        ),
        ComparisonSpec(
            "Manual time tax",
            lambda metrics: metrics.manual_time_tax_label,
            lambda metrics: metrics.manual_time_tax_seconds,
            prefer="lower",
            unit="duration",
        ),
        ComparisonSpec(
            "Operator touches",
            lambda metrics: str(metrics.operator_touches),
            lambda metrics: metrics.operator_touches,
            prefer="lower",
        ),
        ComparisonSpec(
            "Human prompts",
            lambda metrics: str(metrics.prompts),
            lambda metrics: metrics.prompts,
            prefer="lower",
        ),
        ComparisonSpec("Prompt metadata coverage", _prompt_metadata_coverage),
        ComparisonSpec(
            "Prompt metadata missing",
            lambda metrics: str(metrics.prompt_metadata_missing),
            lambda metrics: metrics.prompt_metadata_missing,
            prefer="lower",
        ),
        ComparisonSpec(
            "Human commands",
            lambda metrics: str(metrics.human_commands),
            lambda metrics: metrics.human_commands,
            prefer="lower",
        ),
        ComparisonSpec(
            "Human actions",
            lambda metrics: str(metrics.human_actions),
            lambda metrics: metrics.human_actions,
            prefer="lower",
        ),
        ComparisonSpec(
            "Context-management actions",
            lambda metrics: str(metrics.context_management_actions),
            lambda metrics: metrics.context_management_actions,
            prefer="lower",
        ),
        ComparisonSpec(
            "AE actions",
            lambda metrics: str(metrics.ae_actions),
            lambda metrics: metrics.ae_actions,
            prefer="lower",
        ),
        ComparisonSpec(
            "Shell/AE commands",
            lambda metrics: str(metrics.commands),
            lambda metrics: metrics.commands,
            prefer="lower",
        ),
        ComparisonSpec(
            "WorkerBee actions",
            lambda metrics: str(metrics.workerbee_actions),
            lambda metrics: metrics.workerbee_actions,
            prefer="neutral",
        ),
        ComparisonSpec(
            "Automation actions",
            lambda metrics: str(metrics.automation_actions),
            lambda metrics: metrics.automation_actions,
            prefer="neutral",
        ),
        ComparisonSpec(
            "Evidence artifacts",
            lambda metrics: str(metrics.evidence),
            lambda metrics: metrics.evidence,
            prefer="same",
        ),
        ComparisonSpec(
            "Evidence phases",
            lambda metrics: ", ".join(metrics.evidence_phases) or "none",
        ),
        ComparisonSpec(
            "Protocol violations",
            lambda metrics: str(metrics.violations),
            lambda metrics: metrics.violations,
            prefer="lower",
        ),
        ComparisonSpec(
            "Codex turns started",
            lambda metrics: str(metrics.codex_turns_started),
            lambda metrics: metrics.codex_turns_started,
            prefer="neutral",
        ),
        ComparisonSpec(
            "Codex usage snapshots",
            lambda metrics: str(metrics.usage_snapshots),
            lambda metrics: metrics.usage_snapshots,
            prefer="neutral",
        ),
        ComparisonSpec(
            "Codex turns missing usage",
            lambda metrics: str(metrics.codex_turns_missing_usage),
            lambda metrics: metrics.codex_turns_missing_usage,
            prefer="lower",
        ),
        ComparisonSpec(
            "Cumulative billed input tokens",
            lambda metrics: str(metrics.input_tokens),
            lambda metrics: metrics.input_tokens,
            prefer="lower",
            unit="tokens",
        ),
        ComparisonSpec(
            "Cumulative output tokens",
            lambda metrics: str(metrics.output_tokens),
            lambda metrics: metrics.output_tokens,
            prefer="lower",
            unit="tokens",
        ),
        ComparisonSpec(
            "Final Codex turn input tokens",
            lambda metrics: str(metrics.final_turn_input_tokens),
            lambda metrics: metrics.final_turn_input_tokens,
            prefer="lower",
            unit="tokens",
        ),
        ComparisonSpec(
            "Max Codex turn input tokens",
            lambda metrics: str(metrics.max_turn_input_tokens),
            lambda metrics: metrics.max_turn_input_tokens,
            prefer="lower",
            unit="tokens",
        ),
        ComparisonSpec(
            "Cumulative prompt bytes",
            lambda metrics: str(metrics.prompt_bytes),
            lambda metrics: metrics.prompt_bytes,
            prefer="lower",
            unit="bytes",
        ),
        ComparisonSpec(
            "Max prompt bytes",
            lambda metrics: str(metrics.max_prompt_bytes),
            lambda metrics: metrics.max_prompt_bytes,
            prefer="lower",
            unit="bytes",
        ),
        ComparisonSpec(
            "Copied context bytes",
            lambda metrics: str(metrics.copied_context_bytes),
            lambda metrics: metrics.copied_context_bytes,
            prefer="lower",
            unit="bytes",
        ),
        ComparisonSpec(
            "Copied context sources",
            lambda metrics: str(metrics.copied_context_sources),
            lambda metrics: metrics.copied_context_sources,
            prefer="lower",
        ),
    ]


def _delta_cards(metrics_by_track: dict[str, object], *, diagnostic: bool = False) -> str:
    if diagnostic:
        return (
            '<article class="delta-card delta-bad delta-suppressed">'
            '<span class="delta-label">Audit blocked</span>'
            '<strong class="delta-value">diagnostic only</strong>'
            "<small>Percentage deltas are suppressed until the audit accepts this run.</small>"
            "</article>"
        )
    specs = [
        spec
        for spec in _comparison_specs()
        if spec.label
        in {
            "Runtime",
            "Realistic runtime",
            "Manual time tax",
            "Operator touches",
            "Human prompts",
            "Human commands",
            "Shell/AE commands",
            "Cumulative billed input tokens",
            "Final Codex turn input tokens",
            "Cumulative prompt bytes",
            "Copied context bytes",
            "Cumulative output tokens",
        }
    ]
    cards = []
    for spec in specs:
        plain, workerbee = _plain_workerbee(metrics_by_track)
        if plain is None or workerbee is None or spec.number_fn is None:
            continue
        base = spec.number_fn(plain)
        value = spec.number_fn(workerbee)
        if base is None or value is None:
            continue
        delta = float(value) - float(base)
        tone = _delta_tone(delta, spec.prefer)
        cards.append(
            '<article class="delta-card '
            f'{_tone_class(tone)}">'
            f'<span class="delta-label">{escape(spec.label)}</span>'
            f'<strong class="delta-value">{_delta_badge(base, value, spec)}</strong>'
            f"<small>{escape(_delta_detail(base, value, spec))}</small>"
            "</article>"
        )
    return "".join(cards) or '<p class="empty">No comparable numeric metrics found.</p>'


def _delta_cell(
    metrics_by_track: dict[str, object],
    spec: ComparisonSpec,
    *,
    diagnostic: bool = False,
) -> str:
    if diagnostic and spec.number_fn is not None:
        return '<td><span class="delta-badge delta-neutral">blocked</span></td>'
    plain, workerbee = _plain_workerbee(metrics_by_track)
    if plain is None or workerbee is None or spec.number_fn is None:
        return '<td><span class="delta-badge delta-neutral">n/a</span></td>'
    base = spec.number_fn(plain)
    value = spec.number_fn(workerbee)
    if base is None or value is None:
        return '<td><span class="delta-badge delta-neutral">n/a</span></td>'
    delta = float(value) - float(base)
    tone = _delta_tone(delta, spec.prefer)
    return (
        f'<td><span class="delta-badge {_tone_class(tone)}">'
        f"{_delta_badge(base, value, spec)}</span></td>"
    )


def _plain_workerbee(metrics_by_track: dict[str, object]) -> tuple[object | None, object | None]:
    return metrics_by_track.get("plain-codex"), metrics_by_track.get("workerbee-codex")


def _prompt_metadata_coverage(metrics: object) -> str:
    return f"{metrics.prompt_metadata_count}/{metrics.prompts}"


def _audit_blocks_deltas(audit: dict[str, object]) -> bool:
    return bool(audit) and not bool(audit.get("accepted"))


def _delta_badge(base: float | int, value: float | int, spec: ComparisonSpec) -> str:
    if float(base) == 0:
        if float(value) == 0:
            return "0%"
        return f"new +{_format_quantity(value, spec.unit)}"
    percent = ((float(value) - float(base)) / abs(float(base))) * 100.0
    return f"{percent:+.1f}%"


def _delta_detail(base: float | int, value: float | int, spec: ComparisonSpec) -> str:
    delta = float(value) - float(base)
    base_label = _format_quantity(base, spec.unit)
    value_label = _format_quantity(value, spec.unit)
    if spec.label == "Manual time tax":
        if delta < 0:
            saved = _format_quantity(abs(delta), spec.unit)
            return (
                f"WorkerBee avoided {saved} of manual time tax "
                f"(plain {base_label}, WorkerBee {value_label})"
            )
        if delta > 0:
            added = _format_quantity(delta, spec.unit)
            return (
                f"WorkerBee added {added} of manual time tax "
                f"(plain {base_label}, WorkerBee {value_label})"
            )
        return f"Both tracks recorded the same manual time tax ({base_label})"
    if spec.unit == "duration" and spec.prefer == "lower":
        if delta < 0:
            saved = _format_quantity(abs(delta), spec.unit)
            return (
                f"WorkerBee finished {saved} faster "
                f"(plain {base_label}, WorkerBee {value_label})"
            )
        if delta > 0:
            slower = _format_quantity(delta, spec.unit)
            return (
                f"WorkerBee finished {slower} slower "
                f"(plain {base_label}, WorkerBee {value_label})"
            )
        return f"Both tracks finished in {base_label}"
    if spec.prefer == "lower":
        metric_label = spec.label[:1].lower() + spec.label[1:]
        if delta < 0:
            reduction = _format_quantity(abs(delta), spec.unit)
            return (
                f"WorkerBee reduced {metric_label} by {reduction} "
                f"(plain {base_label}, WorkerBee {value_label})"
            )
        if delta > 0:
            increase = _format_quantity(delta, spec.unit)
            return (
                f"WorkerBee increased {metric_label} by {increase} "
                f"(plain {base_label}, WorkerBee {value_label})"
            )
        return f"Both tracks recorded the same {metric_label} ({base_label})"
    return (
        f"WorkerBee changed by {_format_signed_quantity(delta, spec.unit)} "
        f"(plain {base_label}, WorkerBee {value_label})"
    )


def _format_quantity(value: float | int, unit: str) -> str:
    rounded = int(round(float(value)))
    if unit == "duration":
        return format_duration(float(value))
    if unit == "tokens":
        return f"{rounded:,} tokens"
    if unit == "bytes":
        return f"{rounded:,} bytes"
    return f"{rounded:,}"


def _format_signed_quantity(value: float | int, unit: str) -> str:
    if unit == "duration":
        if value == 0:
            return "0s"
        sign = "+" if value > 0 else "-"
        return f"{sign}{format_duration(abs(float(value)))}"
    sign = "+" if value > 0 else ""
    rounded = int(round(float(value)))
    suffix = " tokens" if unit == "tokens" else ""
    if unit == "bytes":
        suffix = " bytes"
    return f"{sign}{rounded:,}{suffix}"


def _delta_tone(delta: float, prefer: str) -> str:
    if delta == 0:
        if prefer == "same":
            return "good"
        return "neutral"
    if prefer == "lower":
        return "good" if delta < 0 else "bad"
    if prefer == "higher":
        return "good" if delta > 0 else "bad"
    if prefer == "same":
        return "bad"
    return "info"


def _metric_delta_tone(
    metrics_by_track: dict[str, object],
    number_fn: Callable[[object], float | int | None],
    prefer: str,
) -> str:
    plain, workerbee = _plain_workerbee(metrics_by_track)
    if plain is None or workerbee is None:
        return "neutral"
    base = number_fn(plain)
    value = number_fn(workerbee)
    if base is None or value is None:
        return "neutral"
    return _delta_tone(float(value) - float(base), prefer)


def _tone_class(tone: str) -> str:
    if tone in {"good", "bad", "info", "neutral"}:
        return f"delta-{tone}"
    return "delta-neutral"


def _delta_note(*, diagnostic: bool = False) -> str:
    if diagnostic:
        return (
            "Audit is blocked for this run, so percentage deltas are diagnostic only. "
            "Use the raw track values and audit findings to plan the rerun; do not "
            "treat these deltas as accepted comparison results."
        )
    return (
        "Deltas compare workerbee-codex against plain-codex. Green means the "
        "WorkerBee value moved in the preferred direction for that metric, red "
        "means it moved away from the preferred direction, and blue marks "
        "automation-oriented or neutral metrics. Runtime deltas use realistic "
        "runtime, which includes explicit manual time-tax events."
    )


def _technical_rows(metrics_by_track: dict[str, object]) -> str:
    rows = []
    for track, metrics in metrics_by_track.items():
        rows.append(
            "<tr>"
            f"<th>{escape(track)}</th>"
            f"<td>{escape(metrics.duration.label)}</td>"
            f"<td>{escape(metrics.manual_time_tax_label)}</td>"
            f"<td><code>{escape(metrics.observed_duration.started_at)}</code></td>"
            f"<td><code>{escape(metrics.observed_duration.ended_at)}</code></td>"
            f"<td>{metrics.operator_touches}</td>"
            f"<td>{metrics.human_commands}</td>"
            f"<td>{metrics.human_actions}</td>"
            f"<td>{metrics.context_management_actions}</td>"
            f"<td>{metrics.ae_actions}</td>"
            f"<td>{metrics.workerbee_actions}</td>"
            f"<td>{metrics.evidence}</td>"
            f"<td>{escape(', '.join(metrics.evidence_phases) or 'none')}</td>"
            f"<td>{metrics.violations}</td>"
            f"<td>{metrics.usage_snapshots}</td>"
            f"<td>{metrics.codex_turns_missing_usage}</td>"
            f"<td>{metrics.input_tokens}</td>"
            f"<td>{metrics.final_turn_input_tokens}</td>"
            f"<td>{metrics.max_turn_input_tokens}</td>"
            f"<td>{metrics.prompt_bytes}</td>"
            f"<td>{_prompt_metadata_coverage(metrics)}</td>"
            f"<td>{metrics.max_prompt_bytes}</td>"
            f"<td>{metrics.copied_context_bytes}</td>"
            f"<td>{metrics.copied_context_sources}</td>"
            "</tr>"
        )
    return "".join(rows)


def _observed_caveats(run_root: Path) -> list[str]:
    caveats = []
    command_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")[:20000]
        for path in sorted(run_root.glob("*/commands/*"))
        if path.is_file()
    )
    if "ambiguous site definition" in command_text:
        caveats.append(
            "WorkerBee local HTTPS ingress reported an ambiguous Caddy site definition; "
            "the local baseline used direct profile ports for browser evidence."
        )
    if "user cancelled MCP tool call" in command_text:
        caveats.append(
            "A nested Codex WorkerBee MCP call was cancelled; the measured WorkerBee runtime path "
            "used the direct-containerd helper instead."
        )
    if "profile stop" in command_text and "rm -f ae-padawan" in command_text:
        caveats.append(
            "Profile stop left workload containers behind; the run includes explicit cleanup of "
            "the remaining direct-containerd workload containers."
        )
    return caveats


def _is_reviewable(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES | VIDEO_SUFFIXES | TEXT_SUFFIXES


def _text_preview(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")[:8000]
    except UnicodeDecodeError:
        text = "Text preview unavailable for this encoding."
    return f"<pre>{escape(text)}</pre>"


def _meta_rows(pairs: Iterable[tuple[str, object]]) -> str:
    rows = []
    for label, value in pairs:
        text = "" if value is None else str(value)
        rendered = (
            '<span class="empty">not recorded</span>'
            if not text
            else f"<code>{escape(text)}</code>"
        )
        rows.append(f"<dt>{escape(label)}</dt><dd>{rendered}</dd>")
    return "".join(rows)


def _scenario_mapping(manifest: dict[str, object]) -> dict[str, object]:
    scenario = manifest.get("scenario")
    if isinstance(scenario, dict):
        return scenario
    if not manifest.get("padawan_root"):
        return {}

    fallback = load_scenario(REPO_ROOT).to_manifest()
    fallback["source"] = "built-in:padawan-peer (legacy manifest fallback)"
    target = _mapping_value(fallback, "target")
    k1s = _mapping_value(fallback, "k1s")
    workerbee = _mapping_value(fallback, "workerbee")
    target["repo_root"] = str(manifest.get("padawan_root") or target.get("repo_root") or "")
    if manifest.get("feature_prompt"):
        target["feature_prompt"] = str(manifest["feature_prompt"])
    k1s["repo_root"] = str(manifest.get("k1s_root") or k1s.get("repo_root") or "")
    workerbee["repo_root"] = str(manifest.get("workerbee_root") or workerbee.get("repo_root") or "")
    if isinstance(manifest.get("runtime_policy"), dict):
        fallback["runtime_policy"] = manifest["runtime_policy"]
    return fallback


def _is_legacy_calibration(manifest: dict[str, object]) -> bool:
    return "scenario" not in manifest and bool(manifest.get("padawan_root"))


def _mapping_value(parent: dict[str, object], key: str) -> dict[str, object]:
    value = parent.get(key)
    return value if isinstance(value, dict) else {}


def _review_settings(manifest: dict[str, object]) -> dict[str, object]:
    scenario = _scenario_mapping(manifest)
    target = _mapping_value(scenario, "target")
    k1s = _mapping_value(scenario, "k1s")
    workerbee = _mapping_value(scenario, "workerbee")
    return {
        "run": {
            "run_id": manifest.get("run_id"),
            "created_at": manifest.get("created_at"),
            "partial_preview": manifest.get("partial_preview", False),
            "partial_preview_note": manifest.get("partial_preview_note"),
            "plain_reference_run": manifest.get("plain_reference_run"),
            "plain_reference_note": manifest.get("plain_reference_note"),
            "lineage": manifest.get("lineage"),
            "audit_adjustments": manifest.get("audit_adjustments"),
        },
        "scenario": {
            "name": scenario.get("name"),
            "source": scenario.get("source"),
        },
        "target": {
            "label": manifest.get("target_label") or target.get("label"),
            "repo_root": manifest.get("target_root")
            or manifest.get("padawan_root")
            or target.get("repo_root"),
            "feature_prompt": manifest.get("feature_prompt") or target.get("feature_prompt"),
        },
        "repositories": {
            "k1s": manifest.get("k1s_root") or k1s.get("repo_root"),
            "workerbee": manifest.get("workerbee_root") or workerbee.get("repo_root"),
        },
        "runtime_policy": scenario.get("runtime_policy") or manifest.get("runtime_policy") or {},
        "preflight": scenario.get("preflight") or {},
        "k1s_ingress": scenario.get("k1s_ingress") or {},
        "evidence": scenario.get("evidence") or {},
        "workerbee_stage": scenario.get("workerbee_stage") or {},
    }


def _flatten_settings(
    value: object,
    prefix: str = "",
) -> Iterable[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_key = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten_settings(child, child_key)
        return
    yield prefix, value


def _setting_value_html(value: object) -> str:
    if value is None or value == "":
        return '<span class="empty">not recorded</span>'
    if isinstance(value, bool):
        return f"<code>{str(value).lower()}</code>"
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, indent=2, sort_keys=True, default=str)
        return f'<pre class="settings-value">{escape(text)}</pre>'
    text = str(value)
    if "\n" in text or len(text) > 120:
        return f'<pre class="settings-value">{escape(text)}</pre>'
    return f"<code>{escape(text)}</code>"


def _json_block(value: object, *, compact: bool = False) -> str:
    text = json.dumps(value, indent=None if compact else 2, sort_keys=True, default=str)
    if compact and len(text) > 360:
        text = text[:360] + "..."
    return f"<pre>{escape(text)}</pre>"


def _script_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str).replace(
        "</", "<\\/"
    )


def _prepare_html_assets(output_dir: Path) -> None:
    _copy_if_exists(
        REPO_ROOT / "node_modules" / "chart.js" / "dist" / "chart.umd.min.js",
        output_dir / "assets" / "chart.umd.min.js",
    )
    for asset in (
        "favicon.ico",
        "favicon-32x32.svg",
        "k1s-logo-circle.svg",
        "k1s-logo-horizontal.svg",
    ):
        _copy_if_exists(K1S_STATIC_ROOT / asset, output_dir / "static" / asset)
    _copy_if_exists(
        K1S_STATIC_ROOT / "dash-assets" / "page-background-tile-1024.png",
        output_dir / "static" / "dash-assets" / "page-background-tile-1024.png",
    )
    _copy_if_exists(
        K1S_STATIC_ROOT / "dash-assets" / "page-background-3840x2160.png",
        output_dir / "static" / "dash-assets" / "page-background-3840x2160.png",
    )


def _copy_if_exists(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _short_time(value: datetime) -> str:
    return value.strftime("%H:%M:%S")


def _href(path: Path, output_dir: Path) -> str:
    target = path.resolve() if path.is_absolute() else path
    rel = os.path.relpath(target, output_dir.resolve())
    return quote(rel.replace(os.sep, "/"), safe="/.:#?=&%")


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _page(run_id: str, active: str, body: str) -> str:
    nav_links = " ".join(
        f'<a class="{"active" if label == active else ""}" href="{href}">{label}</a>'
        for label, href in (
            ("Executive", "executive.html"),
            ("Summary", "index.html"),
            ("Technical", "technical.html"),
            ("Charts", "charts.html"),
            ("Timeline", "timeline.html"),
            ("Artifacts", "evidence.html"),
        )
    )
    nav = (
        '<a class="nav-brand" href="index.html" aria-label="simreport home">'
        '<img src="static/k1s-logo-circle.svg" alt="k1s logo">'
        "<span>k1s / WorkerBee Simreport</span></a>"
        '<span class="nav-group-label" aria-hidden="true">Review</span>'
        f"{nav_links}"
    )
    return f"""<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(run_id)} - {escape(active)}</title>
  <link rel="icon" href="static/favicon.ico" sizes="any">
  <link rel="icon" type="image/svg+xml" href="static/favicon-32x32.svg">
  <script>
    (function() {{
      var key = 'k1s-theme';
      var saved = null;
      try {{ saved = localStorage.getItem(key); }} catch (_err) {{ saved = null; }}
      var initial = (saved === 'dark' || saved === 'light') ? saved : 'light';
      document.documentElement.setAttribute('data-theme', initial);
      window.simulacraApplyTheme = function(next) {{
        var theme = (next === 'dark' || next === 'light') ? next : 'light';
        document.documentElement.setAttribute('data-theme', theme);
        try {{ localStorage.setItem(key, theme); }} catch (_err) {{}}
        var event = new CustomEvent('simulacra:themechange', {{
          detail: {{ theme: theme }}
        }});
        window.dispatchEvent(event);
      }};
      window.simulacraWireThemeToggle = function() {{
        var btn = document.getElementById('theme-toggle');
        if (!btn) return;
        var labels = {{
          dark: 'Switch to light mode',
          light: 'Switch to dark mode'
        }};
        function update() {{
          var cur = document.documentElement.getAttribute('data-theme') || 'light';
          var label = labels[cur] || 'Toggle theme';
          btn.setAttribute('aria-label', label);
          btn.setAttribute('title', label);
        }}
        update();
        btn.addEventListener('click', function() {{
          var cur = document.documentElement.getAttribute('data-theme') || 'light';
          window.simulacraApplyTheme(cur === 'dark' ? 'light' : 'dark');
          update();
        }});
      }};
      if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', window.simulacraWireThemeToggle);
      }} else {{
        window.simulacraWireThemeToggle();
      }}
    }})();
  </script>
  <style>
    :root {{
      color-scheme: light dark;
      --k1s-bg: #f4f5f7;
      --k1s-surface: #f8fafb;
      --k1s-panel: #ffffff;
      --k1s-border: #d4d7dd;
      --k1s-border-soft: #e6e8ec;
      --k1s-text: #0f141c;
      --k1s-text-muted: #4a5565;
      --k1s-primary: #2563eb;
      --k1s-primary-soft: #3b82f6;
      --k1s-highlight: #60a5fa;
      --k1s-info: #0284c7;
      --k1s-info-bg: #e0f2fe;
      --k1s-success: #16a34a;
      --k1s-success-bg: #16a34a33;
      --k1s-warn: #f59e0b;
      --k1s-warn-bg: #f59e0b33;
      --k1s-danger: #ef4444;
      --k1s-danger-bg: #ef444433;
      --k1s-card-bg: #ffffff;
      --k1s-header-bg: rgba(255,255,255,0.82);
      --k1s-radius: 8px;
      --k1s-radius-pill: 999px;
      --k1s-gap: 12px;
      --k1s-brand-gold: #fbc02d;
      --k1s-brand-graphite: #404040;
      --k1s-brand-mist: #f1f1f1;
      --k1s-page-bg-image: url('static/dash-assets/page-background-tile-1024.png');
      --k1s-page-overlay: linear-gradient(rgba(244,245,247,0.9), rgba(244,245,247,0.9));
      --k1s-mix-bg: #ffffff;
      --k1s-report-header-bg:
        radial-gradient(
          circle at 92% 8%,
          color-mix(in srgb, var(--k1s-brand-gold) 26%, transparent) 0%,
          transparent 60%
        ),
        linear-gradient(
          135deg,
          #ffffff 0%,
          #f8f7f2 60%,
          color-mix(in srgb, var(--k1s-brand-gold) 18%, #ffffff) 100%
        );
      --bg: var(--k1s-bg);
      --fg: var(--k1s-text);
      --muted: var(--k1s-panel);
      --link: #2f59b9;
      --link-hover: #3b63c5;
      --code-bg: #f5f6f8;
      --border: var(--k1s-border);
    }}
    html[data-theme="dark"] {{
      --k1s-bg: #121212;
      --k1s-surface: #181818;
      --k1s-panel: #2c2c2c;
      --k1s-border: #404040;
      --k1s-border-soft: #4a4a4a;
      --k1s-text: #e5e7eb;
      --k1s-text-muted: #9ca3af;
      --k1s-card-bg: #2c2c2c;
      --k1s-header-bg: #0a0a0a10;
      --k1s-page-bg-image: url('static/dash-assets/page-background-3840x2160.png');
      --k1s-page-overlay: linear-gradient(rgba(7,10,14,0.72), rgba(7,10,14,0.72));
      --k1s-mix-bg: #000000;
      --k1s-report-header-bg:
        radial-gradient(
          circle at 92% 8%,
          color-mix(in srgb, var(--k1s-brand-gold) 18%, transparent) 0%,
          transparent 60%
        ),
        linear-gradient(
          135deg,
          #181818 0%,
          #252525 64%,
          color-mix(in srgb, var(--k1s-brand-gold) 12%, #2c2c2c) 100%
        );
      --bg: var(--k1s-bg);
      --fg: var(--k1s-text);
      --muted: var(--k1s-panel);
      --link: #5a86c9;
      --link-hover: #7aa0e8;
      --code-bg: #1b1b1b;
      --border: var(--k1s-border);
    }}
    html {{ height: 100%; }}
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 2rem;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      background-color: var(--bg);
      background-image: var(--k1s-page-overlay), var(--k1s-page-bg-image);
      background-size: 100% 100%, auto 100%;
      background-position: center top, center top;
      background-repeat: repeat-y, repeat-y;
      color: var(--fg);
      font: 13px/1.55 system-ui, -apple-system, "Segoe UI", "Roboto", sans-serif;
    }}
    img {{ max-width: 100%; height: auto; }}
    nav {{
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: .6rem;
      justify-content: center;
      margin: 0 auto 1.25rem auto;
      width: min(100%, 1320px);
      padding: 10px 16px;
      background: var(--k1s-panel);
      border: 1px solid var(--k1s-border);
      border-radius: 14px;
      box-shadow: 0 8px 30px rgba(0,0,0,0.12);
      position: sticky;
      top: 12px;
      z-index: 10;
      backdrop-filter: blur(6px);
      -webkit-backdrop-filter: blur(6px);
    }}
    nav::after {{
      content: "";
      position: absolute;
      left: 14px;
      right: 14px;
      bottom: 6px;
      height: 2px;
      border-radius: 999px;
      background: linear-gradient(90deg, transparent, var(--k1s-brand-gold), transparent);
      opacity: 0.5;
      pointer-events: none;
    }}
    nav a {{
      display: inline-flex;
      align-items: center;
      gap: .25rem;
      padding: 7px 10px;
      border: 1px solid var(--k1s-border);
      border-radius: 10px;
      background: var(--k1s-card-bg);
      color: var(--fg);
      text-decoration: none;
      box-shadow: 0 6px 16px rgba(0,0,0,0.16);
      transition:
        background .15s ease,
        border-color .15s ease,
        transform .12s ease,
        color .15s ease;
      font-weight: 600;
    }}
    nav a:hover,
    nav a.active {{
      background: var(--k1s-surface);
      border-color: var(--k1s-brand-gold);
      color: var(--link-hover);
      transform: translateY(-1px);
    }}
    nav .nav-brand {{
      gap: 10px;
      padding: 6px 10px;
      border: 1px solid transparent;
      background: transparent;
      box-shadow: none;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 11px;
      color: var(--k1s-text-muted);
    }}
    nav .nav-brand:hover {{
      background: color-mix(in srgb, var(--k1s-card-bg) 60%, transparent);
      border-color: var(--k1s-brand-gold);
      color: var(--fg);
      transform: translateY(0);
    }}
    nav .nav-brand img {{
      width: 28px;
      height: 28px;
      border-radius: 999px;
      box-shadow: 0 6px 16px rgba(0,0,0,0.2);
    }}
    nav .nav-group-label {{
      display: inline-flex;
      align-items: center;
      padding: 4px 2px 4px 8px;
      color: var(--k1s-text-muted);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      white-space: nowrap;
    }}
    nav .nav-group-label::before {{
      content: "";
      width: 16px;
      height: 1px;
      margin-right: 8px;
      background: linear-gradient(90deg, transparent, var(--k1s-brand-gold));
      opacity: 0.75;
    }}
    .theme-fab {{
      position: fixed;
      right: 18px;
      bottom: 24px;
      width: 52px;
      height: 52px;
      border-radius: 50%;
      border: 1px solid var(--k1s-border);
      background: var(--k1s-card-bg);
      color: var(--fg);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 12px 35px rgba(0,0,0,0.32);
      cursor: pointer;
      z-index: 20;
      transition:
        background .15s ease,
        border-color .15s ease,
        transform .15s ease,
        box-shadow .15s ease;
    }}
    .theme-fab:hover {{
      background: var(--k1s-surface);
      border-color: var(--k1s-border-soft);
      transform: translateY(-1px);
      box-shadow: 0 14px 40px rgba(0,0,0,0.38);
    }}
    .theme-fab:active {{ transform: translateY(0); }}
    .theme-fab svg {{ width: 26px; height: 26px; fill: currentColor; }}
    .theme-fab .icon-sun {{ display: none; }}
    html[data-theme="light"] .theme-fab .icon-sun {{ display: block; }}
    html[data-theme="light"] .theme-fab .icon-moon {{ display: none; }}
    html[data-theme="dark"] .theme-fab .icon-moon {{ display: block; }}
    .container {{
      width: min(100%, 1320px);
      max-width: 1320px;
      margin: 0 auto;
      flex: 1 0 auto;
    }}
    .report-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
      padding: 18px;
      border: 1px solid var(--k1s-border);
      border-radius: 18px;
      background: var(--k1s-report-header-bg);
      box-shadow: 0 16px 40px rgba(0,0,0,0.12);
    }}
    .report-brand {{
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }}
    .report-logo {{ width: min(180px, 42vw); }}
    .report-pill {{
      padding: 6px 12px;
      border-radius: 999px;
      font-weight: 700;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      background: var(--k1s-brand-gold);
      color: #2b2b2b;
      box-shadow: 0 10px 22px rgba(251,192,45,0.25);
      white-space: nowrap;
    }}
    .report-title {{ min-width: 0; text-align: right; }}
    h1 {{ margin: 0; font-size: 28px; letter-spacing: 0.01em; }}
    h2 {{ margin: 0 0 14px; font-size: 20px; line-height: 1.3; }}
    h3 {{ margin: 0 0 8px; font-size: 17px; }}
    main {{ width: 100%; }}
    .panel {{
      margin-bottom: 1rem;
      padding: 12px;
      border: 1px solid var(--k1s-border);
      border-radius: var(--k1s-radius);
      background: var(--k1s-card-bg);
      overflow-x: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1rem 0;
      background: var(--k1s-panel);
      border: 1px solid var(--k1s-border);
      border-radius: 10px;
      overflow: hidden;
    }}
    th, td {{
      padding: 12px 14px;
      border-top: 1px solid var(--k1s-border-soft);
      text-align: left;
      vertical-align: top;
    }}
    tbody tr:nth-child(even) td {{
      background: color-mix(in srgb, var(--k1s-panel) 92%, var(--k1s-mix-bg) 8%);
    }}
    th {{
      font-size: 12px;
      color: var(--fg);
      text-transform: uppercase;
      font-weight: 600;
      background: var(--k1s-card-bg);
    }}
    code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    code, pre {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      color: var(--fg);
      border-radius: 8px;
    }}
    code {{ overflow-wrap: anywhere; }}
    pre {{
      max-height: 520px;
      overflow: auto;
      padding: 12px;
      white-space: pre-wrap;
      scrollbar-width: none;
      -ms-overflow-style: none;
    }}
    pre::-webkit-scrollbar {{ width: 0; height: 0; }}
    .meta {{ display: grid; grid-template-columns: max-content 1fr; gap: 8px 14px; }}
    .meta dt {{ color: var(--k1s-text-muted); }}
    .meta dd {{ margin: 0; }}
    .prompt-block {{ max-height: 300px; }}
    .settings-table th:first-child {{ width: 34%; }}
    .settings-table td {{ min-width: 320px; }}
    .settings-value {{ max-height: 240px; margin: 0; }}
    .audit-panel {{
      border-top: 5px solid var(--k1s-text-muted);
    }}
    .audit-panel.audit-accepted {{
      border-top-color: var(--k1s-success);
    }}
    .audit-panel.audit-blocked {{
      border-top-color: var(--k1s-danger);
    }}
    .audit-pill {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 3px 10px;
      border-radius: var(--k1s-radius-pill);
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .audit-pill.audit-accepted {{
      background: var(--k1s-success-bg);
      color: var(--k1s-success);
    }}
    .audit-pill.audit-blocked {{
      background: var(--k1s-danger-bg);
      color: var(--k1s-danger);
    }}
    .audit-table .audit-error td:first-child {{ color: var(--k1s-danger); font-weight: 700; }}
    .audit-table .audit-warning td:first-child {{ color: var(--k1s-warn); font-weight: 700; }}
    .audit-table .audit-info td:first-child {{ color: var(--k1s-info); font-weight: 700; }}
    .delta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .delta-card {{
      --delta-color: var(--k1s-text-muted);
      --delta-bg: var(--k1s-surface);
      --delta-border: var(--k1s-border-soft);
      display: grid;
      gap: 6px;
      min-height: 118px;
      padding: 12px;
      border: 1px solid var(--delta-border);
      border-left: 5px solid var(--delta-color);
      border-radius: var(--k1s-radius);
      background: var(--delta-bg);
    }}
    .delta-label {{
      color: var(--k1s-text-muted);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .delta-value {{
      color: var(--delta-color);
      font-size: 24px;
      line-height: 1.05;
    }}
    .delta-card small {{ color: var(--k1s-text-muted); }}
    .delta-suppressed {{
      grid-column: 1 / -1;
      min-height: 96px;
    }}
    .delta-badge {{
      --delta-color: var(--k1s-text-muted);
      --delta-bg: var(--k1s-surface);
      --delta-border: var(--k1s-border-soft);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 76px;
      padding: 4px 9px;
      border: 1px solid var(--delta-border);
      border-radius: var(--k1s-radius-pill);
      background: var(--delta-bg);
      color: var(--delta-color);
      font-weight: 700;
      white-space: nowrap;
    }}
    .delta-good {{
      --delta-color: var(--k1s-success);
      --delta-bg: color-mix(in srgb, var(--k1s-success) 10%, var(--k1s-mix-bg));
      --delta-border: color-mix(in srgb, var(--k1s-success) 38%, var(--k1s-border-soft));
    }}
    .delta-bad {{
      --delta-color: var(--k1s-danger);
      --delta-bg: color-mix(in srgb, var(--k1s-danger) 9%, var(--k1s-mix-bg));
      --delta-border: color-mix(in srgb, var(--k1s-danger) 38%, var(--k1s-border-soft));
    }}
    .delta-info {{
      --delta-color: var(--k1s-info);
      --delta-bg: color-mix(in srgb, var(--k1s-info) 10%, var(--k1s-mix-bg));
      --delta-border: color-mix(in srgb, var(--k1s-info) 36%, var(--k1s-border-soft));
    }}
    .delta-neutral {{
      --delta-color: var(--k1s-text-muted);
      --delta-bg: var(--k1s-surface);
      --delta-border: var(--k1s-border-soft);
    }}
    .gallery {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
    }}
    .artifact {{
      padding: 12px;
      border: 1px solid var(--k1s-border-soft);
      border-radius: 8px;
      background: var(--k1s-surface);
    }}
    .artifact img, .artifact video {{
      display: block;
      width: 100%;
      max-height: 420px;
      object-fit: contain;
      border: 1px solid var(--k1s-border-soft);
      border-radius: 6px;
      background: var(--k1s-panel);
    }}
    .chart-panel {{
      --delta-color: var(--k1s-text-muted);
      --delta-border: var(--k1s-border-soft);
      padding-bottom: 14px;
      border-top: 5px solid var(--delta-color);
      box-shadow: inset 0 1px 0 var(--delta-border);
    }}
    .chart-grid-layout {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
      gap: 1rem;
      align-items: stretch;
    }}
    .chart-shell {{
      position: relative;
      width: 100%;
      min-height: 320px;
      height: 360px;
      padding: 10px;
      border: 1px solid var(--delta-border);
      border-radius: 14px;
      background: var(--k1s-surface);
    }}
    .chart-shell canvas {{ width: 100% !important; height: 100% !important; }}
    .empty {{ color: var(--k1s-text-muted); }}
    a {{ color: var(--link); }}
    a:hover {{ color: var(--link-hover); }}
    a:focus-visible {{
      outline: 2px solid var(--k1s-highlight);
      outline-offset: 2px;
      border-radius: 4px;
    }}
    .site-footer {{
      margin-top: 3rem;
      border-top: 1px solid var(--k1s-border);
      color: var(--k1s-text-muted);
    }}
    .site-footer .inner {{
      display: flex;
      align-items: center;
      gap: .75rem;
      padding: 14px 0;
      opacity: .85;
    }}
    @media (max-width: 980px) {{
      body {{ padding: 1.5rem; }}
      nav {{
        width: 100%;
        padding: 8px 10px;
        gap: .5rem;
        justify-content: flex-start;
      }}
      nav a {{ padding: 6px 10px; font-size: 12px; }}
      nav .nav-group-label {{ font-size: 10px; letter-spacing: 0.1em; padding-left: 6px; }}
      nav .nav-brand {{ font-size: 10px; letter-spacing: 0.1em; }}
      .report-header {{ flex-direction: column; align-items: flex-start; }}
      .report-title {{ text-align: left; }}
      .chart-grid-layout {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 720px) {{
      body {{ padding: 1.1rem; }}
      nav {{
        top: 8px;
        flex-wrap: nowrap;
        overflow-x: auto;
        scrollbar-width: none;
      }}
      nav::-webkit-scrollbar {{ width: 0; height: 0; }}
      nav a, nav .nav-group-label {{ flex: 0 0 auto; }}
      nav::after {{ left: 8px; right: 8px; }}
      .theme-fab {{ right: 12px; bottom: 16px; width: 48px; height: 48px; }}
      h1 {{ font-size: 24px; }}
      h2 {{ font-size: 18px; }}
      h3 {{ font-size: 15px; }}
      table {{
        display: block;
        max-width: 100%;
        width: max-content;
        min-width: 100%;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
      }}
      thead th, tbody td {{ padding: 10px 12px; }}
      .chart-shell {{ height: 300px; }}
    }}
  </style>
</head>
<body>
  <nav>{nav}</nav>
  <button id="theme-toggle" class="theme-fab" aria-label="Toggle theme" title="Toggle theme">
    <svg class="icon-sun" viewBox="0 -960 960 960" aria-hidden="true" focusable="false">
      <path d="{SUN_ICON_PATH}"/>
    </svg>
    <svg class="icon-moon" viewBox="0 -960 960 960" aria-hidden="true" focusable="false">
      <path d="{MOON_ICON_PATH}"/>
    </svg>
  </button>
  <div class="container">
    <header class="report-header">
      <div class="report-brand">
        <img src="static/k1s-logo-horizontal.svg" alt="k1s logo" class="report-logo">
        <span class="report-pill">Simulation Evidence</span>
      </div>
      <div class="report-title">
        <h1>{escape(run_id)}</h1>
      </div>
    </header>
    <main>{body}</main>
    <footer class="site-footer">
      <div class="inner">k1s / WorkerBee simulation report package</div>
    </footer>
  </div>
</body>
</html>
"""
