from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from simulacra import cli
from simulacra.cli import main
from simulacra.k1s_preflight import K1sFinding, K1sIngressPreflight
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

    assert "Start-to-finish runtime:" in report
    assert "- Realistic runtime:" in report
    assert "- Operator touches: 0" in report
    assert "- Shell/AE commands: 0" in report
    assert "- WorkerBee actions: 1" in report
    assert "- Automation actions: 1" in report
    assert "incomplete (human_prompt, evidence, token usage)" in report


def test_record_touch_writes_human_action(tmp_path: Path) -> None:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "r1"]) == 0
    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "record-touch",
                "--run-id",
                "r1",
                "--track",
                "plain-codex",
                "--summary",
                "copied console logs into Codex",
                "--kind",
                "copy_logs",
                "--detail",
                "manual paste from terminal",
            ]
        )
        == 0
    )

    event_path = tmp_path / ".local" / "runs" / "r1" / "plain-codex" / "events.jsonl"
    events = read_events(event_path)

    assert events[-1].event_type == "human_action"
    assert events[-1].source == "human"
    assert events[-1].payload["kind"] == "copy_logs"
    assert events[-1].payload["detail"] == "manual paste from terminal"


def test_build_log_review_prompt_embeds_copied_logs(tmp_path: Path) -> None:
    log_file = tmp_path / "compose.log"
    output = tmp_path / "prompt.md"
    log_file.write_text("line one\nline two\nline three\n", encoding="utf-8")

    assert (
        main(
            [
                "build-log-review-prompt",
                "--output",
                str(output),
                "--title",
                "Plain log review",
                "--instruction",
                "Review copied logs and recommend the next action.",
                "--log-file",
                str(log_file),
                "--max-bytes-per-log",
                "12",
            ]
        )
        == 0
    )

    text = output.read_text(encoding="utf-8")

    assert "Plain log review" in text
    assert "uncurated human-provided context" in text
    assert "## Log:" in text
    assert "line one" in text
    assert "[truncated after 12 bytes" in text
    metadata = json.loads(output.with_suffix(".prompt-meta.json").read_text(encoding="utf-8"))
    assert metadata["prompt_kind"] == "log_review"
    assert metadata["copied_context_class"] == "local_logs"
    assert metadata["total_available_bytes"] == len(b"line one\nline two\nline three\n")
    assert metadata["total_embedded_bytes"] == 12
    assert metadata["truncated_source_count"] == 1


def test_build_context_review_prompt_embeds_copied_context(tmp_path: Path) -> None:
    context_file = tmp_path / "k1s-docs.txt"
    output = tmp_path / "prompt.md"
    context_file.write_text("remote cli\nserver token\napply command\n", encoding="utf-8")

    assert (
        main(
            [
                "build-context-review-prompt",
                "--output",
                str(output),
                "--title",
                "Plain k1s deploy docs",
                "--instruction",
                "Review copied docs and recommend the deploy path.",
                "--context-label",
                "Doc excerpt",
                "--context-file",
                str(context_file),
                "--max-bytes-per-file",
                "18",
            ]
        )
        == 0
    )

    text = output.read_text(encoding="utf-8")

    assert "Plain k1s deploy docs" in text
    assert "manually gathered by the operator" in text
    assert "## Doc excerpt:" in text
    assert "remote cli" in text
    assert "[truncated after 18 bytes" in text
    metadata = json.loads(output.with_suffix(".prompt-meta.json").read_text(encoding="utf-8"))
    assert metadata["prompt_kind"] == "context_review"
    assert metadata["copied_context_class"] == "k1s_docs"
    assert metadata["total_available_bytes"] == len(b"remote cli\nserver token\napply command\n")
    assert metadata["total_embedded_bytes"] == 18


