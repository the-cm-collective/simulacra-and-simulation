from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from simulacra import cli
from simulacra.cli import main
from simulacra.k1s_preflight import K1sFinding, K1sIngressPreflight
from simulacra.schema import SimulationEvent, append_event, read_events


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


def test_record_command_can_attach_workerbee_artifact_metadata(tmp_path: Path) -> None:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "r1"]) == 0
    artifact = tmp_path / "status.json"
    artifact.write_text('{"ok": true}\n', encoding="utf-8")

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
                "checked WorkerBee profile status",
                "--command",
                "workerbee_v1_profile_status",
                "--artifact-file",
                str(artifact),
                "--artifact-class",
                "targeted_status",
            ]
        )
        == 0
    )

    events = read_events(tmp_path / ".local" / "runs" / "r1" / "workerbee-codex" / "events.jsonl")
    payload = events[-1].payload

    assert payload["artifact_files"] == [str(artifact)]
    assert payload["artifact_class"] == "targeted_status"
    assert payload["mcp_visible"] is True


def test_measure_mcp_artifacts_appends_idempotent_observation_events(tmp_path: Path) -> None:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "r1"]) == 0
    commands_dir = tmp_path / ".local" / "runs" / "r1" / "workerbee-codex" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    artifact = commands_dir / "profile-status.json"
    artifact.write_text('{"status":"ready","pods":["padawan"]}\n', encoding="utf-8")

    command = [
        "--repo-root",
        str(tmp_path),
        "measure-mcp-artifacts",
        "--run-id",
        "r1",
        "--track",
        "workerbee-codex",
        "--commands-dir",
        str(commands_dir),
        "--artifact-class",
        "targeted_status",
    ]

    assert main(command) == 0
    assert main(command) == 0

    events = read_events(tmp_path / ".local" / "runs" / "r1" / "workerbee-codex" / "events.jsonl")
    observations = [event for event in events if event.event_type == "mcp_observation"]

    assert len(observations) == 1
    assert observations[0].payload["artifact_file"] == (
        "workerbee-codex/commands/profile-status.json"
    )
    assert observations[0].payload["artifact_class"] == "targeted_status"
    assert observations[0].payload["mcp_visible"] is True
    assert observations[0].payload["included_in_codex_usage"] is False
    assert observations[0].payload["byte_count"] == artifact.stat().st_size
    assert observations[0].payload["token_count"] > 0
    assert observations[0].payload["generated_by"] == "measure-mcp-artifacts"


def test_prepare_openai_api_auth_uses_env_without_recording_key(
    tmp_path: Path, monkeypatch
) -> None:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "r1"]) == 0
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        "#!/bin/sh\n"
        'mkdir -p "$CODEX_HOME"\n'
        "bytes=$(wc -c | tr -d ' ')\n"
        'printf \'%s\' "$bytes" > "$CODEX_HOME/key-bytes"\n',
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    monkeypatch.setenv("SIM_TEST_OPENAI_KEY", "test-key-value")

    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "prepare-openai-api-auth",
                "--run-id",
                "r1",
                "--track",
                "plain-codex",
                "--api-key-env",
                "SIM_TEST_OPENAI_KEY",
                "--codex-bin",
                str(fake_codex),
            ]
        )
        == 0
    )

    event_path = tmp_path / ".local" / "runs" / "r1" / "plain-codex" / "events.jsonl"
    events = read_events(event_path)
    payload = events[-1].payload
    assert events[-1].event_type == "billing_reconciliation"
    assert payload["phase"] == "auth_prepare"
    assert payload["api_key_env"] == "SIM_TEST_OPENAI_KEY"
    assert "test-key-value" not in event_path.read_text(encoding="utf-8")
    auth_home = tmp_path / ".local" / "auth" / "codex-api" / "r1" / "plain-codex"
    assert (auth_home / "key-bytes").read_text(encoding="utf-8") == str(len("test-key-value"))


