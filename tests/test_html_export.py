from __future__ import annotations

import json
from pathlib import Path

from simulacra.cli import main
from simulacra.html_export import ComparisonSpec, _delta_detail
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
    report = (tmp_path / ".local" / "runs" / "r1" / "report.md").read_text(encoding="utf-8")

    assert "Executive Summary" in executive
    assert "Comparative Simulation Frame" in executive
    assert "Comparative Simulation Frame" in index
    assert "Comparative Simulation Frame" in technical
    assert "supports isolated OpenAI project/API-key identity per lane" in executive
    assert "## Comparative Simulation Frame" in report
    assert "Executive Deltas" in executive
    assert "Detailed Metric Comparison" in executive
    assert "Core Metric Scorecard" in executive
    assert "Review pending" in executive
    assert "WorkerBee Δ" in executive
    assert "delta-badge" in executive
    assert 'data-theme="light"' in executive
    assert 'id="theme-toggle"' in executive
    assert "k1s-theme" in executive
    assert "simulacra:themechange" in executive
    assert "icon-sun" in executive
    assert "icon-moon" in executive
    assert "--k1s-bg: #f4f5f7" in executive
    assert 'html[data-theme="dark"]' in executive
    assert "--k1s-bg: #121212" in executive
    assert "--k1s-brand-gold: #fbc02d" in executive
    assert "static/dash-assets/page-background-tile-1024.png" in executive
    assert "static/dash-assets/page-background-3840x2160.png" in executive
    assert "Charts" in executive
    assert "Target &amp; Input Prompt" in executive
    assert "Input Prompt" in executive
    assert "Audit Status" in executive
    assert "Audit not run" in executive
    assert "Measurement Integrity" in executive
    assert "Provider Reconciliation" in executive
    assert "Not recorded" in executive
    assert "Realistic Runtime" in executive
    assert "Pre-Tax Measured Span" in executive
    assert "Manual Time Tax" in executive
    assert "Measurement completeness" in index
    assert "Start-to-finish runtime" in index
    assert "First measured event" in index
    assert "Checkpoint Idle Excluded" in index
    assert "Audit Status" in index
    assert "Target &amp; Input Prompt" in index
    assert "Target repo" in index
    assert "Simulation Settings" in index
    assert "target.feature_prompt" in index
    assert "Add Padawan/Jedi peer collaboration" in index
    assert "Evidence phases" in index
    assert "Operator Touches" in index
    assert "Captured Codex Input" in index
    assert "MCP Observation Input" in index
    assert "Estimated All-In Input" in index
    assert "not an authoritative billing reconciliation" in index
    assert "Copied Context Bytes" in index
    assert "Prompt Metadata" in index
    assert "Context Mgmt" in index
    assert "Technical Summary" in technical
    assert "Core Metric Scorecard" in technical
    assert "Audit Status" in technical
    assert "Target &amp; Input Prompt" in technical
    assert "Simulation Settings" in technical
    assert "target.repo_root" in technical
    assert "runtime_policy.plain-codex.local_container_runtime" in technical
    assert "workerbee_stage.app_host_template" in technical
    assert "Implementation Quality Note" in technical
    assert "Realistic Runtime" in technical
    assert "Observed Runtime" not in technical
    assert "Raw Event Span" in technical
    assert "Estimated All-In Input" in technical
    assert "provider-side usage/cost records" in technical
    assert "Cumulative Prompt Bytes" in technical
    assert "Prompt Metadata" in technical
    assert "Measurement Charts" in charts
    assert "Metric Deltas" in charts
    assert "delta-card" in charts
    assert "chart-panel delta-" in charts
    assert "Minutes from first measured event" in charts
    assert "Cumulative Operator Touches" in charts
    assert "Per-Turn Codex Input Tokens" in charts
    assert "Captured Codex, MCP Observation, and Provider Tokens" in charts
    assert "Estimated All-In Input" in charts
    assert "not an authoritative billing reconciliation" in charts
    assert "Cumulative Prompt and Copied Context Bytes" in charts
    assert "Final Turn Input" in charts
    assert "<canvas" in charts
    assert "assets/chart.umd.min.js" in charts
    assert "chartTheme" in charts
    assert "chart.update('none')" in charts
    assert "k1s / WorkerBee Simreport" in charts
    assert "checked podman" in timeline
    assert "jedi-peer.png" in evidence
    assert "prompt.md" in evidence
    assert "codex.jsonl" in evidence
    assert (html_dir / "assets" / "chart.umd.min.js").exists()


