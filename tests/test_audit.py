from __future__ import annotations

import json
from pathlib import Path

from simulacra.audit import audit_run
from simulacra.cli import main
from simulacra.schema import SimulationEvent, append_event


def test_audit_run_accepts_complete_fixture(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)

    status = main(["--repo-root", str(tmp_path), "audit-run", "--run-id", "audit-r1"])

    assert status == 0
    audit = json.loads((run_root / "audit.json").read_text(encoding="utf-8"))
    assert audit["accepted"] is True
    assert audit["summary"]["error"] == 0
    assert (run_root / "audit.md").exists()


def test_audit_detects_duplicate_codex_transcript_ingestion(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    event_path = run_root / "plain-codex" / "events.jsonl"
    append_event(
        event_path,
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn started duplicate",
            payload={
                "raw_type": "turn.started",
                "line_no": 1,
                "source_sha256": "plain-codex-1",
            },
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(report, "codex.duplicate_event_fingerprint")


def test_audit_blocks_final_evidence_without_peer_body_gate(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    for path in (run_root / "workerbee-codex" / "commands").glob("*ingress-final*.json"):
        path.unlink()

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(report, "evidence.missing_final_peer_body_gate", track="workerbee-codex")


def test_audit_accepts_ingress_gate_filename(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    command_dir = run_root / "workerbee-codex" / "commands"
    for path in command_dir.glob("*ingress-final*.json"):
        path.unlink()
    (command_dir / "workerbee-k1s-ingress-gate.json").write_text(
        json.dumps(
            {
                "ok": True,
                "probe_url": "https://workerbee.example.test/peer",
                "probe_body_contains": "Padawan",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = audit_run(run_root)

    assert report.accepted is True
    assert not _has_finding(
        report,
        "evidence.missing_final_peer_body_gate",
        track="workerbee-codex",
    )


def test_audit_ignores_plain_codex_prose_about_docker(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    append_event(
        run_root / "plain-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="Confirm Docker usage is avoided; use podman compose only.",
            payload={"raw_type": "item.completed", "item_type": "agent_message"},
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is True
    assert not _has_finding(report, "policy.plain_docker_use", track="plain-codex")


def test_audit_flags_workerbee_host_podman_fallback(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    append_event(
        run_root / "workerbee-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="workerbee-codex",
            event_type="command",
            source="human",
            summary="fallback push with host Podman",
            payload={"command": "podman push localhost/example:dev"},
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(report, "policy.workerbee_host_podman_fallback")


def test_audit_blocks_abnormal_one_prompt_workerbee_token_usage(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    _set_workerbee_input_tokens(run_root, 52_529)

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(report, "workerbee.token_sanity_check", track="workerbee-codex")


def test_audit_allows_explicit_workerbee_token_sanity_waiver(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    _set_workerbee_input_tokens(run_root, 52_529)
    append_event(
        run_root / "workerbee-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="workerbee-codex",
            event_type="human_action",
            source="human",
            summary="waiver: workerbee_token_sanity accepted for diagnostic replay",
            payload={
                "kind": "audit_waiver",
                "audit_waivers": ["workerbee_token_sanity", "plain_core_metric_win"],
            },
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is True
    assert _has_finding(report, "workerbee.token_sanity_waived", track="workerbee-codex")
    assert _has_finding(report, "comparison.plain_core_metric_win")
    assert not _has_finding(report, "workerbee.token_sanity_check", track="workerbee-codex")


def test_audit_blocks_plain_core_metric_win(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    _set_workerbee_input_tokens(run_root, 1_000)

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(report, "comparison.plain_core_metric_win")


def test_audit_allows_explicit_plain_core_metric_waiver(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    _set_workerbee_input_tokens(run_root, 1_000)
    append_event(
        run_root / "plain-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="human_action",
            source="human",
            summary="waiver: plain_core_metric_win expected diagnostic token inversion",
            payload={
                "kind": "audit_waiver",
                "audit_waiver": "plain_core_metric_win",
            },
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is True
    assert _has_finding(report, "comparison.plain_core_metric_win")


def test_audit_blocks_environment_repair_noise(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    append_event(
        run_root / "workerbee-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="workerbee-codex",
            event_type="command",
            source="simctl",
            summary="patch WorkerBee remote service ports after empty-body route finding",
            payload={
                "command": "patch WorkerBee stage service ports after empty-body route finding",
                "duration_seconds": 12,
            },
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(report, "environment.repair_noise", track="workerbee-codex")
    assert report.runtime["workerbee-codex"]["environment_repair_events"] == 1
    assert report.runtime["workerbee-codex"]["environment_repair_seconds"] == 12


def test_audit_allows_lane_scoped_service_port_patch(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    append_event(
        run_root / "workerbee-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="workerbee-codex",
            event_type="workerbee_tool",
            source="workerbee",
            summary="patch WorkerBee local stage hosts and lane service ports",
            payload={
                "command": "simctl patch-workerbee-stage --value spec.service.port=18878",
                "duration_seconds": 1,
            },
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is True
    assert not _has_finding(report, "environment.repair_noise", track="workerbee-codex")
    assert report.runtime["workerbee-codex"]["environment_repair_events"] == 0


def test_audit_blocks_codex_checkpoint_without_isolation_flags(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    append_event(
        run_root / "plain-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="command",
            source="human",
            summary="submitted plain checkpoint to Codex CLI",
            payload={"command": "codex exec --json -C ../padawan --sandbox read-only < prompt.md"},
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(report, "codex.missing_isolation_flags", track="plain-codex")


def test_audit_blocks_tools_after_no_tool_checkpoint(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    append_event(
        run_root / "workerbee-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="workerbee-codex",
            event_type="human_prompt",
            source="human",
            summary="no-tool checkpoint",
            payload={"prompt": "Do not run commands, read files, or use tools."},
        ),
    )
    append_event(
        run_root / "workerbee-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="workerbee-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="command started",
            payload={
                "raw_type": "item.started",
                "item_type": "command_execution",
                "command": "sed -n '1,20p' README.md",
            },
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(report, "codex.no_tool_checkpoint_violation", track="workerbee-codex")


def test_audit_blocks_plain_run_with_insufficient_copied_context(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    event_path = run_root / "plain-codex" / "events.jsonl"
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    for event in events:
        metadata = event.get("payload", {}).get("prompt_metadata")
        if isinstance(metadata, dict) and metadata.get("copied_context_class") == "local_logs":
            metadata["total_embedded_bytes"] = 100
            metadata["total_available_bytes"] = 50_000
    event_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(
        report,
        "plain_realism.insufficient_local_log_context",
        track="plain-codex",
    )


def test_audit_blocks_plain_failed_command_without_repair_prompt(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    append_event(
        run_root / "plain-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="ae_command",
            source="ae",
            summary="failed remote deploy",
            payload={"command": "ae apply -f stage", "exit_code": 1},
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(
        report,
        "plain_realism.missing_failure_repair_prompt",
        track="plain-codex",
    )


def test_audit_allows_plain_transient_readiness_wait_recovery(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    event_path = run_root / "plain-codex" / "events.jsonl"
    append_event(
        event_path,
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="ae_command",
            source="ae",
            summary="wait for plain k1s-dev-a workload readiness",
            payload={
                "command": "ae status --namespace sim-baseline --watch 2 --timeout 120",
                "exit_code": 1,
            },
        ),
    )
    append_event(
        event_path,
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="human_action",
            source="human",
            summary="human waits for k1s-dev-a status convergence after tokened apply",
            payload={"kind": "manual_wait", "duration_seconds": 60},
        ),
    )
    append_event(
        event_path,
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="ae_command",
            source="ae",
            summary="verify plain k1s-dev-a workload readiness after convergence",
            payload={
                "command": "ae status --namespace sim-baseline --wide --events",
                "exit_code": 0,
            },
        ),
    )
    _evidence(run_root, "plain-codex", "k1s-dev-a")

    report = audit_run(run_root)

    assert report.accepted is True
    assert not _has_finding(
        report,
        "plain_realism.missing_failure_repair_prompt",
        track="plain-codex",
    )


def test_audit_blocks_plain_session_reset_without_context_management(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    append_event(
        run_root / "plain-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="command",
            source="human",
            summary="started a fresh Codex checkpoint without reset note",
            payload={
                "command": (
                    "codex exec --json --ignore-rules --ignore-user-config "
                    "-C ../padawan --sandbox read-only -"
                ),
                "codex_invocation_mode": "start",
                "codex_session_id": "plain-session-2",
                "checkpoint_id": "005",
                "exit_code": 0,
            },
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(report, "codex.session_model_violation", track="plain-codex")


def test_audit_blocks_plain_cert_tax_without_local_https(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    append_event(
        run_root / "plain-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="human_action",
            source="human",
            summary="manual certificate setup",
            payload={"kind": "cert_setup", "duration_seconds": 180},
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(report, "plain_realism.cert_tax_without_https", track="plain-codex")


def test_audit_blocks_missing_context_management_after_large_turn(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    event_path = run_root / "plain-codex" / "events.jsonl"
    append_event(
        event_path,
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="codex_event",
            source="codex-jsonl",
            summary="large turn usage",
            payload={"usage": {"input_tokens": 45_000}},
        ),
    )
    append_event(
        event_path,
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="human_prompt",
            source="human",
            summary="next checkpoint without context management",
            payload={"prompt": "Next checkpoint."},
        ),
    )

    report = audit_run(run_root)

    assert report.accepted is False
    assert _has_finding(
        report,
        "plain_realism.missing_context_management_touch",
        track="plain-codex",
    )


def test_audit_warns_for_legacy_padawan_manifest_without_blocking(tmp_path: Path) -> None:
    run_root = _complete_run(tmp_path)
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("scenario", "target_label", "target_root", "feature_prompt"):
        manifest.pop(key, None)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    report = audit_run(run_root)

    assert report.accepted is True
    assert _has_finding(report, "manifest.legacy_scenario_fallback")


def _complete_run(tmp_path: Path) -> Path:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "audit-r1"]) == 0
    run_root = tmp_path / ".local" / "runs" / "audit-r1"

    _prompt_and_turn(
        run_root,
        "plain-codex",
        1,
        "Plain checkpoint 1 implementation checklist.",
        input_tokens=100,
        codex_mode="start",
    )
    _prompt_and_turn(
        run_root,
        "plain-codex",
        2,
        "Plain checkpoint 2 copied Podman logs with manually copied log context.",
        input_tokens=120,
        codex_mode="resume",
        prompt_metadata=_prompt_metadata(
            "local_logs", embedded=30_000, available=32_000, sources=4
        ),
    )
    _prompt_and_turn(
        run_root,
        "plain-codex",
        3,
        "Plain checkpoint 3 k1s docs excerpt for deploy.",
        input_tokens=140,
        codex_mode="resume",
        prompt_metadata=_prompt_metadata("k1s_docs", embedded=36_000, available=38_000, sources=3),
    )
    _prompt_and_turn(
        run_root,
        "plain-codex",
        4,
        "Plain checkpoint 4 final repair and evidence report.",
        input_tokens=160,
        codex_mode="resume",
    )
    append_event(
        run_root / "plain-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="command",
            source="human",
            summary="ran podman compose validation",
            payload={
                "command": "podman compose up",
                "started_at": "2026-06-13T00:00:00+00:00",
                "exit_code": 0,
            },
        ),
    )
    append_event(
        run_root / "plain-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="plain-codex",
            event_type="human_action",
            source="human",
            summary="copied raw Podman validation logs into Codex",
            payload={"kind": "copy_logs", "duration_seconds": 60},
        ),
    )

    _prompt_and_turn(
        run_root,
        "workerbee-codex",
        1,
        "WorkerBee checkpoint 1 validation checklist.",
        input_tokens=90,
    )
    append_event(
        run_root / "workerbee-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="workerbee-codex",
            event_type="workerbee_tool",
            source="workerbee",
            summary="checked WorkerBee capabilities runtime.selected containerd",
            payload={
                "command": "workerbee_v1_capabilities",
                "started_at": "2026-06-13T00:00:00+00:00",
            },
        ),
    )
    append_event(
        run_root / "workerbee-codex" / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track="workerbee-codex",
            event_type="workerbee_tool",
            source="workerbee",
            summary="inspect WorkerBee profile status",
            payload={"command": "workerbee_v1_profile_status"},
        ),
    )

    for track in ("plain-codex", "workerbee-codex"):
        _evidence(run_root, track, "local")
        _evidence(run_root, track, "k1s-dev-a")
        _final_gate(run_root, track)

    return run_root


def _prompt_and_turn(
    run_root: Path,
    track: str,
    checkpoint: int,
    prompt: str,
    *,
    input_tokens: int,
    codex_mode: str | None = None,
    prompt_metadata: dict[str, object] | None = None,
) -> None:
    prompt_file = run_root / track / "prompts" / f"{checkpoint:03d}.md"
    prompt_file.write_text(prompt + "\n", encoding="utf-8")
    event_path = run_root / track / "events.jsonl"
    append_event(
        event_path,
        SimulationEvent(
            run_id="audit-r1",
            track=track,  # type: ignore[arg-type]
            event_type="human_prompt",
            source="human",
            summary=prompt,
            payload={
                "prompt_file": str(prompt_file),
                "prompt": prompt,
                "prompt_char_count": len(prompt),
                "prompt_byte_count": len(prompt.encode("utf-8")),
                **({"prompt_metadata": prompt_metadata} if prompt_metadata else {}),
            },
        ),
    )
    source_sha = f"{track}-{checkpoint}"
    append_event(
        event_path,
        SimulationEvent(
            run_id="audit-r1",
            track=track,  # type: ignore[arg-type]
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn started",
            payload={"raw_type": "turn.started", "line_no": 1, "source_sha256": source_sha},
        ),
    )
    append_event(
        event_path,
        SimulationEvent(
            run_id="audit-r1",
            track=track,  # type: ignore[arg-type]
            event_type="codex_event",
            source="codex-jsonl",
            summary="turn completed",
            payload={
                "raw_type": "turn.completed",
                "line_no": 2,
                "source_sha256": source_sha,
                "usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": 10,
                    "output_tokens": 5,
                    "reasoning_output_tokens": 1,
                },
            },
        ),
    )
    if codex_mode:
        append_event(
            event_path,
            SimulationEvent(
                run_id="audit-r1",
                track=track,  # type: ignore[arg-type]
                event_type="command",
                source="human",
                summary=f"submitted {track} checkpoint {checkpoint} to Codex CLI",
                payload={
                    "command": _codex_command(codex_mode),
                    "checkpoint_id": f"{checkpoint:03d}",
                    "codex_invocation_mode": codex_mode,
                    "codex_session_id": "plain-session-1",
                    "exit_code": 0,
                },
            ),
        )


def _codex_command(mode: str) -> str:
    if mode == "resume":
        return "codex exec resume --json --ignore-rules --ignore-user-config plain-session-1 -"
    return (
        "codex exec --json --ignore-rules --ignore-user-config -C ../padawan --sandbox read-only -"
    )


def _prompt_metadata(
    copied_context_class: str,
    *,
    embedded: int,
    available: int,
    sources: int,
) -> dict[str, object]:
    return {
        "schema_version": "simulacra.prompt-meta.v1",
        "prompt_kind": "log_review",
        "copied_context_class": copied_context_class,
        "source_count": sources,
        "total_available_bytes": available,
        "total_embedded_bytes": embedded,
        "truncated_source_count": 0,
        "sources": [
            {
                "path": f"source-{index}.log",
                "exists": True,
                "available_bytes": available // sources,
                "embedded_bytes": embedded // sources,
                "truncated": False,
            }
            for index in range(sources)
        ],
    }


def _evidence(run_root: Path, track: str, phase: str) -> None:
    root = run_root / track / "evidence" / "screenshots" / phase / "peer-flow"
    root.mkdir(parents=True, exist_ok=True)
    jedi = root / "jedi-peer.png"
    padawan = root / "padawan-peer.png"
    jedi.write_bytes(b"png")
    padawan.write_bytes(b"png")
    summary = root / "peer-flow-summary.json"
    summary.write_text(
        json.dumps(
            {
                "phase": phase,
                "data_channel": "open",
                "screenshots": [str(jedi), str(padawan)],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    append_event(
        run_root / track / "events.jsonl",
        SimulationEvent(
            run_id="audit-r1",
            track=track,  # type: ignore[arg-type]
            event_type="evidence",
            source="playwright",
            summary=f"{phase} evidence",
            payload={
                "phase": phase,
                "artifacts": [str(jedi), str(padawan)],
                "summary_path": str(summary),
            },
        ),
    )


def _final_gate(run_root: Path, track: str) -> None:
    command_dir = run_root / track / "commands"
    command_dir.mkdir(parents=True, exist_ok=True)
    (command_dir / "k1s-dev-a-ingress-final.json").write_text(
        json.dumps(
            {
                "ok": True,
                "probe_url": f"https://{track}.example.test/peer",
                "probe_body_contains": "Padawan",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _set_workerbee_input_tokens(run_root: Path, input_tokens: int) -> None:
    event_path = run_root / "workerbee-codex" / "events.jsonl"
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    for event in events:
        usage = event.get("payload", {}).get("usage")
        if isinstance(usage, dict):
            usage["input_tokens"] = input_tokens
    event_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def _has_finding(report, check_id: str, *, track: str | None = None) -> bool:
    return any(
        finding.check_id == check_id and (track is None or finding.track == track)
        for finding in report.findings
    )
