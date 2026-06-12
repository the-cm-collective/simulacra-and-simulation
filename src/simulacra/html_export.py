from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import quote

from .metrics import run_duration, track_metrics
from .runs import TRACKS
from .schema import SimulationEvent, read_events

IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".webm"}
TEXT_SUFFIXES = {".json", ".jsonl", ".log", ".md", ".txt"}


@dataclass(frozen=True)
class HtmlExport:
    output_dir: Path
    pages: list[Path]


def export_run_html(run_root: Path, output_dir: Path | None = None) -> HtmlExport:
    output = output_dir or run_root / "html"
    output.mkdir(parents=True, exist_ok=True)
    manifest = _read_json(run_root / "manifest.json")
    events_by_track = {track: read_events(run_root / track / "events.jsonl") for track in TRACKS}
    metrics_by_track = {track: track_metrics(events) for track, events in events_by_track.items()}
    duration = run_duration(events_by_track)
    report_path = run_root / "report.md"
    pages = [
        _write(output / "executive.html", _executive_page(run_root, metrics_by_track, duration)),
        _write(
            output / "index.html",
            _index_page(run_root, output, manifest, metrics_by_track, duration, report_path),
        ),
        _write(
            output / "technical.html",
            _technical_page(run_root, output, manifest, metrics_by_track, duration),
        ),
        _write(output / "timeline.html", _timeline_page(run_root, output, events_by_track)),
        _write(output / "evidence.html", _artifacts_page(run_root, output, events_by_track)),
    ]
    return HtmlExport(output_dir=output, pages=pages)


def _index_page(
    run_root: Path,
    output_dir: Path,
    manifest: dict[str, object],
    metrics_by_track: dict[str, object],
    duration,
    report_path: Path,
) -> str:
    rows = []
    for track, metrics in metrics_by_track.items():
        rows.append(
            "<tr>"
            f"<th>{escape(track)}</th>"
            f"<td>{escape(metrics.duration.label)}</td>"
            f"<td>{metrics.events}</td>"
            f"<td>{metrics.prompts}</td>"
            f"<td>{metrics.commands}</td>"
            f"<td>{metrics.workerbee_actions}</td>"
            f"<td>{metrics.evidence}</td>"
            f"<td>{metrics.violations}</td>"
            f"<td>{metrics.input_tokens}</td>"
            f"<td>{metrics.output_tokens}</td>"
            f"<td>{escape(metrics.completeness)}</td>"
            "</tr>"
        )
    manifest_items = "".join(
        f"<dt>{escape(str(key))}</dt><dd><code>{escape(str(value))}</code></dd>"
        for key, value in manifest.items()
        if key not in {"tracks", "runtime_policy"}
    )
    runtime_policy = _json_block(manifest.get("runtime_policy", {}))
    report = (
        report_path.read_text(encoding="utf-8") if report_path.exists() else "report.md not found"
    )
    body = f"""
<section class="panel">
  <h2>Run Summary</h2>
  <dl class="meta">{manifest_items}</dl>
  <p><strong>Start-to-finish runtime:</strong> {escape(duration.label)}</p>
  <p><strong>First event:</strong> <code>{escape(duration.started_at)}</code></p>
  <p><strong>Last event:</strong> <code>{escape(duration.ended_at)}</code></p>
</section>
<section class="panel">
  <h2>Track Metrics</h2>
  <table>
    <thead>
      <tr>
        <th>Track</th><th>Runtime</th><th>Events</th><th>Prompts</th><th>Commands</th>
        <th>WorkerBee</th><th>Evidence</th><th>Violations</th>
        <th>Input tokens</th><th>Output tokens</th><th>Completeness</th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Runtime Policy</h2>
  {runtime_policy}
</section>
<section class="panel">
  <h2>Markdown Report</h2>
  <p><a href="{_href(report_path, output_dir)}">Open raw report.md</a></p>
  <pre>{escape(report)}</pre>
</section>
"""
    return _page(run_root.name, "Summary", body)


def _executive_page(run_root: Path, metrics_by_track: dict[str, object], duration) -> str:
    complete = all(metrics.completeness == "complete" for metrics in metrics_by_track.values())
    violation_count = sum(metrics.violations for metrics in metrics_by_track.values())
    status = "Complete" if complete and violation_count == 0 else "Needs Review"
    rows = _comparison_rows(metrics_by_track)
    body = f"""
<section class="panel">
  <h2>Executive Summary</h2>
  <p><strong>Status:</strong> {status}</p>
  <p><strong>Start-to-finish runtime:</strong> {escape(duration.label)}</p>
  <p>
    This run produced complete local measurement streams for the constrained
    plain-Codex path and the WorkerBee direct-containerd path. Both local
    browser evidence runs passed the Padawan/Jedi peer-flow test.
  </p>
</section>
<section class="panel">
  <h2>Comparison Snapshot</h2>
  <table>
    <thead>
      <tr><th>Metric</th>{"".join(f"<th>{escape(track)}</th>" for track in metrics_by_track)}</tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Interpretation Boundary</h2>
  <p>
    This evidence supports comparison of process and validation behavior:
    prompts, commands, WorkerBee actions, token usage, runtime, protocol
    adherence, and evidence completeness. It does not, by itself, prove one
    track produced higher implementation quality because both tracks validated
    the same already-present Padawan feature branch in this local baseline.
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
) -> str:
    caveats = _observed_caveats(run_root)
    caveat_items = "".join(f"<li>{escape(item)}</li>" for item in caveats)
    if not caveat_items:
        caveat_items = '<li class="empty">No known caveats detected in command logs.</li>'
    body = f"""