def test_reconcile_openai_usage_cli_writes_events_and_manifest(tmp_path: Path) -> None:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "r1"]) == 0
    run_root = tmp_path / ".local" / "runs" / "r1"
    _append_usage(run_root, "plain-codex", 1000)
    _append_usage(run_root, "workerbee-codex", 800)
    usage_json = tmp_path / "usage.json"
    costs_json = tmp_path / "costs.json"
    usage_json.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "results": [
                            {
                                "project_id": "proj_plain",
                                "input_tokens": 1000,
                                "input_cached_tokens": 100,
                                "output_tokens": 50,
                                "num_model_requests": 1,
                            },
                            {
                                "project_id": "proj_wb",
                                "input_tokens": 800,
                                "input_cached_tokens": 80,
                                "output_tokens": 40,
                                "num_model_requests": 1,
                            },
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    costs_json.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "results": [
                            {
                                "project_id": "proj_plain",
                                "line_item": "responses",
                                "amount": {"value": 0.01, "currency": "usd"},
                            },
                            {
                                "project_id": "proj_wb",
                                "line_item": "responses",
                                "amount": {"value": 0.008, "currency": "usd"},
                            },
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "reconcile-openai-usage",
                "--run-id",
                "r1",
                "--plain-project-id",
                "proj_plain",
                "--workerbee-project-id",
                "proj_wb",
                "--usage-json",
                str(usage_json),
                "--costs-json",
                str(costs_json),
            ]
        )
        == 0
    )

    plain_events = read_events(run_root / "plain-codex" / "events.jsonl")
    billing_events = [
        event
        for event in plain_events
        if event.event_type == "billing_reconciliation"
        and event.payload.get("phase") == "provider_reconciliation"
    ]
    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert billing_events
    assert billing_events[-1].payload["provider_input_tokens"] == 1000
    assert billing_events[-1].payload["match_basis"] == "captured_codex"
    assert (run_root / "billing" / "openai" / "usage-completions.raw.json").exists()
    assert manifest["billing_reconciliation"]["required"] is True
    assert manifest["billing_reconciliation"]["tracks"]["plain-codex"]["project_id"] == (
        "proj_plain"
    )
    assert main(["--repo-root", str(tmp_path), "render-report", "--run-id", "r1"]) == 0
    report = (run_root / "report.md").read_text(encoding="utf-8")
    assert "## Provider Reconciliation" in report
    assert "Provider-reconciled values" in report
    assert "Provider input tokens: 1000" in report


def test_reconcile_openai_usage_cli_accepts_single_active_track_mapping(tmp_path: Path) -> None:
    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "init-run",
                "--run-id",
                "r1",
                "--track",
                "workerbee-codex",
            ]
        )
        == 0
    )
    run_root = tmp_path / ".local" / "runs" / "r1"
    _append_usage(run_root, "workerbee-codex", 800)
    usage_json = tmp_path / "usage.json"
    costs_json = tmp_path / "costs.json"
    usage_json.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "results": [
                            {
                                "project_id": "proj_wb",
                                "input_tokens": 800,
                                "input_cached_tokens": 80,
                                "output_tokens": 40,
                                "num_model_requests": 1,
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    costs_json.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "results": [
                            {
                                "project_id": "proj_wb",
                                "line_item": "responses",
                                "amount": {"value": 0.008, "currency": "usd"},
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "reconcile-openai-usage",
                "--run-id",
                "r1",
                "--track-project-id",
                "workerbee-codex=proj_wb",
                "--usage-json",
                str(usage_json),
                "--costs-json",
                str(costs_json),
            ]
        )
        == 0
    )

    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert sorted(manifest["billing_reconciliation"]["tracks"]) == ["workerbee-codex"]
    assert not (run_root / "plain-codex" / "events.jsonl").exists()
    events = read_events(run_root / "workerbee-codex" / "events.jsonl")
    billing = [
        event
        for event in events
        if event.event_type == "billing_reconciliation"
        and event.payload.get("phase") == "provider_reconciliation"
    ]
    assert billing[-1].payload["provider_input_tokens"] == 800


def test_workerbee_lane_wrapper_records_high_level_tool_event(tmp_path: Path) -> None:
    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "init-run",
                "--run-id",
                "r1",
                "--track",
                "workerbee-codex",
            ]
        )
        == 0
    )

    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "workerbee-lane",
                "--run-id",
                "r1",
                "--project",
                "sim-workerbee",
                "prepare",
            ]
        )
        == 0
    )

    events = read_events(tmp_path / ".local" / "runs" / "r1" / "workerbee-codex" / "events.jsonl")
    assert events[-1].event_type == "workerbee_tool"
    assert events[-1].source == "workerbee"
    assert events[-1].payload["wrapper_action"] == "prepare"
    assert events[-1].payload["project"] == "sim-workerbee"
    assert "workerbee_v1_capabilities" in events[-1].payload["recommended_workerbee_tools"]


