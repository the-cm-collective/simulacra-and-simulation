from __future__ import annotations

from pathlib import Path

from simulacra.cli import main
from simulacra.schema import read_events


def test_record_command_counts_workerbee_tool_in_report(tmp_path: Path) -> None:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "r1"]) == 0
    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "record-command",
                "--run-id",
                "r1",
                "--track",
                "workerbee-codex",
                "--event-type",
                "workerbee_tool",
                "--source",
                "workerbee",
                "--summary",
                "checked WorkerBee capabilities",
                "--command",
                "workerbee_v1_capabilities",
            ]
        )
        == 0
    )

    event_path = tmp_path / ".local" / "runs" / "r1" / "workerbee-codex" / "events.jsonl"
    events = read_events(event_path)

    assert events[-1].event_type == "workerbee_tool"
    assert events[-1].payload["command"] == "workerbee_v1_capabilities"

    assert main(["--repo-root", str(tmp_path), "render-report", "--run-id", "r1"]) == 0
    report = (tmp_path / ".local" / "runs" / "r1" / "report.md").read_text(encoding="utf-8")

    assert "- Commands: 1" in report
    assert "- WorkerBee actions: 1" in report
    assert "incomplete (human_prompt, evidence, token usage)" in report
