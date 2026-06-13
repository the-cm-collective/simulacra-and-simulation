from __future__ import annotations

import argparse
import json
from pathlib import Path

from .caddy_preflight import check_workerbee_caddy_routes
from .codex_events import normalize_codex_jsonl
from .config import default_paths
from .context_prompt import build_context_review_prompt
from .html_export import export_run_html
from .k1s_preflight import check_k1s_dev_a_ingress
from .log_prompt import build_log_review_prompt
from .preflight import run_preflight
from .report import render_run_report
from .runs import init_run
from .scenario import Scenario, load_run_scenario, load_scenario
from .schema import SimulationEvent, Track, append_event
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
    if args.subcommand == "ingest-codex":
        return _cmd_ingest_codex(paths, args.run_id, args.track, args.jsonl)
    if args.subcommand == "patch-workerbee-stage":
        _run_paths, run_scenario = _resolve_run_context(paths, scenario, args.run_id)
        return _cmd_patch_workerbee_stage(args, run_scenario)
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
    context_prompt = sub.add_parser("build-context-review-prompt")
    context_prompt.add_argument("--output", type=Path, required=True)
    context_prompt.add_argument("--title", required=True)
    context_prompt.add_argument("--instruction", required=True)
    context_prompt.add_argument("--context-file", type=Path, action="append", required=True)
    context_prompt.add_argument("--context-label", default="Context")
    context_prompt.add_argument("--max-bytes-per-file", type=int, default=120_000)
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
    report = sub.add_parser("render-report")
    report.add_argument("--run-id", required=True)
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
            payload={"prompt_file": str(prompt_file), "prompt": prompt_text},
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
    )
    print(output)
    return 0


def _cmd_ingest_codex(paths, run_id: str, track: Track, jsonl: Path) -> int:
    event_path = paths.runs_dir / run_id / track / "events.jsonl"
    events = normalize_codex_jsonl(jsonl, run_id=run_id, track=track)
    for event in events:
        append_event(event_path, event)
    print(f"ingested {len(events)} events")
    return 0


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


def _parse_env_updates(values: list[str]) -> dict[str, str]:
    updates: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--env must use NAME=value-template: {value}")
        name, template = value.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"--env name is empty: {value}")
        updates[name] = template
    return updates


if __name__ == "__main__":
    raise SystemExit(main())