<section class="panel">
  <h2>Technical Summary</h2>
  <p>
    Runtime and event metrics are derived from JSONL event timestamps. Evidence
    artifacts are linked from the run tree rather than copied into the HTML
    package.
  </p>
  <dl class="meta">
    <dt>Run</dt><dd><code>{escape(run_root.name)}</code></dd>
    <dt>Start-to-finish runtime</dt><dd>{escape(duration.label)}</dd>
    <dt>First event</dt><dd><code>{escape(duration.started_at)}</code></dd>
    <dt>Last event</dt><dd><code>{escape(duration.ended_at)}</code></dd>
  </dl>
</section>
<section class="panel">
  <h2>Track Details</h2>
  <table>
    <thead>
      <tr>
        <th>Track</th><th>Runtime</th><th>First Event</th><th>Last Event</th>
        <th>Commands</th><th>WorkerBee Actions</th><th>Evidence</th>
        <th>Protocol Violations</th>
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
        for artifact in (run_root / "manifest.json", run_root / "report.md")
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


def _comparison_rows(metrics_by_track: dict[str, object]) -> str:
    rows = []
    specs = [
        ("Completeness", lambda metrics: metrics.completeness),
        ("Runtime", lambda metrics: metrics.duration.label),
        ("Human prompts", lambda metrics: str(metrics.prompts)),
        ("Commands", lambda metrics: str(metrics.commands)),
        ("WorkerBee actions", lambda metrics: str(metrics.workerbee_actions)),
        ("Evidence artifacts", lambda metrics: str(metrics.evidence)),
        ("Protocol violations", lambda metrics: str(metrics.violations)),
        ("Input tokens", lambda metrics: str(metrics.input_tokens)),
        ("Output tokens", lambda metrics: str(metrics.output_tokens)),
    ]
    for label, value_fn in specs:
        rows.append(
            f"<tr><th>{escape(label)}</th>"
            + "".join(
                f"<td>{escape(value_fn(metrics))}</td>" for metrics in metrics_by_track.values()
            )
            + "</tr>"
        )
    return "".join(rows)


def _technical_rows(metrics_by_track: dict[str, object]) -> str:
    rows = []
    for track, metrics in metrics_by_track.items():
        rows.append(
            "<tr>"
            f"<th>{escape(track)}</th>"
            f"<td>{escape(metrics.duration.label)}</td>"
            f"<td><code>{escape(metrics.duration.started_at)}</code></td>"
            f"<td><code>{escape(metrics.duration.ended_at)}</code></td>"
            f"<td>{metrics.commands}</td>"
            f"<td>{metrics.workerbee_actions}</td>"
            f"<td>{metrics.evidence}</td>"
            f"<td>{metrics.violations}</td>"
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


def _json_block(value: object, *, compact: bool = False) -> str:
    text = json.dumps(value, indent=None if compact else 2, sort_keys=True, default=str)
    if compact and len(text) > 360:
        text = text[:360] + "..."
    return f"<pre>{escape(text)}</pre>"


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _href(path: Path, output_dir: Path) -> str:
    target = path.resolve() if path.is_absolute() else path
    rel = os.path.relpath(target, output_dir.resolve())
    return quote(rel.replace(os.sep, "/"), safe="/.:#?=&%")


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _page(run_id: str, active: str, body: str) -> str:
    nav = " ".join(
        f'<a class="{"active" if label == active else ""}" href="{href}">{label}</a>'
        for label, href in (
            ("Executive", "executive.html"),
            ("Summary", "index.html"),
            ("Technical", "technical.html"),
            ("Timeline", "timeline.html"),
            ("Artifacts", "evidence.html"),
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(run_id)} - {escape(active)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #5c6670;
      --line: #d8dde3;
      --accent: #0f766e;
      --accent-soft: #e7f5f3;
      --warn: #8a4b08;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 24px 28px 12px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{ margin: 0 0 12px; font-size: 24px; }}
    h2 {{ margin: 0 0 16px; font-size: 18px; }}
    h3 {{ margin: 0 0 8px; font-size: 14px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    nav a {{
      padding: 7px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      color: var(--ink);
      text-decoration: none;
      background: #fff;
    }}
    nav a.active {{ border-color: var(--accent); background: var(--accent-soft); color: #07544f; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
    .panel {{
      margin-bottom: 18px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      overflow-x: auto;
    }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{ font-size: 12px; color: var(--muted); text-transform: uppercase; }}
    code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    pre {{
      max-height: 520px;
      overflow: auto;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      white-space: pre-wrap;
    }}
    .meta {{ display: grid; grid-template-columns: max-content 1fr; gap: 8px 14px; }}
    .meta dt {{ color: var(--muted); }}
    .meta dd {{ margin: 0; }}
    .gallery {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
    }}
    .artifact {{
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
    }}
    .artifact img, .artifact video {{
      display: block;
      width: 100%;
      max-height: 420px;
      object-fit: contain;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
    }}
    .empty {{ color: var(--muted); }}
    a {{ color: var(--accent); }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(run_id)}</h1>
    <nav>{nav}</nav>
  </header>
  <main>{body}</main>
</body>
</html>
"""
