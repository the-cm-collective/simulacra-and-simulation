from __future__ import annotations

import argparse
from pathlib import Path

from .codex_events import normalize_codex_jsonl
from .config import default_paths
from .preflight import run_preflight
from .report import render_run_report
from .runs import init_run
from .schema import SimulationEvent, append_event


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = default_paths(args.repo_root)
    if args.command == "preflight":
        return _cmd_preflight(paths)
    if args.command == "init-run":
        init_run(paths, args.run_id)
        print(paths.runs_dir / args.run_id)
        return 0
    if args.command == "record-prompt":
        return _cmd_record_prompt(paths, args.run_id, args.track, args.prompt_file)
    if args.command == "ingest-codex":
        return _cmd_ingest_codex(paths, args.run_id, args.track, args.jsonl)
    if args.command == "render-report":
        return _cmd_render_report(paths, args.run_id)
    parser.error(f"unknown command: {args.command}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="simctl")
    parser.add_argument("--repo-root", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    init = sub.add_parser("init-run")
    init.add_argument("--run-id", required=True)
    prompt = sub.add_parser("record-prompt")
    prompt.add_argument("--run-id", required=True)
    prompt.add_argument("--track", choices=["plain-codex", "workerbee-codex"], required=True)
    prompt.add_argument("--prompt-file", type=Path, required=True)
    ingest = sub.add_parser("ingest-codex")
    ingest.add_argument("--run-id", required=True)
    ingest.add_argument("--track", choices=["plain-codex", "workerbee-codex"], required=True)
    ingest.add_argument("--jsonl", type=Path, required=True)
    report = sub.add_parser("render-report")
    report.add_argument("--run-id", required=True)
    return parser


def _cmd_preflight(paths) -> int:
    checks = run_preflight(paths)
    width = max(len(check.name) for check in checks)
    for check in checks:
        status = "ok" if check.ok else "fail"
        print(f"{status:4} {check.name:<{width}} {check.detail}")
    return 0 if all(check.ok for check in checks) else 1


def _cmd_record_prompt(paths, run_id: str, track: str, prompt_file: Path) -> int:
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


def _cmd_ingest_codex(paths, run_id: str, track: str, jsonl: Path) -> int:
    event_path = paths.runs_dir / run_id / track / "events.jsonl"
    events = normalize_codex_jsonl(jsonl, run_id=run_id, track=track)
    for event in events:
        append_event(event_path, event)
    print(f"ingested {len(events)} events")
    return 0


def _cmd_render_report(paths, run_id: str) -> int:
    run_root = paths.runs_dir / run_id
    report = render_run_report(run_root)
    output = run_root / "report.md"
    output.write_text(report + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
