from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path

from .audit import write_audit_report
from .caddy_preflight import check_workerbee_caddy_routes
from .codex_events import normalize_codex_jsonl
from .config import default_paths
from .context_prompt import build_context_review_prompt
from .html_export import export_run_html
from .k1s_preflight import check_k1s_dev_a_ingress
from .k1s_runtime_preflight import check_k1s_runtime_clean, scenario_reserved_ports
from .log_prompt import build_log_review_prompt
from .preflight import run_preflight
from .prompt_meta import COPIED_CONTEXT_CLASSES, read_prompt_metadata
from .report import render_run_report
from .runs import init_run
from .scenario import Scenario, load_run_scenario, load_scenario
from .schema import SimulationEvent, Track, append_event, utc_now_iso
from .workerbee_stage import patch_stage


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
    if args.subcommand == "init-run":
        init_run(paths, args.run_id, scenario=scenario)
        print(paths.runs_dir / args.run_id)
        return 0
    if args.subcommand == "record-prompt":
        return _cmd_record_prompt(paths, args.run_id, args.track, args.prompt_file)
    if args.subcommand == "record-command":
        return _cmd_record_command(paths, args)
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
    init = sub.add_parser("init-run")
    init.add_argument("--run-id", required=True)
    prompt = sub.add_parser("record-prompt")
    prompt.add_argument("--run-id", required=True)
    prompt.add_argument("--track", choices=["plain-codex", "workerbee-codex"], required=True)
    prompt.add_argument("--prompt-file", type=Path, required=True)
    command = sub.add_parser("record-command")
    command.add_argument("--run-id", required=True)
    command.add_argument("--track", choices=["plain-codex", "workerbee-codex"], required=True)
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
    command_text = command.add_mutually_exclusive_group(required=True)
    command_text.add_argument("--command", dest="command_text")
    command_text.add_argument("--command-file", type=Path)
    touch = sub.add_parser("record-touch")
    touch.add_argument("--run-id", required=True)
    touch.add_argument("--track", choices=["plain-codex", "workerbee-codex"], required=True)
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
    codex_checkpoint.add_argument(
        "--track", choices=["plain-codex", "workerbee-codex"], required=True
    )
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
    ingest.add_argument("--track", choices=["plain-codex", "workerbee-codex"], required=True)
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
        "violating_containers": [
            {
                "id": container.container_id,
                "name": container.name,
                "ports": container.ports,
            }
            for container in result.containers
            if any(container.name in finding.message for finding in result.findings)
        ],
        "findings": [
            {"severity": finding.severity, "message": finding.message}
            for finding in result.findings
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0 if result.ok else 1


def _cmd_record_prompt(paths, run_id: str, track: Track, prompt_file: Path) -> int:
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
    }
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


def _cmd_record_touch(paths, args: argparse.Namespace) -> int:
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
    codex_home = args.codex_home or run_root / "codex-home"
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


if __name__ == "__main__":
    raise SystemExit(main())
