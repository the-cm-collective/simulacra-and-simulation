from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .audit import write_audit_report
from .caddy_preflight import check_workerbee_caddy_routes
from .codex_events import normalize_codex_jsonl
from .config import default_paths
from .context_prompt import build_context_review_prompt
from .html_export import export_run_html
from .k1s_cleanup import DEFAULT_AE_SERVER, DEFAULT_WORKERBEE_STATE_ROOT, cleanup_k1s_dev_a
from .k1s_preflight import check_k1s_dev_a_ingress
from .k1s_runtime_preflight import check_k1s_runtime_clean, scenario_reserved_ports
from .log_prompt import build_log_review_prompt
from .mcp_tokens import measure_artifact_tokens
from .openai_billing import (
    billing_event_payload,
    normalized_reconciliation,
    prepare_codex_api_auth,
    reconcile_openai_usage,
)
from .preflight import run_preflight
from .prompt_meta import COPIED_CONTEXT_CLASSES, read_prompt_metadata
from .report import render_run_report
from .runs import TRACKS, active_tracks_for_run, init_run, normalize_tracks
from .scenario import Scenario, load_run_scenario, load_scenario
from .schema import SimulationEvent, Track, append_event, read_events, utc_now_iso
from .workerbee_stage import patch_stage

TRACK_CHOICES = list(TRACKS)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = (args.repo_root or Path.cwd()).resolve()
    scenario = load_scenario(repo_root, args.scenario, args.scenario_override)
    paths = default_paths(args.repo_root, scenario=scenario)
    if args.subcommand == "preflight":
        run_paths, run_scenario = _resolve_run_context(paths, scenario, args.run_id)
        return _cmd_preflight(run_paths, run_scenario)
    if args.subcommand == "check-workerbee-caddy":
        return _cmd_check_workerbee_caddy(args)
    if args.subcommand == "check-k1s-dev-a-ingress":
        _run_paths, run_scenario = _resolve_run_context(paths, scenario, args.run_id)
        return _cmd_check_k1s_dev_a_ingress(args, run_scenario)
    if args.subcommand == "check-k1s-runtime-clean":
        _run_paths, run_scenario = _resolve_run_context(paths, scenario, args.run_id)
        return _cmd_check_k1s_runtime_clean(args, run_scenario)
    if args.subcommand == "cleanup-k1s-dev-a":
        _run_paths, run_scenario = _resolve_run_context(paths, scenario, args.run_id)
        return _cmd_cleanup_k1s_dev_a(args, run_scenario)
    if args.subcommand == "init-run":
        init_run(paths, args.run_id, scenario=scenario, tracks=args.track)
        print(paths.runs_dir / args.run_id)
        return 0
    if args.subcommand == "record-prompt":
        return _cmd_record_prompt(paths, args.run_id, args.track, args.prompt_file)
    if args.subcommand == "record-command":
        return _cmd_record_command(paths, args)
    if args.subcommand == "measure-mcp-artifacts":
        return _cmd_measure_mcp_artifacts(paths, args)
    if args.subcommand == "prepare-openai-api-auth":
        return _cmd_prepare_openai_api_auth(paths, args)
    if args.subcommand == "reconcile-openai-usage":
        return _cmd_reconcile_openai_usage(paths, args)
    if args.subcommand == "record-touch":
        return _cmd_record_touch(paths, args)
    if args.subcommand == "build-log-review-prompt":
        return _cmd_build_log_review_prompt(args)
    if args.subcommand == "build-context-review-prompt":
        return _cmd_build_context_review_prompt(args)
    if args.subcommand == "run-codex-checkpoint":
        return _cmd_run_codex_checkpoint(paths, args)
    if args.subcommand == "ingest-codex":
        return _cmd_ingest_codex(paths, args.run_id, args.track, args.jsonl)
    if args.subcommand == "patch-workerbee-stage":
        _run_paths, run_scenario = _resolve_run_context(paths, scenario, args.run_id)
        return _cmd_patch_workerbee_stage(args, run_scenario)
    if args.subcommand == "workerbee-lane":
        _run_paths, run_scenario = _resolve_run_context(paths, scenario, args.run_id)
        return _cmd_workerbee_lane(paths, args, run_scenario)
    if args.subcommand == "audit-run":
        return _cmd_audit_run(paths, args.run_id, args.profile)
    if args.subcommand == "render-report":
        return _cmd_render_report(paths, args.run_id)
    if args.subcommand == "export-html":
        return _cmd_export_html(paths, args.run_id, args.output_dir)
    parser.error(f"unknown command: {args.subcommand}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="simctl")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument(
        "--set",
        dest="scenario_override",
        action="append",
        default=[],
        help="Override scenario values with dotted.key=value; may be repeated.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--run-id", default=None)
    caddy = sub.add_parser("check-workerbee-caddy")
    caddy.add_argument("--state-root", type=Path, required=True)
    caddy.add_argument("--project", default=None)
    k1s_ingress = sub.add_parser("check-k1s-dev-a-ingress")
    k1s_ingress.add_argument("--run-id", default=None)
    k1s_ingress.add_argument("--namespace", default=None)
    k1s_ingress.add_argument(
        "--controller-deployment",
        default=None,
    )
    k1s_ingress.add_argument("--probe-url", default=None)
    k1s_ingress.add_argument(
        "--probe-body-contains",
        default=None,
        help="Required with --probe-url; expected response body text from the deployed app route.",
    )
    k1s_ingress.add_argument("--timeout", type=float, default=5.0)
    k1s_runtime = sub.add_parser("check-k1s-runtime-clean")
    k1s_runtime.add_argument("--run-id", default=None)
    k1s_runtime.add_argument("--allow-run-id", default=None)
    k1s_runtime.add_argument("--port", dest="extra_port", type=int, action="append", default=[])
    k1s_runtime.add_argument("--namespace", default="ae")
    k1s_runtime.add_argument("--nerdctl-bin", default="/var/lib/ae/nerdctl-bin/nerdctl")
    k1s_runtime.add_argument(
        "--containerd-socket",
        default="unix:///var/snap/microk8s/common/run/containerd.sock",
    )
    k1s_runtime.add_argument("--data-root", default="/var/lib/ae/nerdctl")
    k1s_runtime.add_argument("--no-sudo", action="store_true")
    k1s_runtime.add_argument("--timeout", type=float, default=10.0)
    k1s_cleanup = sub.add_parser("cleanup-k1s-dev-a")
    k1s_cleanup.add_argument("--run-id", default=None)
    k1s_cleanup.add_argument("--execute", action="store_true")
    k1s_cleanup.add_argument("--ae-server", default=DEFAULT_AE_SERVER)
    k1s_cleanup.add_argument("--ae-token-env", default=None)
    k1s_cleanup.add_argument("--kubectl-namespace", default=None)
    k1s_cleanup.add_argument("--auth-secret", default="k1s-dev-a-k1s-core-ha-auth")
    k1s_cleanup.add_argument("--ae-bin", default="ae")
    k1s_cleanup.add_argument("--kubectl-bin", default="kubectl")
    k1s_cleanup.add_argument("--nerdctl-bin", default="/var/lib/ae/nerdctl-bin/nerdctl")
    k1s_cleanup.add_argument(
        "--containerd-socket",
        default="unix:///var/snap/microk8s/common/run/containerd.sock",
    )
    k1s_cleanup.add_argument("--containerd-namespace", default="ae")
    k1s_cleanup.add_argument("--data-root", default="/var/lib/ae/nerdctl")
    k1s_cleanup.add_argument("--no-sudo", action="store_true")
    k1s_cleanup.add_argument("--include-workerbee-profiles", action="store_true")
    k1s_cleanup.add_argument("--workerbee-state-root", default=DEFAULT_WORKERBEE_STATE_ROOT)
    k1s_cleanup.add_argument("--workerbee-bin", default="workerbee")
    k1s_cleanup.add_argument("--workerbee-nerdctl-bin", default="/usr/local/bin/nerdctl")
    k1s_cleanup.add_argument("--timeout", type=float, default=15.0)
    init = sub.add_parser("init-run")
    init.add_argument("--run-id", required=True)
    init.add_argument(
        "--track",
        choices=TRACK_CHOICES,
        action="append",
        default=None,
        help="Active track for this run; repeat for comparison. Defaults to both tracks.",
    )
    prompt = sub.add_parser("record-prompt")
    prompt.add_argument("--run-id", required=True)
    prompt.add_argument("--track", choices=TRACK_CHOICES, required=True)
    prompt.add_argument("--prompt-file", type=Path, required=True)
    command = sub.add_parser("record-command")
    command.add_argument("--run-id", required=True)
    command.add_argument("--track", choices=TRACK_CHOICES, required=True)
    command.add_argument(
        "--event-type",
        choices=["command", "workerbee_tool", "ae_command"],
        default="command",
    )
    command.add_argument(
        "--source",
        choices=["human", "codex", "workerbee", "ae", "simctl"],
        required=True,
    )
    command.add_argument("--summary", required=True)
    command.add_argument("--cwd", type=Path, default=None)
    command.add_argument("--exit-code", type=int, default=None)
    command.add_argument("--started-at", default=None)
    command.add_argument("--ended-at", default=None)
    command.add_argument("--duration-seconds", type=float, default=None)
    command.add_argument("--artifact-file", type=Path, action="append", default=[])
    command.add_argument(
        "--artifact-class",
        choices=[
            "targeted_status",
            "targeted_logs",
            "deploy_result",
            "probe_result",
            "build_output",
            "other",
        ],
        default=None,
    )
    command.add_argument(
        "--mcp-visible",
        choices=["true", "false"],
        default=None,
        help="Whether attached WorkerBee artifacts were visible to Codex as MCP/tool observations.",
    )
    command.add_argument(
        "--included-in-codex-usage",
        action="store_true",
        help="Mark attached observation artifacts as already included in Codex JSONL usage.",
    )
    command_text = command.add_mutually_exclusive_group(required=True)
    command_text.add_argument("--command", dest="command_text")
    command_text.add_argument("--command-file", type=Path)
    mcp_measure = sub.add_parser("measure-mcp-artifacts")
    mcp_measure.add_argument("--run-id", required=True)
    mcp_measure.add_argument("--track", choices=TRACK_CHOICES, required=True)
    mcp_measure.add_argument("--commands-dir", type=Path, default=None)
    mcp_measure.add_argument("--artifact-file", type=Path, action="append", default=[])
    mcp_measure.add_argument("--artifact-glob", action="append", default=None)
    mcp_measure.add_argument(
        "--artifact-class",
        choices=[
            "targeted_status",
            "targeted_logs",
            "deploy_result",
            "probe_result",
            "build_output",
            "other",
        ],
        default="other",
    )
    mcp_measure.add_argument("--tokenizer", default="cl100k_base")
    mcp_measure.add_argument(
        "--mcp-visible",
        choices=["true", "false"],
        default="true",
    )
    mcp_measure.add_argument("--included-in-codex-usage", action="store_true")
    mcp_measure.add_argument(
        "--no-replace",
        action="store_true",
        help="Do not remove prior measure-mcp-artifacts events before appending.",
    )
    auth = sub.add_parser("prepare-openai-api-auth")
    auth.add_argument("--run-id", required=True)
    auth.add_argument("--track", choices=TRACK_CHOICES, required=True)
    auth.add_argument("--api-key-env", required=True)
    auth.add_argument("--codex-home", type=Path, default=None)
    auth.add_argument("--codex-bin", default="codex")
    reconcile = sub.add_parser("reconcile-openai-usage")
    reconcile.add_argument("--run-id", required=True)
    reconcile.add_argument("--admin-key-env", default="OPENAI_ADMIN_KEY")
    reconcile.add_argument("--plain-project-id", default=None)
    reconcile.add_argument("--workerbee-project-id", default=None)
    reconcile.add_argument("--plain-api-key-id", default=None)
    reconcile.add_argument("--workerbee-api-key-id", default=None)
    reconcile.add_argument(
        "--track-project-id",
        action="append",
        default=[],
        help="Map an active track to an OpenAI project ID as TRACK=PROJECT; may be repeated.",
    )
    reconcile.add_argument(
        "--track-api-key-id",
        action="append",
        default=[],
        help="Map an active track to an OpenAI API key ID as TRACK=KEY; may be repeated.",
    )
    reconcile.add_argument("--start-time", default=None)
    reconcile.add_argument("--end-time", default=None)
    reconcile.add_argument("--window-pad-seconds", type=int, default=600)
    reconcile.add_argument("--usage-json", type=Path, default=None)
    reconcile.add_argument("--costs-json", type=Path, default=None)
    reconcile.add_argument("--base-url", default="https://api.openai.com/v1")
    reconcile.add_argument(
        "--mark-required",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Mark provider reconciliation as required for public audit.",
    )
    reconcile.add_argument(
        "--require-costs",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Treat missing provider cost values as an audit error.",
    )
    touch = sub.add_parser("record-touch")
    touch.add_argument("--run-id", required=True)
    touch.add_argument("--track", choices=TRACK_CHOICES, required=True)
    touch.add_argument("--summary", required=True)
    touch.add_argument(
        "--kind",
        choices=[
            "copy_logs",
            "dashboard_action",
            "cert_setup",
            "context_management",
            "manual_wait",
            "troubleshoot",
            "other",
        ],
        default="other",
    )
    touch.add_argument("--detail", default=None)
    touch.add_argument("--started-at", default=None)
    touch.add_argument("--ended-at", default=None)
    touch.add_argument("--duration-seconds", type=float, default=None)
    log_prompt = sub.add_parser("build-log-review-prompt")
    log_prompt.add_argument("--output", type=Path, required=True)
    log_prompt.add_argument("--title", required=True)
    log_prompt.add_argument("--instruction", required=True)
    log_prompt.add_argument("--log-file", type=Path, action="append", required=True)
    log_prompt.add_argument("--max-bytes-per-log", type=int, default=120_000)
    log_prompt.add_argument(
        "--copied-context-class",
        choices=sorted(COPIED_CONTEXT_CLASSES),
        default="local_logs",
    )
    context_prompt = sub.add_parser("build-context-review-prompt")
    context_prompt.add_argument("--output", type=Path, required=True)
    context_prompt.add_argument("--title", required=True)
    context_prompt.add_argument("--instruction", required=True)
    context_prompt.add_argument("--context-file", type=Path, action="append", required=True)
    context_prompt.add_argument("--context-label", default="Context")
    context_prompt.add_argument("--max-bytes-per-file", type=int, default=120_000)
    context_prompt.add_argument(
        "--copied-context-class",
        choices=sorted(COPIED_CONTEXT_CLASSES),
        default="k1s_docs",
    )
    codex_checkpoint = sub.add_parser("run-codex-checkpoint")
    codex_checkpoint.add_argument("--run-id", required=True)
    codex_checkpoint.add_argument("--track", choices=TRACK_CHOICES, required=True)
    codex_checkpoint.add_argument("--checkpoint-id", required=True)
    codex_checkpoint.add_argument("--prompt-file", type=Path, required=True)
    codex_checkpoint.add_argument("--cwd", type=Path, required=True)
    codex_checkpoint.add_argument("--mode", choices=["start", "resume", "isolated"], required=True)
    codex_checkpoint.add_argument("--session-id", default=None)
    codex_checkpoint.add_argument("--jsonl", type=Path, default=None)
    codex_checkpoint.add_argument("--response", type=Path, default=None)
    codex_checkpoint.add_argument("--codex-bin", default="codex")
    codex_checkpoint.add_argument("--codex-home", type=Path, default=None)
    codex_checkpoint.add_argument("--model", default=None)
    ingest = sub.add_parser("ingest-codex")
    ingest.add_argument("--run-id", required=True)
    ingest.add_argument("--track", choices=TRACK_CHOICES, required=True)
    ingest.add_argument("--jsonl", type=Path, required=True)
    patch_stage = sub.add_parser("patch-workerbee-stage")
    patch_stage.add_argument("--run-id", default=None)
    patch_stage.add_argument("--stage-dir", type=Path, required=True)
    patch_stage.add_argument("--project", required=True)
    patch_stage.add_argument("--app-host", default=None)
    patch_stage.add_argument("--domain", default=None)
    patch_stage.add_argument("--manifest", default=None)
    patch_stage.add_argument("--ingress-host-path", default=None)
    patch_stage.add_argument(
        "--env",
        dest="env_update",
        action="append",
        default=[],
        help="Set a manifest env value with NAME=value-template; may be repeated.",
    )
    patch_stage.add_argument(
        "--value",
        dest="value_update",
        action="append",
        default=[],
        help="Set a manifest YAML value with dotted.path=value-template; may be repeated.",
    )
    workerbee_lane = sub.add_parser("workerbee-lane")
    workerbee_lane.add_argument("--run-id", required=True)
    workerbee_lane.add_argument("--project", default=None)
    workerbee_lane.add_argument("--stage-dir", type=Path, default=None)
    workerbee_lane.add_argument("--artifact-file", type=Path, action="append", default=[])
    workerbee_lane.add_argument(
        "--artifact-class",
        choices=[
            "targeted_status",
            "targeted_logs",
            "deploy_result",
            "probe_result",
            "build_output",
            "other",
        ],
        default="other",
    )
    workerbee_lane.add_argument(
        "--mcp-visible",
        choices=["true", "false"],
        default="true",
    )
    workerbee_lane.add_argument("--summary", default=None)
    workerbee_lane.add_argument("--duration-seconds", type=float, default=None)
    workerbee_actions = workerbee_lane.add_subparsers(dest="workerbee_action", required=True)
    for action in ("prepare", "deploy-local", "probe", "collect-evidence", "cleanup", "run"):
        workerbee_actions.add_parser(action)
    report = sub.add_parser("render-report")
    report.add_argument("--run-id", required=True)
    audit = sub.add_parser("audit-run")
    audit.add_argument("--run-id", required=True)
    audit.add_argument("--profile", default="public-tech-report")
    html = sub.add_parser("export-html")
    html.add_argument("--run-id", required=True)
    html.add_argument("--output-dir", type=Path, default=None)
    return parser