def test_export_html_single_lane_omits_comparison_deltas(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Implement the WorkerBee lane feature.\n", encoding="utf-8")
    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "init-run",
                "--run-id",
                "wb-only",
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
                "record-prompt",
                "--run-id",
                "wb-only",
                "--track",
                "workerbee-codex",
                "--prompt-file",
                str(prompt),
            ]
        )
        == 0
    )
    assert main(["--repo-root", str(tmp_path), "render-report", "--run-id", "wb-only"]) == 0
    assert main(["--repo-root", str(tmp_path), "export-html", "--run-id", "wb-only"]) == 0

    html_dir = tmp_path / ".local" / "runs" / "wb-only" / "html"
    executive = (html_dir / "executive.html").read_text(encoding="utf-8")
    charts = (html_dir / "charts.html").read_text(encoding="utf-8")
    report = (tmp_path / ".local" / "runs" / "wb-only" / "report.md").read_text(encoding="utf-8")

    assert "Lane Summary" in executive
    assert "standalone report for <code>workerbee-codex</code>" in executive
    assert "Comparative Simulation Frame" not in executive
    assert "Executive Deltas" not in executive
    assert "Detailed Metric Comparison" not in executive
    assert "WorkerBee Δ" not in executive
    assert "Metric Deltas" not in charts
    assert "plain-codex operator touches" not in charts
    assert "workerbee-codex operator touches" in charts
    assert "## Single-Lane Report" in report
    assert "## Comparative Simulation Frame" not in report
    assert "comparison deltas" in report


def test_export_html_comparison_frame_uses_reconciled_provider_wording(tmp_path: Path) -> None:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "r1"]) == 0
    run_root = tmp_path / ".local" / "runs" / "r1"
    for track in ("plain-codex", "workerbee-codex"):
        append_event(
            run_root / track / "events.jsonl",
            SimulationEvent(
                run_id="r1",
                track=track,  # type: ignore[arg-type]
                event_type="billing_reconciliation",
                source="openai-admin-api",
                summary=f"Reconciled OpenAI provider usage for {track}",
                payload={
                    "phase": "provider_reconciliation",
                    "provider": "openai",
                    "provider_input_tokens": 1000,
                    "provider_cached_input_tokens": 100,
                    "provider_output_tokens": 50,
                    "provider_model_requests": 1,
                    "match_basis": "captured_codex",
                },
            ),
        )

    assert main(["--repo-root", str(tmp_path), "render-report", "--run-id", "r1"]) == 0
    assert main(["--repo-root", str(tmp_path), "export-html", "--run-id", "r1"]) == 0

    html_dir = run_root / "html"
    executive = (html_dir / "executive.html").read_text(encoding="utf-8")
    report = (run_root / "report.md").read_text(encoding="utf-8")

    assert "token/cost fields are reconciled from OpenAI Admin API records" in executive
    assert "token/cost fields are reconciled from OpenAI Admin API records" in report
    assert "has not recorded provider reconciliation" not in executive


def test_delta_detail_explains_manual_time_tax_plainly() -> None:
    detail = _delta_detail(
        600,
        0,
        ComparisonSpec(
            "Manual time tax",
            lambda _metrics: "",
            lambda _metrics: 0,
            prefer="lower",
            unit="duration",
        ),
    )

    assert detail == ("WorkerBee avoided 10m 0s of manual time tax (plain 10m 0s, WorkerBee 0s)")


