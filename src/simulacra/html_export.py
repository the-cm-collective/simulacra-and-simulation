from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import quote

from .codex_events import aggregate_usage
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
    report_path = run_root / "report.md"
    pages = [
        _write(
            output / "index.html",
            _index_page(run_root, output, manifest, events_by_track, report_path),
        ),
        _write(output / "timeline.html", _timeline_page(run_root, output, events_by_track)),
        _write(output / "evidence.html", _evidence_page(run_root, output, events_by_track)),
    ]
    return HtmlExport(output_dir=output, pages=pages)


def _index_page(
    run_root: Path,
    output_dir: Path,
    manifest: dict[str, object],
    events_by_track: dict[str, list[SimulationEvent]],
    report_path: Path,
) -> str:
    rows = []
    for track, events in events_by_track.items():
        metrics = _track_metrics(events)
        rows.append(
            "<tr>"
            f"<th>{escape(track)}</th>"
            f"<td>{metrics['events']}</td>"
            f"<td>{metrics['prompts']}</td>"
            f"<td>{metrics['commands']}</td>"
            f"<td>{metrics['workerbee_actions']}</td>"
            f"<td>{metrics['evidence']}</td>"
            f"<td>{metrics['violations']}</td>"
            f"<td>{metrics['input_tokens']}</td>"
            f"<td>{metrics['output_tokens']}</td>"
            f"<td>{escape(metrics['completeness'])}</td>"
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
</section>
<section class="panel">
  <h2>Track Metrics</h2>
  <table>
    <thead>
      <tr>
        <th>Track</th><th>Events</th><th>Prompts</th><th>Commands</th>
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


def _evidence_page(
    run_root: Path,
    output_dir: Path,
    events_by_track: dict[str, list[SimulationEvent]],
) -> str:
    sections = []
    for track, events in events_by_track.items():
        artifacts = _collect_artifacts(run_root, track, events)
        cards = [_artifact_card(artifact, output_dir) for artifact in artifacts]
        if not cards:
            cards = ['<p class="empty">No evidence artifacts found.</p>']
        sections.append(
            f"""
<section class="panel">
  <h2>{escape(track)}</h2>
  <div class="gallery">{"".join(cards)}</div>
</section>
"""
        )
    return _page(run_root.name, "Evidence", "".join(sections))


def _track_metrics(events: list[SimulationEvent]) -> dict[str, str | int]:
    prompts = [event for event in events if event.event_type == "human_prompt"]
    commands = [
        event for event in events if event.event_type in {"command", "ae_command", "workerbee_tool"}
    ]
    workerbee_actions = [event for event in events if event.event_type == "workerbee_tool"]
    evidence = [event for event in events if event.event_type == "evidence"]
    violations = [event for event in events if event.event_type == "protocol_violation"]
    usage = aggregate_usage(events)
    missing = []
    if not prompts:
        missing.append("human_prompt")
    if not commands:
        missing.append("command/tool")
    if not evidence:
        missing.append("evidence")
    if not any(usage.values()):
        missing.append("token usage")
    return {
        "events": len(events),
        "prompts": len(prompts),
        "commands": len(commands),
        "workerbee_actions": len(workerbee_actions),
        "evidence": len(evidence),
        "violations": len(violations),
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "completeness": "complete" if not missing else f"incomplete ({', '.join(missing)})",
    }


def _collect_artifacts(run_root: Path, track: str, events: Iterable[SimulationEvent]) -> list[Path]:
    seen: set[Path] = set()
    artifacts: list[Path] = []
    evidence_root = run_root / track / "evidence"
    if evidence_root.exists():
        for path in sorted(evidence_root.rglob("*")):
            if path.is_file() and _is_reviewable(path):
                _append_artifact(artifacts, seen, path)
    for event in events:
        if event.event_type != "evidence":
            continue
        for value in _payload_paths(event.payload):
            path = Path(value)
            if not path.is_absolute():
                path = run_root / track / value
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
            ("Summary", "index.html"),
            ("Timeline", "timeline.html"),
            ("Evidence", "evidence.html"),
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