def _resolve_run_context(
    paths,
    scenario: Scenario,
    run_id: str | None,
):
    if not run_id:
        return paths, scenario
    run_scenario = load_run_scenario(paths.runs_dir / run_id, scenario)
    return default_paths(paths.repo_root, scenario=run_scenario), run_scenario


def _ensure_active_track(paths, run_id: str, track: str) -> None:
    run_root = paths.runs_dir / run_id
    if not (run_root / "manifest.json").exists():
        return
    active_tracks = active_tracks_for_run(run_root)
    if track not in active_tracks:
        raise SystemExit(
            f"Track `{track}` is not active for run `{run_id}`. "
            f"Active track(s): {', '.join(active_tracks)}"
        )


def _cmd_preflight(paths, scenario: Scenario) -> int:
    checks = run_preflight(paths, scenario=scenario)
    width = max(len(check.name) for check in checks)
    for check in checks:
        status = "ok" if check.ok else "fail"
        print(f"{status:4} {check.name:<{width}} {check.detail}")
    return 0 if all(check.ok for check in checks) else 1


def _cmd_check_workerbee_caddy(args: argparse.Namespace) -> int:
    result = check_workerbee_caddy_routes(args.state_root, project=args.project)
    payload = {
        "ok": result.ok,
        "state_root": str(args.state_root),
        "project": args.project,
        "files": [str(path) for path in result.files],
        "findings": [
            {"severity": finding.severity, "message": finding.message}
            for finding in result.findings
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0 if result.ok else 1


def _cmd_check_k1s_dev_a_ingress(args: argparse.Namespace, scenario: Scenario) -> int:
    defaults = scenario.k1s_ingress
    namespace = args.namespace or str(defaults.get("namespace") or "k1s-dev-a")
    controller_deployment = args.controller_deployment or str(
        defaults.get("controller_deployment") or "k1s-dev-a-k1s-core-ha-controller"
    )
    probe_url = args.probe_url or defaults.get("probe_url")
    probe_body_contains = args.probe_body_contains
    if probe_body_contains is None and defaults.get("probe_body_contains") is not None:
        probe_body_contains = str(defaults["probe_body_contains"])
    result = check_k1s_dev_a_ingress(
        namespace=namespace,
        controller_deployment=controller_deployment,
        probe_url=str(probe_url) if probe_url else None,
        probe_body_contains=probe_body_contains,
        timeout=args.timeout,
    )
    payload = {
        "ok": result.ok,
        "namespace": namespace,
        "controller_deployment": controller_deployment,
        "probe_url": str(probe_url) if probe_url else None,
        "probe_body_contains": probe_body_contains,
        "controller_env": {
            key: result.controller_env.get(key)
            for key in sorted(result.controller_env)
            if key.startswith("AE_EDGE_INGRESS")
            or key in {"AE_TRANSPORT_BACKEND", "AE_STATE_BACKEND"}
        },
        "core_proxy_ports_open": result.core_proxy_ports_open,
        "findings": [
            {"severity": finding.severity, "message": finding.message}
            for finding in result.findings
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0 if result.ok else 1


def _cmd_check_k1s_runtime_clean(args: argparse.Namespace, scenario: Scenario) -> int:
    reserved_ports = sorted(set(scenario_reserved_ports(scenario) + list(args.extra_port or [])))
    result = check_k1s_runtime_clean(
        reserved_ports=reserved_ports,
        allow_run_id=args.allow_run_id,
        nerdctl_bin=args.nerdctl_bin,
        containerd_socket=args.containerd_socket,
        namespace=args.namespace,
        data_root=args.data_root,
        use_sudo=not args.no_sudo,
        timeout=args.timeout,
    )
    payload = {
        "ok": result.ok,
        "namespace": args.namespace,
        "reserved_ports": result.reserved_ports,
        "container_count": len(result.containers),
        "host_listener_count": len(result.listeners),
        "violating_containers": [
            {
                "id": container.container_id,
                "name": container.name,
                "ports": container.ports,
            }
            for container in result.containers
            if any(container.name in finding.message for finding in result.findings)
        ],
        "violating_listeners": [
            {
                "protocol": listener.protocol,
                "local_address": listener.local_address,
                "port": listener.port,
            }
            for listener in result.listeners
        ],
        "findings": [
            {"severity": finding.severity, "message": finding.message}
            for finding in result.findings
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0 if result.ok else 1


def _cmd_cleanup_k1s_dev_a(args: argparse.Namespace, scenario: Scenario) -> int:
    defaults = scenario.k1s_ingress
    namespace = args.kubectl_namespace or str(defaults.get("namespace") or "k1s-dev-a")
    reserved_ports = sorted(set(scenario_reserved_ports(scenario)))
    result = cleanup_k1s_dev_a(
        run_id=args.run_id,
        execute=bool(args.execute),
        ae_server=args.ae_server,
        ae_token_env=args.ae_token_env,
        kubectl_namespace=namespace,
        auth_secret=args.auth_secret,
        ae_bin=args.ae_bin,
        kubectl_bin=args.kubectl_bin,
        nerdctl_bin=args.nerdctl_bin,
        containerd_socket=args.containerd_socket,
        containerd_namespace=args.containerd_namespace,
        data_root=args.data_root,
        use_sudo=not args.no_sudo,
        reserved_ports=reserved_ports,
        include_workerbee_profiles=bool(args.include_workerbee_profiles),
        workerbee_state_root=args.workerbee_state_root,
        workerbee_bin=args.workerbee_bin,
        workerbee_nerdctl_bin=args.workerbee_nerdctl_bin,
        timeout=args.timeout,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


def _cmd_record_prompt(paths, run_id: str, track: Track, prompt_file: Path) -> int:
    _ensure_active_track(paths, run_id, track)
    prompt_text = prompt_file.read_text(encoding="utf-8")
    append_event(
        paths.runs_dir / run_id / track / "events.jsonl",
        SimulationEvent(
            run_id=run_id,
            track=track,
            event_type="human_prompt",
            source="human",
            summary=prompt_text.splitlines()[0][:120] if prompt_text.strip() else "empty prompt",
            payload=_prompt_payload(prompt_file, prompt_text),
        ),
    )
    return 0


def _cmd_record_command(paths, args: argparse.Namespace) -> int:
    _ensure_active_track(paths, args.run_id, args.track)
    command_text = args.command_text
    if args.command_file is not None:
        command_text = args.command_file.read_text(encoding="utf-8")
    payload = {
        "command": command_text,
        "cwd": str(args.cwd.resolve()) if args.cwd else None,
        "exit_code": args.exit_code,
        "started_at": args.started_at,
        "ended_at": args.ended_at,
        "duration_seconds": args.duration_seconds,
        "artifact_files": [str(path) for path in args.artifact_file],
        "artifact_class": args.artifact_class,
        "mcp_visible": _optional_bool(args.mcp_visible),
        "included_in_codex_usage": args.included_in_codex_usage or None,
    }
    if args.event_type == "workerbee_tool" and args.artifact_file and args.mcp_visible is None:
        payload["mcp_visible"] = True
    append_event(
        paths.runs_dir / args.run_id / args.track / "events.jsonl",
        SimulationEvent(
            run_id=args.run_id,
            track=args.track,
            event_type=args.event_type,
            source=args.source,
            summary=args.summary,
            payload={key: value for key, value in payload.items() if value is not None},
        ),
    )
    return 0


def _cmd_measure_mcp_artifacts(paths, args: argparse.Namespace) -> int:
    run_root = paths.runs_dir / args.run_id
    _ensure_active_track(paths, args.run_id, args.track)
    track_root = run_root / args.track
    event_path = track_root / "events.jsonl"
    artifacts = _mcp_artifact_paths(args, track_root)
    mcp_visible = _optional_bool(args.mcp_visible)
    if mcp_visible is None:
        mcp_visible = True
    existing = read_events(event_path)
    if not args.no_replace:
        existing = [
            event
            for event in existing
            if not (
                event.event_type == "mcp_observation"
                and event.payload.get("generated_by") == "measure-mcp-artifacts"
            )
        ]
    appended = []
    for artifact in artifacts:
        measurement = measure_artifact_tokens(artifact, tokenizer=args.tokenizer)
        event = SimulationEvent(
            run_id=args.run_id,
            track=args.track,
            event_type="mcp_observation",
            source="simctl",
            summary=f"MCP observation token estimate for {artifact.name}",
            timestamp=_artifact_timestamp(artifact),
            payload={
                "artifact_file": _display_path(artifact, run_root),
                "artifact_class": args.artifact_class,
                "mcp_visible": mcp_visible,
                "included_in_codex_usage": bool(args.included_in_codex_usage),
                "byte_count": measurement.byte_count,
                "token_count": measurement.token_count,
                "tokenizer_requested": measurement.tokenizer_requested,
                "tokenizer_actual": measurement.tokenizer_actual,
                "estimation_method": measurement.estimation_method,
                "sha256": measurement.sha256,
                "generated_by": "measure-mcp-artifacts",
            },
        )
        appended.append(event)
    _write_events(event_path, _sort_events(existing + appended))
    total_bytes = sum(int(event.payload.get("byte_count") or 0) for event in appended)
    total_tokens = sum(int(event.payload.get("token_count") or 0) for event in appended)
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "track": args.track,
                "artifacts": len(appended),
                "mcp_visible": mcp_visible,
                "included_in_codex_usage": bool(args.included_in_codex_usage),
                "byte_count": total_bytes,
                "token_count": total_tokens,
                "event_file": str(event_path),
            },
            indent=2,
        )
    )
    return 0


def _cmd_prepare_openai_api_auth(paths, args: argparse.Namespace) -> int:
    _ensure_active_track(paths, args.run_id, args.track)
    codex_home = (
        args.codex_home or paths.local_dir / "auth" / "codex-api" / args.run_id / args.track
    ).resolve()
    result = prepare_codex_api_auth(
        track=args.track,
        api_key_env=args.api_key_env,
        codex_home=codex_home,
        codex_bin=args.codex_bin,
    )
    run_root = paths.runs_dir / args.run_id
    append_event(
        run_root / args.track / "events.jsonl",
        SimulationEvent(
            run_id=args.run_id,
            track=args.track,
            event_type="billing_reconciliation",
            source="simctl",
            summary=f"Prepared Codex API-key auth for {args.track}",
            payload=result.event_payload(),
        ),
    )
    _update_manifest(
        run_root,
        lambda manifest: _merge_billing_manifest(
            manifest,
            {
                "auth_method": "api_key",
                "auth": {
                    args.track: {
                        "api_key_env": args.api_key_env,
                        "codex_home": str(codex_home),
                        "codex_bin": args.codex_bin,
                        "prepared_at": utc_now_iso(),
                        "returncode": result.returncode,
                    }
                },
            },
        ),
    )
    print(
        json.dumps(
            {
                "ok": result.ok,
                "run_id": args.run_id,
                "track": args.track,
                "codex_home": str(codex_home),
                "api_key_env": args.api_key_env,
                "returncode": result.returncode,
            },
            indent=2,
        )
    )
    return result.returncode


def _cmd_reconcile_openai_usage(paths, args: argparse.Namespace) -> int:
    run_root = paths.runs_dir / args.run_id
    active_tracks = active_tracks_for_run(run_root)
    track_project_ids = _track_project_ids_from_args(args, active_tracks)
    missing = [track for track in active_tracks if not track_project_ids.get(track)]
    if missing:
        raise SystemExit(
            "Missing OpenAI project ID for active track(s): "
            + ", ".join(missing)
            + ". Use --track-project-id TRACK=PROJECT or the lane-specific project flag/env."
        )
    project_values = [track_project_ids[track] for track in active_tracks]
    if len(set(project_values)) != len(project_values):
        raise SystemExit("OpenAI project IDs must be distinct across active tracks")
    track_api_key_ids = _track_api_key_ids_from_args(args, active_tracks)
    billing_dir = run_root / "billing" / "openai"
    billing_dir.mkdir(parents=True, exist_ok=True)
    reconciliation_path = run_root / "billing" / "reconciliation.json"
    raw_usage_path = billing_dir / "usage-completions.raw.json"
    raw_costs_path = billing_dir / "costs.raw.json"
    reconciliation = reconcile_openai_usage(
        run_root=run_root,
        admin_key_env=args.admin_key_env,
        track_project_ids=track_project_ids,
        track_api_key_ids=track_api_key_ids,
        start_time=args.start_time,
        end_time=args.end_time,
        window_pad_seconds=args.window_pad_seconds,
        usage_json=args.usage_json,
        costs_json=args.costs_json,
        base_url=args.base_url,
        tracks=active_tracks,
    )
    raw_usage_path.write_text(
        json.dumps(reconciliation["usage_raw"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    raw_costs_path.write_text(
        json.dumps(reconciliation["costs_raw"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    normalized = normalized_reconciliation(reconciliation)
    reconciliation_path.parent.mkdir(parents=True, exist_ok=True)
    reconciliation_path.write_text(
        json.dumps(normalized, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    event_source = (
        "simctl" if reconciliation.get("source") == "offline_fixture" else "openai-admin-api"
    )
    for track in active_tracks:
        append_event(
            run_root / track / "events.jsonl",
            SimulationEvent(
                run_id=args.run_id,
                track=track,
                event_type="billing_reconciliation",
                source=event_source,
                summary=f"Reconciled OpenAI provider usage for {track}",
                payload=billing_event_payload(
                    reconciliation=reconciliation,
                    track=track,
                    raw_usage_path=raw_usage_path,
                    raw_costs_path=raw_costs_path,
                    reconciliation_path=reconciliation_path,
                    run_root=run_root,
                ),
            ),
        )
    _update_manifest(
        run_root,
        lambda manifest: _merge_billing_manifest(
            manifest,
            {
                "required": bool(args.mark_required),
                "require_costs": bool(args.require_costs),
                "source": reconciliation.get("source"),
                "provider": "openai",
                "auth_method": "api_key",
                "fetched_at": reconciliation.get("fetched_at"),
                "window_started_at": reconciliation.get("window_started_at"),
                "window_ended_at": reconciliation.get("window_ended_at"),
                "window_pad_seconds": reconciliation.get("window_pad_seconds"),
                "cost_window_started_at": reconciliation.get("cost_window_started_at"),
                "cost_window_ended_at": reconciliation.get("cost_window_ended_at"),
                "raw_usage_file": _display_path(raw_usage_path, run_root),
                "raw_costs_file": _display_path(raw_costs_path, run_root),
                "reconciliation_file": _display_path(reconciliation_path, run_root),
                "tracks": {
                    track: {
                        "project_id": track_project_ids[track],
                        "api_key_id": track_api_key_ids.get(track),
                        "match_basis": normalized["tracks"][track]["comparison"]["match_basis"],
                    }
                    for track in active_tracks
                },
            },
        ),
    )
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "source": reconciliation.get("source"),
                "window_started_at": reconciliation.get("window_started_at"),
                "window_ended_at": reconciliation.get("window_ended_at"),
                "reconciliation": str(reconciliation_path),
                "tracks": {
                    track: normalized["tracks"][track]["comparison"]["match_basis"]
                    for track in active_tracks
                },
            },
            indent=2,
        )
    )
    return 0


def _track_project_ids_from_args(
    args: argparse.Namespace,
    active_tracks: tuple[Track, ...],
) -> dict[str, str]:
    values = _parse_track_mapping(args.track_project_id, "--track-project-id")
    legacy = {
        "plain-codex": args.plain_project_id or os.environ.get("SIM_OPENAI_PROJECT_PLAIN"),
        "workerbee-codex": args.workerbee_project_id
        or os.environ.get("SIM_OPENAI_PROJECT_WORKERBEE"),
    }
    for track in active_tracks:
        if track not in values and legacy.get(track):
            values[track] = str(legacy[track])
    return {track: values[track] for track in active_tracks if values.get(track)}


def _track_api_key_ids_from_args(
    args: argparse.Namespace,
    active_tracks: tuple[Track, ...],
) -> dict[str, str | None]:
    values = _parse_track_mapping(args.track_api_key_id, "--track-api-key-id")
    legacy = {
        "plain-codex": args.plain_api_key_id,
        "workerbee-codex": args.workerbee_api_key_id,
    }
    for track in active_tracks:
        if track not in values and legacy.get(track):
            values[track] = str(legacy[track])
    return {track: values.get(track) for track in active_tracks}


def _parse_track_mapping(values: list[str], option: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"{option} must use TRACK=value: {value}")
        raw_track, raw_mapping = value.split("=", 1)
        track = raw_track.strip()
        mapping = raw_mapping.strip()
        normalize_tracks([track])
        if not mapping:
            raise SystemExit(f"{option} value is empty for track `{track}`")
        parsed[track] = mapping
    return parsed


def _cmd_record_touch(paths, args: argparse.Namespace) -> int:
    _ensure_active_track(paths, args.run_id, args.track)
    payload = {
        "kind": args.kind,
        "detail": args.detail,
        "started_at": args.started_at,
        "ended_at": args.ended_at,
        "duration_seconds": args.duration_seconds,
    }
    append_event(
        paths.runs_dir / args.run_id / args.track / "events.jsonl",
        SimulationEvent(
            run_id=args.run_id,
            track=args.track,
            event_type="human_action",
            source="human",
            summary=args.summary,
            payload={key: value for key, value in payload.items() if value is not None},
        ),
    )
    return 0


def _cmd_build_log_review_prompt(args: argparse.Namespace) -> int:
    output = build_log_review_prompt(
        output=args.output,
        title=args.title,
        instruction=args.instruction,
        log_files=args.log_file,
        max_bytes_per_log=args.max_bytes_per_log,
        copied_context_class=args.copied_context_class,
    )
    print(output)
    return 0


def _cmd_build_context_review_prompt(args: argparse.Namespace) -> int:
    output = build_context_review_prompt(
        output=args.output,
        title=args.title,
        instruction=args.instruction,
        context_files=args.context_file,
        context_label=args.context_label,
        max_bytes_per_file=args.max_bytes_per_file,
        copied_context_class=args.copied_context_class,
    )
    print(output)
    return 0


def _cmd_run_codex_checkpoint(paths, args: argparse.Namespace) -> int:
    _ensure_active_track(paths, args.run_id, args.track)
    run_root = paths.runs_dir / args.run_id / args.track
    codex_dir = run_root / "codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = args.jsonl or codex_dir / f"{args.checkpoint_id}.jsonl"
    response_path = args.response or codex_dir / f"{args.checkpoint_id}.response.md"
    stderr_path = jsonl_path.with_suffix(".stderr")
    prompt_text = args.prompt_file.read_text(encoding="utf-8")
    event_path = run_root / "events.jsonl"
    append_event(
        event_path,
        SimulationEvent(
            run_id=args.run_id,
            track=args.track,
            event_type="human_prompt",
            source="human",
            summary=prompt_text.splitlines()[0][:120] if prompt_text.strip() else "empty prompt",
            payload=_prompt_payload(args.prompt_file, prompt_text),
        ),
    )
    command, command_for_log = _codex_command(args, response_path)
    env = os.environ.copy()
    codex_home = (args.codex_home or run_root / "codex-home").resolve()
    _prepare_codex_home(codex_home)
    env["CODEX_HOME"] = str(codex_home)
    started_at = utc_now_iso()
    result = subprocess.run(  # noqa: S603 - command is intentionally user-selected CLI path.
        command,
        input=prompt_text,
        text=True,
        cwd=args.cwd,
        env=env,
        capture_output=True,
        check=False,
    )
    ended_at = utc_now_iso()
    jsonl_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    for event in normalize_codex_jsonl(jsonl_path, run_id=args.run_id, track=args.track):
        append_event(event_path, event)
    session_id = _extract_thread_id(jsonl_path) or args.session_id
    append_event(
        event_path,
        SimulationEvent(
            run_id=args.run_id,
            track=args.track,
            event_type="command",
            source="human",
            summary=f"submitted {args.track} checkpoint {args.checkpoint_id} to Codex CLI",
            payload={
                "command": command_for_log,
                "cwd": str(args.cwd.resolve()),
                "started_at": started_at,
                "ended_at": ended_at,
                "exit_code": result.returncode,
                "checkpoint_id": args.checkpoint_id,
                "codex_invocation_mode": args.mode,
                "codex_session_id": session_id,
                "prompt_file": str(args.prompt_file),
                "jsonl_file": str(jsonl_path),
                "response_file": str(response_path),
                "stderr_file": str(stderr_path),
                "codex_home": str(codex_home),
            },
        ),
    )
    print(
        json.dumps(
            {
                "ok": result.returncode == 0,
                "exit_code": result.returncode,
                "session_id": session_id,
                "jsonl": str(jsonl_path),
                "response": str(response_path),
                "stderr": str(stderr_path),
            },
            indent=2,
        )
    )
    return result.returncode


def _cmd_ingest_codex(paths, run_id: str, track: Track, jsonl: Path) -> int:
    _ensure_active_track(paths, run_id, track)
    event_path = paths.runs_dir / run_id / track / "events.jsonl"
    events = normalize_codex_jsonl(jsonl, run_id=run_id, track=track)
    for event in events:
        append_event(event_path, event)
    print(f"ingested {len(events)} events")
    return 0


def _prompt_payload(prompt_file: Path, prompt_text: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "prompt_file": str(prompt_file),
        "prompt": prompt_text,
        "prompt_char_count": len(prompt_text),
        "prompt_byte_count": len(prompt_text.encode("utf-8")),
        "prompt_word_count": len(prompt_text.split()),
    }
    metadata = read_prompt_metadata(prompt_file)
    if metadata:
        payload["prompt_metadata"] = metadata
    return payload


def _codex_command(args: argparse.Namespace, response_path: Path) -> tuple[list[str], str]:
    base = [args.codex_bin]
    common = [
        "--json",
        "--ignore-rules",
        "--ignore-user-config",
        "--output-last-message",
        str(response_path),
    ]
    if args.model:
        common.extend(["--model", args.model])
    if args.mode == "resume":
        if not args.session_id:
            raise SystemExit("--session-id is required with --mode resume")
        command = base + ["exec", "resume", *common, args.session_id, "-"]
    else:
        command = base + [
            "exec",
            *common,
            "-C",
            str(args.cwd),
            "--sandbox",
            "read-only",
        ]
        if args.mode == "isolated":
            command.append("--ephemeral")
        command.append("-")
    return command, " ".join(shlex.quote(part) for part in command)


def _prepare_codex_home(codex_home: Path) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    source_home = Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser()
    if source_home.resolve() == codex_home.resolve():
        return
    for name in ("auth.json", "credentials.json", "auth.toml"):
        source = source_home / name
        target = codex_home / name
        if source.exists() and not target.exists():
            target.symlink_to(source)


def _extract_thread_id(jsonl_path: Path) -> str | None:
    if not jsonl_path.exists():
        return None
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        thread_id = data.get("thread_id")
        if data.get("type") == "thread.started" and thread_id:
            return str(thread_id)
    return None


def _cmd_patch_workerbee_stage(args: argparse.Namespace, scenario: Scenario) -> int:
    result = patch_stage(
        args.stage_dir,
        project=args.project,
        stage_config=scenario.workerbee_stage,
        app_host=args.app_host,
        domain=args.domain,
        manifest=args.manifest,
        ingress_host_path=args.ingress_host_path,
        env_updates=_parse_env_updates(args.env_update),
        value_updates=_parse_value_updates(args.value_update),
    )
    print(json.dumps(result, indent=2))
    return 0


def _cmd_workerbee_lane(paths, args: argparse.Namespace, scenario: Scenario) -> int:
    _ensure_active_track(paths, args.run_id, "workerbee-codex")
    run_root = paths.runs_dir / args.run_id
    action_names = (
        ("prepare", "validate scenario, runtime policy, and WorkerBee availability"),
        ("deploy-local", "build, stage, patch, deploy, and inspect the local WorkerBee profile"),
        ("probe", "run targeted WorkerBee status, log, ingress, and feature probes"),
        ("collect-evidence", "collect screenshots, probe output, logs, and MCP artifacts"),
        ("cleanup", "tear down WorkerBee and k1s-dev-a simulation orphans after evidence"),
    )
    selected = (
        [name for name, _summary in action_names]
        if args.workerbee_action == "run"
        else [args.workerbee_action]
    )
    emitted = []
    for action in selected:
        plan = _workerbee_lane_action_payload(args, scenario, action)
        event = SimulationEvent(
            run_id=args.run_id,
            track="workerbee-codex",
            event_type="workerbee_tool",
            source="workerbee",
            summary=args.summary or f"WorkerBee lane {action}: {plan['summary']}",
            payload=plan,
        )
        append_event(run_root / "workerbee-codex" / "events.jsonl", event)
        emitted.append(plan)
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "track": "workerbee-codex",
                "action": args.workerbee_action,
                "events": len(emitted),
                "event_file": str(run_root / "workerbee-codex" / "events.jsonl"),
                "actions": emitted,
            },
            indent=2,
        )
    )
    return 0


def _workerbee_lane_action_payload(
    args: argparse.Namespace,
    scenario: Scenario,
    action: str,
) -> dict[str, object]:
    stage = scenario.workerbee_stage
    policy = scenario.runtime_policy.get("workerbee-codex", {})
    artifacts = [str(path) for path in args.artifact_file]
    command = _workerbee_lane_command(args, action)
    recommended_tools = _workerbee_lane_tools(action)
    payload: dict[str, object] = {
        "wrapper_action": action,
        "summary": _workerbee_lane_summary(action),
        "command": command,
        "project": args.project,
        "stage_dir": str(args.stage_dir) if args.stage_dir else None,
        "artifact_files": artifacts,
        "artifact_class": args.artifact_class,
        "mcp_visible": _optional_bool(args.mcp_visible),
        "duration_seconds": args.duration_seconds,
        "recommended_workerbee_tools": recommended_tools,
        "runtime_policy": policy,
        "target_root": str(scenario.target_root),
        "target_label": scenario.target_label,
        "feature_prompt": scenario.feature_prompt,
        "workerbee_stage": {
            "manifest": stage.get("manifest"),
            "domain": stage.get("domain"),
            "app_host_template": stage.get("app_host_template"),
            "ingress_host_path": stage.get("ingress_host_path"),
            "local_profile_service_ports": stage.get("local_profile_service_ports"),
        },
        "measurement_note": (
            "This high-level wrapper records the WorkerBee lane operation as a "
            "measured automation action. Attach targeted artifacts and run "
            "`simctl measure-mcp-artifacts` when MCP/tool observations were visible to Codex."
        ),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _workerbee_lane_command(args: argparse.Namespace, action: str) -> str:
    parts = ["simctl", "workerbee-lane", "--run-id", args.run_id]
    if args.project:
        parts.extend(["--project", args.project])
    if args.stage_dir:
        parts.extend(["--stage-dir", str(args.stage_dir)])
    parts.append(action)
    return " ".join(shlex.quote(part) for part in parts)


def _workerbee_lane_summary(action: str) -> str:
    return {
        "prepare": "scenario/runtime validated for WorkerBee native containerd lane",
        "deploy-local": "local WorkerBee profile deployment path executed",
        "probe": "targeted WorkerBee status/log/probe validation executed",
        "collect-evidence": "WorkerBee evidence and MCP artifacts collected",
        "cleanup": "WorkerBee and k1s-dev-a simulation cleanup executed",
        "run": "WorkerBee lane sequence executed",
    }.get(action, action)


def _workerbee_lane_tools(action: str) -> list[str]:
    tools = {
        "prepare": ["workerbee_v1_session_start", "workerbee_v1_capabilities"],
        "deploy-local": [
            "workerbee_v1_profile_start",
            "workerbee_v1_manifest_prepare",
            "workerbee_v1_manifest_validate",
            "workerbee_v1_manifest_deploy_local",
            "workerbee_v1_profile_workload_status",
        ],
        "probe": [
            "workerbee_v1_profile_workload_status",
            "workerbee_v1_logs",
            "workerbee_v1_ingress_probe",
        ],
        "collect-evidence": [
            "workerbee_v1_logs",
            "workerbee_v1_ingress_probe",
            "simctl measure-mcp-artifacts",
        ],
        "cleanup": [
            "workerbee_v1_profile_stop",
            "simctl cleanup-k1s-dev-a",
            "simctl check-k1s-runtime-clean",
        ],
    }
    return tools.get(action, [])


def _cmd_render_report(paths, run_id: str) -> int:
    run_root = paths.runs_dir / run_id
    report = render_run_report(run_root)
    output = run_root / "report.md"
    output.write_text(report + "\n", encoding="utf-8")
    print(output)
    return 0


def _cmd_export_html(paths, run_id: str, output_dir: Path | None) -> int:
    export = export_run_html(paths.runs_dir / run_id, output_dir=output_dir)
    print(export.output_dir / "index.html")
    return 0


def _cmd_audit_run(paths, run_id: str, profile: str) -> int:
    report = write_audit_report(paths.runs_dir / run_id, profile=profile)
    print(paths.runs_dir / run_id / "audit.json")
    return 0 if report.accepted else 1


def _parse_env_updates(values: list[str]) -> dict[str, str]:
    return _parse_key_value_updates(values, "--env", "NAME")


def _parse_value_updates(values: list[str]) -> dict[str, str]:
    return _parse_key_value_updates(values, "--value", "dotted.path")


def _parse_key_value_updates(values: list[str], option: str, key_label: str) -> dict[str, str]:
    updates: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option} must use {key_label}=value-template: {value}")
        name, template = value.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"{option} {key_label} is empty: {value}")
        updates[name] = template
    return updates


def _update_manifest(run_root: Path, update_fn) -> None:
    manifest_path = run_root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            manifest = {}
    else:
        manifest = {"run_id": run_root.name}
    update_fn(manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _merge_billing_manifest(manifest: dict[str, object], update: dict[str, object]) -> None:
    billing = manifest.get("billing_reconciliation")
    if not isinstance(billing, dict):
        billing = {}
    for key, value in update.items():
        if key in {"auth", "tracks"} and isinstance(value, dict):
            existing = billing.get(key)
            if not isinstance(existing, dict):
                existing = {}
            for nested_key, nested_value in value.items():
                if isinstance(nested_value, dict) and isinstance(existing.get(nested_key), dict):
                    merged = dict(existing[nested_key])
                    merged.update(nested_value)
                    existing[nested_key] = merged
                else:
                    existing[nested_key] = nested_value
            billing[key] = existing
        else:
            billing[key] = value
    manifest["billing_reconciliation"] = billing


def _optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() == "true"


def _mcp_artifact_paths(args: argparse.Namespace, track_root: Path) -> list[Path]:
    paths: list[Path] = []
    if args.artifact_file:
        paths.extend(path.resolve() for path in args.artifact_file if path.is_file())
    else:
        commands_dir = args.commands_dir or track_root / "commands"
        for pattern in args.artifact_glob or ["*"]:
            paths.extend(path.resolve() for path in commands_dir.glob(pattern) if path.is_file())
    return sorted(dict.fromkeys(paths))


def _write_events(path: Path, events: list[SimulationEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(event.to_json() + "\n" for event in events), encoding="utf-8")


def _sort_events(events: list[SimulationEvent]) -> list[SimulationEvent]:
    return sorted(events, key=lambda event: event.timestamp)


def _artifact_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


def _display_path(path: Path, run_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(run_root.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