def test_export_html_suppresses_deltas_for_blocked_audit(tmp_path: Path) -> None:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "blocked-r1"]) == 0
    run_root = tmp_path / ".local" / "runs" / "blocked-r1"
    (run_root / "audit.json").write_text(
        json.dumps(
            {
                "accepted": False,
                "profile": "public-tech-report",
                "generated_at": "2026-06-13T00:00:00+00:00",
                "summary": {"error": 1, "warning": 0, "info": 0},
                "findings": [
                    {
                        "severity": "error",
                        "check_id": "workerbee.token_sanity_check",
                        "track": "workerbee-codex",
                        "message": "blocked for test",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert main(["--repo-root", str(tmp_path), "export-html", "--run-id", "blocked-r1"]) == 0

    html_dir = run_root / "html"
    executive = (html_dir / "executive.html").read_text(encoding="utf-8")
    charts = (html_dir / "charts.html").read_text(encoding="utf-8")

    assert "diagnostic only" in executive
    assert "Core Metric Scorecard" in executive
    assert "Blocked" in executive
    assert "blocked</span>" in executive
    assert "Percentage deltas are suppressed" in charts


def test_export_html_surfaces_custom_scenario_settings(tmp_path: Path) -> None:
    scenario_file = tmp_path / "custom.yaml"
    scenario_file.write_text(
        """
name: custom-review
target:
  label: CustomApp
  repo_root: ./custom-app
  feature_prompt: |
    Add a custom review feature.
k1s_ingress:
  namespace: custom-ns
  probe_body_contains: Custom Ready
workerbee_stage:
  manifest: manifests/custom.k1s.yaml
  env_updates:
    CUSTOM_PUBLIC_HOST: "{app_host}"
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
                "custom-r1",
            ]
        )
        == 0
    )
    assert main(["--repo-root", str(tmp_path), "export-html", "--run-id", "custom-r1"]) == 0

    html_dir = tmp_path / ".local" / "runs" / "custom-r1" / "html"
    summary = (html_dir / "index.html").read_text(encoding="utf-8")
    technical = (html_dir / "technical.html").read_text(encoding="utf-8")

    assert "CustomApp" in summary
    assert str(tmp_path / "custom-app") in summary
    assert "Add a custom review feature." in summary
    assert "k1s_ingress.namespace" in technical
    assert "custom-ns" in technical
    assert "workerbee_stage.env_updates.CUSTOM_PUBLIC_HOST" in technical


def test_export_html_and_report_surface_run_lineage(tmp_path: Path) -> None:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "derived-r1"]) == 0
    manifest_path = tmp_path / ".local" / "runs" / "derived-r1" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["lineage"] = {
        "source_run_id": "baseline-013-final-clean",
        "source_run_root": ".local/runs/baseline-013-final-clean",
        "created_by": "simctl audit review",
        "reason": "Audit classification backfill before partial rerun.",
    }
    manifest["audit_adjustments"] = [
        {
            "id": "classification.workerbee_evidence_source",
            "summary": "Reclassified evidence capture command as human initiated.",
            "evidence": "workerbee-codex/events.jsonl:18",
        }
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    assert main(["--repo-root", str(tmp_path), "render-report", "--run-id", "derived-r1"]) == 0
    assert main(["--repo-root", str(tmp_path), "export-html", "--run-id", "derived-r1"]) == 0

    report = (tmp_path / ".local" / "runs" / "derived-r1" / "report.md").read_text(encoding="utf-8")
    summary = (tmp_path / ".local" / "runs" / "derived-r1" / "html" / "index.html").read_text(
        encoding="utf-8"
    )

    assert "## Run Lineage" in report
    assert "baseline-013-final-clean" in report
    assert "Reclassified evidence capture command" in report
    assert "Run Lineage" in summary
    assert "classification.workerbee_evidence_source" in summary
    assert "Reclassified evidence capture command" in summary


def test_export_html_fills_legacy_padawan_manifest_defaults(tmp_path: Path) -> None:
    assert main(["--repo-root", str(tmp_path), "init-run", "--run-id", "legacy-r1"]) == 0
    manifest_path = tmp_path / ".local" / "runs" / "legacy-r1" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("scenario", "target_label", "target_root", "feature_prompt"):
        manifest.pop(key, None)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    assert main(["--repo-root", str(tmp_path), "export-html", "--run-id", "legacy-r1"]) == 0

    html_dir = tmp_path / ".local" / "runs" / "legacy-r1" / "html"
    summary = (html_dir / "index.html").read_text(encoding="utf-8")
    technical = (html_dir / "technical.html").read_text(encoding="utf-8")

    executive = (html_dir / "executive.html").read_text(encoding="utf-8")

    assert "built-in:padawan-peer (legacy manifest fallback)" in summary
    assert "Legacy calibration" in technical
    assert "Calibration Reference" in executive
    assert "Padawan" in summary
    assert "Add Padawan/Jedi peer collaboration" in summary
    assert "workerbee_stage.app_host_template" in technical