def test_workerbee_lane_run_records_cleanup_step(tmp_path: Path) -> None:
    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "init-run",
                "--run-id",
                "r1",
                "--track",
                "workerbee-codex",
            ]
        )
        == 0
    )

    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "workerbee-lane",
                "--run-id",
                "r1",
                "--project",
                "sim-workerbee",
                "run",
            ]
        )
        == 0
    )

    events = read_events(tmp_path / ".local" / "runs" / "r1" / "workerbee-codex" / "events.jsonl")
    actions = [
        event.payload["wrapper_action"]
        for event in events
        if event.payload.get("wrapper_action")
    ]
    assert actions == ["prepare", "deploy-local", "probe", "collect-evidence", "cleanup"]
    assert "simctl cleanup-k1s-dev-a" in events[-1].payload["recommended_workerbee_tools"]


def test_cleanup_k1s_dev_a_cli_uses_scenario_ports(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    scenario_file = tmp_path / "custom.yaml"
    scenario_file.write_text(
        """
preflight:
  local_ports: [8000]
k1s_ingress:
  namespace: custom-ns
  remote_service_ports:
    workerbee-codex:
      padawan: 28000
workerbee_stage:
  local_profile_service_ports:
    padawan: 18000
""".lstrip(),
        encoding="utf-8",
    )
    seen_kwargs = {}

    def fake_cleanup(**kwargs):
        seen_kwargs.update(kwargs)
        return {
            "ok": True,
            "execute": kwargs["execute"],
            "selected": {},
            "actions": [],
            "after": {"runtime_check": {"ok": True}},
            "findings": [],
        }

    monkeypatch.setattr(cli, "cleanup_k1s_dev_a", fake_cleanup)

    status = main(
        [
            "--repo-root",
            str(tmp_path),
            "--scenario",
            str(scenario_file),
            "cleanup-k1s-dev-a",
            "--run-id",
            "r1",
            "--execute",
            "--ae-server",
            "http://127.0.0.1:49108",
            "--ae-token-env",
            "SIM_AE_TOKEN",
            "--no-sudo",
        ]
    )

    assert status == 0
    assert seen_kwargs["execute"] is True
    assert seen_kwargs["run_id"] == "r1"
    assert seen_kwargs["kubectl_namespace"] == "custom-ns"
    assert {8000, 18000, 28000}.issubset(set(seen_kwargs["reserved_ports"]))
    assert seen_kwargs["use_sudo"] is False
    assert '"ok": true' in capsys.readouterr().out


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


def _append_usage(run_root: Path, track: str, input_tokens: int) -> None:
    append_event(
        run_root / track / "events.jsonl",
        SimulationEvent(
            run_id="r1",
            track=track,  # type: ignore[arg-type]
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn completed",
            payload={
                "raw_type": "turn.completed",
                "usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": 0,
                    "output_tokens": 1,
                    "reasoning_output_tokens": 0,
                },
            },
            timestamp="2026-06-14T00:00:00+00:00",
        ),
    )
