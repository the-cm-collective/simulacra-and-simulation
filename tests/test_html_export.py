from __future__ import annotations

from pathlib import Path

from simulacra.cli import main
from simulacra.schema import SimulationEvent, append_event


def test_export_html_writes_summary_timeline_and_evidence_pages(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Implement the feature.\n", encoding="utf-8")
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "r1"]) == 0
    codex_jsonl = tmp_path / ".local" / "runs" / "r1" / "plain-codex" / "codex" / "codex.jsonl"
    codex_jsonl.write_text(
        '{"type":"turn.completed","usage":{"input_tokens":12,'
        '"cached_input_tokens":4,"output_tokens":5,"reasoning_output_tokens":2}}\n',
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "record-prompt",
                "--run-id",
                "r1",
                "--track",
                "plain-codex",
                "--prompt-file",
                str(prompt),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "record-command",
                "--run-id",
                "r1",
                "--track",
                "plain-codex",
                "--event-type",
                "command",
                "--source",
                "human",
                "--summary",
                "checked podman",
                "--command",
                "podman version",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "ingest-codex",
                "--run-id",
                "r1",
                "--track",
                "plain-codex",
                "--jsonl",
                str(codex_jsonl),
            ]
        )
        == 0
    )

    screenshot = (
        tmp_path
        / ".local"
        / "runs"
        / "r1"
        / "plain-codex"
        / "evidence"
        / "screenshots"
        / "peer-flow"
        / "jedi-peer.png"
    )
    screenshot.parent.mkdir(parents=True)
    screenshot.write_bytes(b"not-a-real-png")
    append_event(
        tmp_path / ".local" / "runs" / "r1" / "plain-codex" / "events.jsonl",
        SimulationEvent(
            run_id="r1",
            track="plain-codex",
            event_type="evidence",
            source="test",
            summary="captured screenshot",
            payload={"artifacts": [str(screenshot)], "phase": "local"},
        ),
    )
    assert main(["--repo-root", str(tmp_path), "render-report", "--run-id", "r1"]) == 0
    assert main(["--repo-root", str(tmp_path), "export-html", "--run-id", "r1"]) == 0

    html_dir = tmp_path / ".local" / "runs" / "r1" / "html"
    executive = (html_dir / "executive.html").read_text(encoding="utf-8")
    index = (html_dir / "index.html").read_text(encoding="utf-8")
    technical = (html_dir / "technical.html").read_text(encoding="utf-8")
    charts = (html_dir / "charts.html").read_text(encoding="utf-8")
    timeline = (html_dir / "timeline.html").read_text(encoding="utf-8")
    evidence = (html_dir / "evidence.html").read_text(encoding="utf-8")

    assert "Executive Summary" in executive
    assert "Delta Snapshot" in executive
    assert "WorkerBee Δ" in executive
    assert "delta-badge" in executive
    assert 'data-theme="light"' in executive
    assert "--k1s-bg: #f4f5f7" in executive
    assert "--k1s-brand-gold: #fbc02d" in executive
    assert "static/dash-assets/page-background-tile-1024.png" in executive
    assert "Charts" in executive
    assert "Measurement completeness" in index
    assert "Start-to-finish runtime" in index
    assert "Evidence phases" in index
    assert "Operator Touches" in index
    assert "Technical Summary" in technical
    assert "Implementation Quality Note" in technical
    assert "Measurement Charts" in charts
    assert "Percentage Deltas" in charts
    assert "delta-card" in charts
    assert "chart-panel delta-" in charts
    assert "Cumulative Operator Touches" in charts
    assert "Per-Turn Codex Input Tokens" in charts
    assert "Cumulative Billed Token Usage" in charts
    assert "Final Turn Input" in charts
    assert "<canvas" in charts
    assert "assets/chart.umd.min.js" in charts
    assert "k1s / WorkerBee Simreport" in charts
    assert "checked podman" in timeline
    assert "jedi-peer.png" in evidence
    assert "prompt.md" in evidence
    assert "codex.jsonl" in evidence
    assert (html_dir / "assets" / "chart.umd.min.js").exists()
