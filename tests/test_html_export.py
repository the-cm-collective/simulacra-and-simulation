from __future__ import annotations

from pathlib import Path

from simulacra.cli import main
from simulacra.schema import SimulationEvent, append_event


def test_export_html_writes_summary_timeline_and_evidence_pages(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Implement the feature.\n", encoding="utf-8")
    codex_jsonl = tmp_path / "codex.jsonl"
    codex_jsonl.write_text(
        '{"type":"turn.completed","usage":{"input_tokens":12,'
        '"cached_input_tokens":4,"output_tokens":5,"reasoning_output_tokens":2}}\n',
        encoding="utf-8",
    )

    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "r1"]) == 0
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
            payload={"artifacts": [str(screenshot)]},
        ),
    )
    assert main(["--repo-root", str(tmp_path), "render-report", "--run-id", "r1"]) == 0
    assert main(["--repo-root", str(tmp_path), "export-html", "--run-id", "r1"]) == 0

    html_dir = tmp_path / ".local" / "runs" / "r1" / "html"
    index = (html_dir / "index.html").read_text(encoding="utf-8")
    timeline = (html_dir / "timeline.html").read_text(encoding="utf-8")
    evidence = (html_dir / "evidence.html").read_text(encoding="utf-8")

    assert "Measurement completeness" in index
    assert "checked podman" in timeline
    assert "jedi-peer.png" in evidence