def test_record_prompt_imports_prompt_metadata(tmp_path: Path) -> None:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "r1"]) == 0
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Review copied logs.\n", encoding="utf-8")
    (tmp_path / "prompt.prompt-meta.json").write_text(
        json.dumps(
            {
                "schema_version": "simulacra.prompt-meta.v1",
                "prompt_kind": "log_review",
                "copied_context_class": "local_logs",
                "total_embedded_bytes": 123,
                "total_available_bytes": 456,
                "source_count": 2,
                "truncated_source_count": 1,
                "sources": [],
            }
        )
        + "\n",
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

    events = read_events(tmp_path / ".local" / "runs" / "r1" / "plain-codex" / "events.jsonl")
    assert events[-1].payload["prompt_byte_count"] == len(b"Review copied logs.\n")
    assert events[-1].payload["prompt_metadata"]["total_embedded_bytes"] == 123


def test_run_codex_checkpoint_records_session_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "r1"]) == 0
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Checkpoint prompt.\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        assert command[:2] == ["codex", "exec"]
        assert "--ignore-rules" in command
        assert "--ignore-user-config" in command
        assert kwargs["input"] == "Checkpoint prompt.\n"
        assert kwargs["env"]["CODEX_HOME"].endswith("codex-home")
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"type":"thread.started","thread_id":"session-1"}\n'
                '{"type":"turn.started"}\n'
                '{"type":"turn.completed","usage":{"input_tokens":10}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    status = main(
        [
            "--repo-root",
            str(tmp_path),
            "run-codex-checkpoint",
            "--run-id",
            "r1",
            "--track",
            "plain-codex",
            "--checkpoint-id",
            "001",
            "--prompt-file",
            str(prompt),
            "--cwd",
            str(tmp_path),
            "--mode",
            "start",
        ]
    )

    assert status == 0
    events = read_events(tmp_path / ".local" / "runs" / "r1" / "plain-codex" / "events.jsonl")
    assert [event.event_type for event in events[-5:]] == [
        "human_prompt",
        "codex_event",
        "codex_event",
        "codex_event",
        "command",
    ]
    assert events[-1].payload["codex_invocation_mode"] == "start"
    assert events[-1].payload["codex_session_id"] == "session-1"


def test_check_k1s_dev_a_ingress_cli_reports_failure(monkeypatch, capsys) -> None:
    seen_kwargs = {}

    def fake_check(**kwargs):
        seen_kwargs.update(kwargs)
        return K1sIngressPreflight(
            ok=False,
            findings=[K1sFinding(severity="error", message="ingress unavailable")],
            controller_env={"AE_TRANSPORT_BACKEND": "nats-js"},
            core_proxy_ports_open=[],
        )

    monkeypatch.setattr(cli, "check_k1s_dev_a_ingress", fake_check)

    status = main(
        [
            "check-k1s-dev-a-ingress",
            "--probe-url",
            "https://example.test/peer",
            "--probe-body-contains",
            "Padawan",
        ]
    )

    assert status == 1
    assert seen_kwargs["probe_body_contains"] == "Padawan"
    out = capsys.readouterr().out
    assert "ingress unavailable" in out
    assert '"probe_url": "https://example.test/peer"' in out
    assert '"probe_body_contains": "Padawan"' in out


def test_check_k1s_dev_a_ingress_uses_run_scenario_defaults(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    scenario_file = tmp_path / "custom.yaml"
    scenario_file.write_text(
        """
target:
  label: CustomApp
  repo_root: ./custom-app
k1s_ingress:
  namespace: custom-ns
  controller_deployment: custom-controller
  probe_body_contains: Custom Ready
""".lstrip(),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "--scenario",
                str(scenario_file),
                "init-run",
                "--run-id",
                "r1",
            ]
        )
        == 0
    )
    seen_kwargs = {}

    def fake_check(**kwargs):
        seen_kwargs.update(kwargs)
        return K1sIngressPreflight(
            ok=True,
            findings=[],
            controller_env={"AE_TRANSPORT_BACKEND": "nats-js"},
            core_proxy_ports_open=[18081],
        )

    monkeypatch.setattr(cli, "check_k1s_dev_a_ingress", fake_check)

    status = main(
        [
            "--repo-root",
            str(tmp_path),
            "check-k1s-dev-a-ingress",
            "--run-id",
            "r1",
            "--probe-url",
            "https://custom.example.test/",
        ]
    )

    assert status == 0
    assert seen_kwargs["namespace"] == "custom-ns"
    assert seen_kwargs["controller_deployment"] == "custom-controller"
    assert seen_kwargs["probe_body_contains"] == "Custom Ready"
    out = capsys.readouterr().out
    assert '"namespace": "custom-ns"' in out
    assert '"probe_body_contains": "Custom Ready"' in out
