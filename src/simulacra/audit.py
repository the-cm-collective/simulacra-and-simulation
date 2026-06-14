from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .metrics import REQUIRED_EVIDENCE_PHASES, duration_window, track_metrics
from .runs import TRACKS
from .schema import SCHEMA_VERSION, SimulationEvent, utc_now_iso

Severity = Literal["error", "warning", "info"]

KNOWN_EVENT_TYPES = {
    "ae_command",
    "checkpoint",
    "codex_event",
    "codex_event_parse_error",
    "command",
    "evidence",
    "human_action",
    "human_prompt",
    "protocol_violation",
    "workerbee_tool",
}
COMMAND_EVENT_TYPES = {"ae_command", "command", "human_action", "workerbee_tool"}
PLAIN_MIN_PROMPTS = 4
PLAIN_MIN_LOCAL_LOG_BYTES = 25_000
PLAIN_MIN_LOCAL_LOG_SOURCES = 4
PLAIN_MIN_K1S_DOC_BYTES = 30_000
PLAIN_MIN_K1S_DOC_SOURCES = 3
CONTEXT_MANAGEMENT_PROMPT_CHARS = 30_000
CONTEXT_MANAGEMENT_TURN_INPUT_TOKENS = 40_000
WORKERBEE_SINGLE_PROMPT_INPUT_TOKEN_MAX = 20_000
WORKERBEE_TOKEN_SANITY_WAIVERS = {
    "workerbee.token_sanity_check",
    "workerbee_token_sanity",
}
ENVIRONMENT_REPAIR_WAIVERS = {
    "environment.repair_noise",
    "environment_repair_noise",
}
CORE_METRIC_WAIVERS = {
    "comparison.plain_core_metric_win",
    "plain_core_metric_win",
}
SECRET_PATTERNS = (  # noqa: S105 - these are detection regexes, not credentials.
    re.compile(r"\b(?:sk|gh[pousr])-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"(?i)\b(?:AE|K1S|WORKERBEE|OPENAI|GITHUB)_[A-Z0-9_]*TOKEN\s*[:=]\s*"
        r"[A-Za-z0-9._~+/=-]{24,}"
    ),
)


@dataclass(frozen=True)
class AuditFinding:
    severity: Severity
    check_id: str
    message: str
    track: str | None = None
    evidence_ref: str | None = None
    remediation: str | None = None


@dataclass(frozen=True)
class AuditReport:
    run_id: str
    profile: str
    generated_at: str
    accepted: bool
    summary: dict[str, int]
    runtime: dict[str, dict[str, object]]
    findings: list[AuditFinding]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "profile": self.profile,
            "generated_at": self.generated_at,
            "accepted": self.accepted,
            "summary": self.summary,
            "runtime": self.runtime,
            "findings": [asdict(finding) for finding in self.findings],
        }


@dataclass(frozen=True)
class CoreMetricSpec:
    label: str
    value_fn: Callable[[object], float | int | None]
    unit: str = "count"


CORE_METRIC_SPECS = (
    CoreMetricSpec("realistic runtime", lambda metrics: metrics.duration.seconds, "duration"),
    CoreMetricSpec("operator touches", lambda metrics: metrics.operator_touches),
    CoreMetricSpec("human commands", lambda metrics: metrics.human_commands),
    CoreMetricSpec(
        "cumulative billed input tokens", lambda metrics: metrics.input_tokens, "tokens"
    ),
    CoreMetricSpec(
        "max turn input tokens", lambda metrics: metrics.max_turn_input_tokens, "tokens"
    ),
    CoreMetricSpec(
        "prompt/context bytes",
        lambda metrics: metrics.prompt_bytes + metrics.copied_context_bytes,
        "bytes",
    ),
)


def audit_run(run_root: Path, *, profile: str = "public-tech-report") -> AuditReport:
    run_root = run_root.resolve()
    findings: list[AuditFinding] = []
    manifest = _read_json(run_root / "manifest.json", findings, "manifest.json")
    run_id = str(manifest.get("run_id") or run_root.name)
    legacy_manifest = "scenario" not in manifest and bool(manifest.get("padawan_root"))
    strict = not legacy_manifest

    events_by_track = {
        track: _read_track_events(run_root, run_id, track, findings) for track in TRACKS
    }

    _check_manifest(manifest, run_root, legacy_manifest, findings)
    for track, events in events_by_track.items():
        _check_event_integrity(track, events, findings)
        _check_codex_usage(track, events, findings)
        _check_workerbee_token_sanity(track, events, strict, findings)
        _check_runtime_measurement(track, events, findings)
        _check_codex_isolation_policy(track, events, strict, findings)
        _check_checkpoint_contract(track, events, strict, findings)
        _check_plain_realism(track, events, strict, findings)
        _check_runtime_policy(track, events, strict, findings)
        _check_evidence(run_root, track, events, findings)
        _check_environment_repairs(track, events, strict, findings)
    _check_secret_hygiene(run_root, findings)
    if strict and _finding_summary(findings)["error"] == 0:
        _check_core_metric_expectations(events_by_track, findings)

    runtime = _runtime_summary(events_by_track)
    summary = _finding_summary(findings)
    report = AuditReport(
        run_id=run_id,
        profile=profile,
        generated_at=utc_now_iso(),
        accepted=summary["error"] == 0,
        summary=summary,
        runtime=runtime,
        findings=sorted(
            findings,
            key=lambda item: (_severity_rank(item.severity), item.track or "", item.check_id),
        ),
    )
    return report


def write_audit_report(run_root: Path, *, profile: str = "public-tech-report") -> AuditReport:
    report = audit_run(run_root, profile=profile)
    (run_root / "audit.json").write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_root / "audit.md").write_text(render_audit_markdown(report) + "\n", encoding="utf-8")
    return report


def read_audit_report(run_root: Path) -> dict[str, object]:
    path = run_root / "audit.json"
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def render_audit_markdown(report: AuditReport | dict[str, object]) -> str:
    data = report.to_dict() if isinstance(report, AuditReport) else report
    accepted = bool(data.get("accepted"))
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    findings = data.get("findings") if isinstance(data.get("findings"), list) else []
    lines = [
        "## Audit Status",
        "",
        f"- Profile: `{data.get('profile', 'unknown')}`",
        f"- Status: {'accepted' if accepted else 'blocked'}",
        f"- Errors: {summary.get('error', 0)}",
        f"- Warnings: {summary.get('warning', 0)}",
        f"- Info: {summary.get('info', 0)}",
        f"- Generated: `{data.get('generated_at', 'unknown')}`",
        "",
    ]
    if not findings:
        lines.extend(["No audit findings.", ""])
        return "\n".join(lines)
    lines.extend(["| Severity | Check | Track | Finding |", "| --- | --- | --- | --- |"])
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        detail = str(finding.get("message") or "")
        if finding.get("remediation"):
            detail = f"{detail} Remediation: {finding['remediation']}"
        if finding.get("evidence_ref"):
            detail = f"{detail} Evidence: `{finding['evidence_ref']}`"
        lines.append(
            "| "
            f"{finding.get('severity', '')} | "
            f"`{finding.get('check_id', '')}` | "
            f"{finding.get('track') or 'run'} | "
            f"{detail} |"
        )
    lines.append("")
    return "\n".join(lines)


def _check_manifest(
    manifest: dict[str, object],
    run_root: Path,
    legacy_manifest: bool,
    findings: list[AuditFinding],
) -> None:
    if not manifest:
        _add(
            findings,
            "error",
            "manifest.missing",
            "Run manifest is missing or not a JSON object.",
            ref="manifest.json",
            remediation="Initialize or reconstruct the run manifest before auditing.",
        )
        return

    for key in ("run_id", "created_at", "tracks", "runtime_policy"):
        if key not in manifest:
            _add(
                findings,
                "error",
                f"manifest.missing_{key}",
                f"Run manifest is missing required field `{key}`.",
                ref="manifest.json",
            )

    if legacy_manifest:
        _add(
            findings,
            "warning",
            "manifest.legacy_scenario_fallback",
            "Manifest predates scenario snapshots; reports infer Padawan defaults for review.",
            ref="manifest.json",
            remediation=(
                "Use `simctl init-run` from the scenario-aware harness for public baselines."
            ),
        )
        return

    scenario = manifest.get("scenario")
    if not isinstance(scenario, dict):
        _add(
            findings,
            "error",
            "manifest.missing_scenario",
            "Public-report runs must include a frozen scenario snapshot.",
            ref="manifest.json",
            remediation=(
                "Create the run with `simctl --scenario ... init-run` or the built-in scenario."
            ),
        )
        return

    target = scenario.get("target") if isinstance(scenario.get("target"), dict) else {}
    required_manifest_values = {
        "target_label": manifest.get("target_label"),
        "target_root": manifest.get("target_root"),
        "feature_prompt": manifest.get("feature_prompt"),
        "k1s_root": manifest.get("k1s_root"),
        "workerbee_root": manifest.get("workerbee_root"),
        "scenario.name": scenario.get("name"),
        "scenario.source": scenario.get("source"),
        "scenario.target.label": target.get("label"),
        "scenario.target.repo_root": target.get("repo_root"),
        "scenario.target.feature_prompt": target.get("feature_prompt"),
    }
    for key, value in required_manifest_values.items():
        if value in {None, ""}:
            _add(
                findings,
                "error",
                f"manifest.missing_{key.replace('.', '_')}",
                f"Run manifest is missing `{key}`.",
                ref="manifest.json",
            )

    for key in ("preflight", "k1s_ingress", "evidence", "workerbee_stage"):
        if not isinstance(scenario.get(key), dict) or not scenario.get(key):
            _add(
                findings,
                "error",
                f"manifest.missing_{key}",
                f"Scenario snapshot is missing simulation setting group `{key}`.",
                ref="manifest.json",
            )

    target_root = manifest.get("target_root")
    if target_root and not Path(str(target_root)).exists():
        _add(
            findings,
            "warning",
            "manifest.target_repo_unavailable",
            "Target repo path recorded in manifest is not present on this host.",
            ref=str(target_root),
        )

    if run_root.name != str(manifest.get("run_id")):
        _add(
            findings,
            "warning",
            "manifest.run_id_path_mismatch",
            "Run directory name differs from manifest run_id.",
            ref="manifest.json",
        )


def _check_event_integrity(
    track: str,
    events: list[SimulationEvent],
    findings: list[AuditFinding],
) -> None:
    if not events:
        _add(
            findings,
            "error",
            "events.missing_track_stream",
            "Track event stream is empty.",
            track=track,
            ref=f"{track}/events.jsonl",
        )
        return

    last_timestamp: datetime | None = None
    for index, event in enumerate(events, start=1):
        ref = f"{track}/events.jsonl:{index}"
        if event.schema_version != SCHEMA_VERSION:
            _add(
                findings,
                "error",
                "events.schema_version",
                f"Event uses unexpected schema version `{event.schema_version}`.",
                track=track,
                ref=ref,
            )
        if event.track != track:
            _add(
                findings,
                "error",
                "events.track_mismatch",
                f"Event track `{event.track}` does not match file track `{track}`.",
                track=track,
                ref=ref,
            )
        if event.event_type not in KNOWN_EVENT_TYPES:
            _add(
                findings,
                "warning",
                "events.unknown_type",
                f"Event type `{event.event_type}` is not part of the public metric schema.",
                track=track,
                ref=ref,
            )
        timestamp = _parse_timestamp(event.timestamp)
        if timestamp is None:
            _add(
                findings,
                "error",
                "events.invalid_timestamp",
                f"Event timestamp `{event.timestamp}` is not parseable.",
                track=track,
                ref=ref,
            )
        elif last_timestamp and timestamp < last_timestamp:
            _add(
                findings,
                "warning",
                "events.timestamp_out_of_order",
                "Event timestamp is earlier than the previous event in the stream.",
                track=track,
                ref=ref,
            )
        if timestamp is not None:
            last_timestamp = timestamp

        _check_event_source(event, track, ref, findings)
        _check_timing_payload(event, track, ref, findings)
        if event.event_type == "protocol_violation":
            _add(
                findings,
                "error",
                "protocol.recorded_violation",
                event.summary,
                track=track,
                ref=ref,
                remediation="Rerun from the last clean checkpoint after removing the violation.",
            )


def _check_event_source(
    event: SimulationEvent,
    track: str,
    ref: str,
    findings: list[AuditFinding],
) -> None:
    expected = {
        "ae_command": {"ae"},
        "checkpoint": {"simctl"},
        "codex_event": {"codex-jsonl"},
        "codex_event_parse_error": {"codex-jsonl"},
        "human_action": {"human"},
        "human_prompt": {"human"},
        "workerbee_tool": {"workerbee"},
    }.get(event.event_type)
    if expected and event.source not in expected:
        _add(
            findings,
            "error",
            "events.source_mismatch",
            f"`{event.event_type}` event has source `{event.source}`; expected {sorted(expected)}.",
            track=track,
            ref=ref,
        )
    if event.event_type == "command" and event.source == "workerbee":
        _add(
            findings,
            "warning",
            "classification.command_source_workerbee",
            (
                "`command` with source `workerbee` is ambiguous; "
                "WorkerBee actions should be `workerbee_tool`."
            ),
            track=track,
            ref=ref,
        )


def _check_timing_payload(
    event: SimulationEvent,
    track: str,
    ref: str,
    findings: list[AuditFinding],
) -> None:
    if event.event_type not in COMMAND_EVENT_TYPES:
        return
    started_at = _parse_timestamp(str(event.payload.get("started_at") or ""))
    ended_at = _parse_timestamp(str(event.payload.get("ended_at") or ""))
    duration = event.payload.get("duration_seconds")
    if started_at and ended_at and ended_at < started_at:
        _add(
            findings,
            "error",
            "timing.ended_before_started",
            "Command/action ended before it started.",
            track=track,
            ref=ref,
        )
    if started_at is None and event.payload.get("started_at"):
        _add(
            findings,
            "warning",
            "timing.invalid_started_at",
            "Command/action started_at is not parseable.",
            track=track,
            ref=ref,
        )
    if ended_at is None and event.payload.get("ended_at"):
        _add(
            findings,
            "warning",
            "timing.invalid_ended_at",
            "Command/action ended_at is not parseable.",
            track=track,
            ref=ref,
        )
    if duration is not None:
        try:
            if float(duration) < 0:
                raise ValueError
        except (TypeError, ValueError):
            _add(
                findings,
                "warning",
                "timing.invalid_duration",
                "Command/action duration_seconds is not a non-negative number.",
                track=track,
                ref=ref,
            )


def _check_codex_usage(
    track: str,
    events: list[SimulationEvent],
    findings: list[AuditFinding],
) -> None:
    prompts = [event for event in events if event.event_type == "human_prompt"]
    codex_events = [event for event in events if event.event_type == "codex_event"]
    started = [event for event in codex_events if event.payload.get("raw_type") == "turn.started"]
    usage = [event for event in codex_events if isinstance(event.payload.get("usage"), dict)]
    parse_errors = [event for event in events if event.event_type == "codex_event_parse_error"]

    for event in parse_errors:
        _add(
            findings,
            "error",
            "codex.jsonl_parse_error",
            event.summary,
            track=track,
            ref=_event_ref(track, events, event),
        )

    if prompts and not codex_events:
        _add(
            findings,
            "error",
            "codex.missing_transcript",
            "Track has human prompts but no ingested Codex JSONL events.",
            track=track,
            remediation="Run `simctl ingest-codex` for every checkpoint transcript.",
        )
    if len(usage) < len(prompts):
        _add(
            findings,
            "error",
            "codex.prompt_usage_mismatch",
            f"Track has {len(prompts)} prompt(s) but only {len(usage)} usage snapshot(s).",
            track=track,
            remediation="Ingest the missing Codex JSONL transcript or rerun the checkpoint.",
        )
    if len(started) != len(usage):
        _add(
            findings,
            "error",
            "codex.turn_usage_mismatch",
            f"Track has {len(started)} turn.started event(s) and {len(usage)} usage snapshot(s).",
            track=track,
        )

    fingerprints: dict[tuple[object, ...], int] = {}
    for event in codex_events:
        if not event.payload.get("source_sha256"):
            continue
        fingerprint = _codex_fingerprint(event)
        fingerprints[fingerprint] = fingerprints.get(fingerprint, 0) + 1
    duplicates = sum(count - 1 for count in fingerprints.values() if count > 1)
    if duplicates:
        _add(
            findings,
            "error",
            "codex.duplicate_event_fingerprint",
            f"Detected {duplicates} duplicate Codex event fingerprint(s).",
            track=track,
            remediation="Recreate the event stream from source JSONL instead of re-ingesting.",
        )

    for prompt in prompts:
        prompt_file = prompt.payload.get("prompt_file")
        prompt_text = str(prompt.payload.get("prompt") or "")
        if not prompt_text.strip():
            _add(
                findings,
                "error",
                "codex.empty_prompt",
                "Human prompt event has no prompt text.",
                track=track,
                ref=_event_ref(track, events, prompt),
            )
        if (
            prompt_file
            and not _resolve_run_path(prompt_file, _track_run_root(events, track)).exists()
        ):
            _add(
                findings,
                "warning",
                "codex.prompt_file_missing",
                f"Prompt file `{prompt_file}` referenced by event is not present.",
                track=track,
                ref=_event_ref(track, events, prompt),
            )


def _check_runtime_measurement(
    track: str,
    events: list[SimulationEvent],
    findings: list[AuditFinding],
) -> None:
    metrics = track_metrics(events)
    if metrics.lane_idle_seconds >= 120:
        _add(
            findings,
            "warning",
                "runtime.checkpoint_idle_excluded",
                (
                    "Track has checkpoint setup idle before the first measured work event; "
                    f"{metrics.lane_idle_label} is excluded from realistic runtime."
                ),
            track=track,
            remediation=(
                "For paired clean baselines, start track checkpoint prompts as close "
                "together as possible or treat the package as diagnostic."
            ),
        )


def _check_workerbee_token_sanity(
    track: str,
    events: list[SimulationEvent],
    strict: bool,
    findings: list[AuditFinding],
) -> None:
    if track != "workerbee-codex" or not strict:
        return
    metrics = track_metrics(events)
    if metrics.prompts != 1:
        return
    if metrics.max_turn_input_tokens <= WORKERBEE_SINGLE_PROMPT_INPUT_TOKEN_MAX:
        return
    if _has_audit_waiver(events, WORKERBEE_TOKEN_SANITY_WAIVERS):
        _add(
            findings,
            "warning",
            "workerbee.token_sanity_waived",
            (
                "WorkerBee track exceeded the one-prompt token sanity threshold, "
                "but an explicit audit waiver was recorded."
            ),
            track=track,
        )
        return
    _add(
        findings,
        "error",
        "workerbee.token_sanity_check",
        (
            "WorkerBee track has a single human prompt but max turn input usage "
            f"is {metrics.max_turn_input_tokens} tokens; accepted clean baselines "
            f"expect about 16k and the strict gate allows up to "
            f"{WORKERBEE_SINGLE_PROMPT_INPUT_TOKEN_MAX}."
        ),
        track=track,
        remediation=(
            "Inspect Codex transcript/session isolation and rerun the WorkerBee lane, "
            "or record an explicit waiver explaining why the token growth is expected."
        ),
    )


def _check_environment_repairs(
    track: str,
    events: list[SimulationEvent],
    strict: bool,
    findings: list[AuditFinding],
) -> None:
    if not strict:
        return
    repairs = _environment_repair_events(events)
    if not repairs:
        return
    details = ", ".join(sorted({kind for _index, _event, kind in repairs}))
    if _has_audit_waiver(events, ENVIRONMENT_REPAIR_WAIVERS):
        _add(
            findings,
            "warning",
            "environment.repair_waived",
            (
                f"Track contains {len(repairs)} environment repair event(s) "
                f"({details}), but an explicit audit waiver was recorded."
            ),
            track=track,
            ref=f"{track}/events.jsonl:{repairs[0][0] + 1}",
        )
        return
    _add(
        findings,
        "error",
        "environment.repair_noise",
        (
            f"Track contains {len(repairs)} environment repair event(s) "
            f"({details}); clean paired baselines must rerun after the "
            "environment is repaired."
        ),
        track=track,
        ref=f"{track}/events.jsonl:{repairs[0][0] + 1}",
        remediation=(
            "Fix the underlying Caddy, ingress route, controller routing, or "
            "service-port issue outside the measured run, then rerun both lanes."
        ),
    )


def _check_core_metric_expectations(
    events_by_track: dict[str, list[SimulationEvent]],
    findings: list[AuditFinding],
) -> None:
    plain_events = events_by_track.get("plain-codex", [])
    workerbee_events = events_by_track.get("workerbee-codex", [])
    if not plain_events or not workerbee_events:
        return
    plain = track_metrics(plain_events)
    workerbee = track_metrics(workerbee_events)
    plain_wins = []
    for spec in CORE_METRIC_SPECS:
        plain_value = spec.value_fn(plain)
        workerbee_value = spec.value_fn(workerbee)
        if plain_value is None or workerbee_value is None:
            continue
        if float(plain_value) < float(workerbee_value):
            plain_wins.append(
                f"{spec.label} "
                f"({_format_metric_value(plain_value, spec.unit)} plain vs "
                f"{_format_metric_value(workerbee_value, spec.unit)} WorkerBee)"
            )
    if not plain_wins:
        return
    all_events = plain_events + workerbee_events
    waiver = _has_audit_waiver(all_events, CORE_METRIC_WAIVERS)
    _add(
        findings,
        "warning" if waiver else "error",
        "comparison.plain_core_metric_win",
        (
            "Plain Codex beat WorkerBee on strict core metric(s): "
            + "; ".join(plain_wins)
            + ". This is review-required because realistic strict use should "
            "favor WorkerBee on core process-cost categories."
        ),
        remediation=(
            "Inspect lane isolation, copied context, environment repair noise, "
            "and transcript usage. Rerun the paired baseline unless the result "
            "has an explicit documented waiver."
        ),
    )


def _check_codex_isolation_policy(
    track: str,
    events: list[SimulationEvent],
    strict: bool,
    findings: list[AuditFinding],
) -> None:
    no_tool_prompt_seen = False
    reported_tool_leaks: set[str] = set()
    for index, event in enumerate(events, start=1):
        ref = f"{track}/events.jsonl:{index}"
        command = str(event.payload.get("command") or "")
        if event.event_type == "command" and event.source == "human" and "codex exec" in command:
            mode = str(event.payload.get("codex_invocation_mode") or "isolated")
            required = ["--ignore-rules"]
            if mode in {"start", "resume"}:
                required.append("--ignore-user-config")
            else:
                required.append("--ephemeral")
            missing = [flag for flag in required if flag not in command]
            if missing:
                _add(
                    findings,
                    "error" if strict else "warning",
                    "codex.missing_isolation_flags",
                    (
                        "Measured Codex CLI checkpoint was submitted without "
                        f"{' and '.join(missing)}; transcript token usage can include "
                        "ambient rules, user configuration, or stale session state."
                    ),
                    track=track,
                    ref=ref,
                    remediation=(
                        "Rerun isolated probes with `--ephemeral --ignore-rules`, "
                        "or run-scoped checkpoints with `--ignore-rules "
                        "--ignore-user-config` and recorded session metadata."
                    ),
                )

        if event.event_type == "human_prompt" and _prompt_forbids_tools(event):
            no_tool_prompt_seen = True
            continue

        if not no_tool_prompt_seen or event.event_type != "codex_event":
            continue
        item_type = str(event.payload.get("item_type") or "")
        raw_type = str(event.payload.get("raw_type") or "")
        if item_type not in {"command_execution", "mcp_tool_call"}:
            continue
        if raw_type not in {"item.started", "item.completed"}:
            continue
        if item_type in reported_tool_leaks:
            continue
        reported_tool_leaks.add(item_type)
        label = "shell command" if item_type == "command_execution" else "MCP tool call"
        _add(
            findings,
            "error" if strict else "warning",
            "codex.no_tool_checkpoint_violation",
            (
                f"Codex emitted a {label} after a checkpoint prompt that forbade "
                "tool use, file reads, or command execution."
            ),
            track=track,
            ref=ref,
            remediation=(
                "Rerun the checkpoint with isolated no-tool settings and reject "
                "transcripts that contain command_execution or mcp_tool_call items."
            ),
        )


def _check_checkpoint_contract(
    track: str,
    events: list[SimulationEvent],
    strict: bool,
    findings: list[AuditFinding],
) -> None:
    prompts = [event for event in events if event.event_type == "human_prompt"]
    prompt_text = "\n".join(str(event.payload.get("prompt") or "") for event in prompts)
    if track == "plain-codex":
        if len(prompts) < 3:
            _add(
                findings,
                "error" if strict else "warning",
                "checkpoint.plain_prompt_minimum",
                (
                    "Plain track should include implementation/checklist, copied-log, "
                    "and k1s-doc checkpoints."
                ),
                track=track,
            )
        has_copy_touch = any(
            event.event_type == "human_action" and event.payload.get("kind") == "copy_logs"
            for event in events
        )
        if not has_copy_touch:
            _add(
                findings,
                "error",
                "checkpoint.plain_missing_copy_logs_touch",
                "Plain track is missing the required copied-log human action.",
                track=track,
            )
        if "copied" not in prompt_text.lower() or "log" not in prompt_text.lower():
            _add(
                findings,
                "error",
                "checkpoint.plain_missing_raw_log_prompt",
                "Plain track prompts do not show the required raw-log review checkpoint.",
                track=track,
            )
        if "k1s docs" not in prompt_text.lower() and "k1s doc" not in prompt_text.lower():
            _add(
                findings,
                "error",
                "checkpoint.plain_missing_k1s_docs_prompt",
                "Plain track prompts do not show the required k1s documentation checkpoint.",
                track=track,
            )
    if track == "workerbee-codex":
        if not prompts:
            _add(
                findings,
                "error",
                "checkpoint.workerbee_missing_prompt",
                "WorkerBee track is missing the measured human prompt.",
                track=track,
            )
        if not any(event.event_type == "workerbee_tool" for event in events):
            _add(
                findings,
                "error",
                "checkpoint.workerbee_missing_tool_actions",
                "WorkerBee track is missing WorkerBee tool/action events.",
                track=track,
            )
        if any(
            event.event_type == "human_action" and event.payload.get("kind") == "copy_logs"
            for event in events
        ):
            _add(
                findings,
                "warning",
                "checkpoint.workerbee_raw_log_prompt_tax",
                (
                    "WorkerBee track includes a raw-log copy action; "
                    "note this weakens the intended contrast."
                ),
                track=track,
            )
        has_targeted_status = any(
            event.event_type == "workerbee_tool"
            and _contains_any(event, ("status", "log", "probe", "inspect", "validate"))
            for event in events
        )
        if not has_targeted_status:
            _add(
                findings,
                "error",
                "checkpoint.workerbee_missing_targeted_status",
                "WorkerBee track does not show targeted status/log/probe validation.",
                track=track,
            )


def _check_plain_realism(
    track: str,
    events: list[SimulationEvent],
    strict: bool,
    findings: list[AuditFinding],
) -> None:
    if track != "plain-codex" or not strict:
        return
    prompts = [event for event in events if event.event_type == "human_prompt"]
    if len(prompts) < PLAIN_MIN_PROMPTS:
        _add(
            findings,
            "error",
            "plain_realism.prompt_minimum",
            (
                f"Plain track has {len(prompts)} prompt(s); strict realism requires "
                f"at least {PLAIN_MIN_PROMPTS} including a final/repair checkpoint."
            ),
            track=track,
            remediation=(
                "Rerun the plain lane with run-scoped Codex resume and explicit "
                "local log, k1s docs, and repair/context-management checkpoints."
            ),
        )

    local_logs = _copied_context_stats(prompts, "local_logs")
    if local_logs["embedded"] < PLAIN_MIN_LOCAL_LOG_BYTES:
        severity: Severity = "error"
        if 0 < local_logs["available"] < PLAIN_MIN_LOCAL_LOG_BYTES:
            severity = "warning"
        _add(
            findings,
            severity,
            "plain_realism.insufficient_local_log_context",
            (
                "Plain local copied-log checkpoint embedded "
                f"{local_logs['embedded']} byte(s) from {local_logs['sources']} source(s); "
                f"strict realism expects at least {PLAIN_MIN_LOCAL_LOG_BYTES} bytes "
                f"from {PLAIN_MIN_LOCAL_LOG_SOURCES} sources when available."
            ),
            track=track,
        )
    elif local_logs["sources"] < PLAIN_MIN_LOCAL_LOG_SOURCES:
        _add(
            findings,
            "error",
            "plain_realism.insufficient_local_log_context",
            (
                "Plain local copied-log checkpoint used only "
                f"{local_logs['sources']} source(s); strict realism expects at least "
                f"{PLAIN_MIN_LOCAL_LOG_SOURCES}."
            ),
            track=track,
        )

    k1s_docs = _copied_context_stats(prompts, "k1s_docs")
    if k1s_docs["embedded"] < PLAIN_MIN_K1S_DOC_BYTES:
        severity = "error"
        if 0 < k1s_docs["available"] < PLAIN_MIN_K1S_DOC_BYTES:
            severity = "warning"
        _add(
            findings,
            severity,
            "plain_realism.insufficient_k1s_doc_context",
            (
                "Plain k1s docs checkpoint embedded "
                f"{k1s_docs['embedded']} byte(s) from {k1s_docs['sources']} source(s); "
                f"strict realism expects at least {PLAIN_MIN_K1S_DOC_BYTES} bytes "
                f"from {PLAIN_MIN_K1S_DOC_SOURCES} sources when available."
            ),
            track=track,
        )
    elif k1s_docs["sources"] < PLAIN_MIN_K1S_DOC_SOURCES:
        _add(
            findings,
            "error",
            "plain_realism.insufficient_k1s_doc_context",
            (
                "Plain k1s docs checkpoint used only "
                f"{k1s_docs['sources']} source(s); strict realism expects at least "
                f"{PLAIN_MIN_K1S_DOC_SOURCES}."
            ),
            track=track,
        )

    _check_plain_failed_command_repairs(events, track, findings)
    _check_plain_context_management(events, track, findings)
    _check_plain_session_model(events, track, findings)
    _check_plain_cert_tax(events, track, findings)


def _check_runtime_policy(
    track: str,
    events: list[SimulationEvent],
    strict: bool,
    findings: list[AuditFinding],
) -> None:
    for index, event in enumerate(events, start=1):
        command = str(event.payload.get("command") or "")
        text = f"{command}\n{event.summary}".lower()
        ref = f"{track}/events.jsonl:{index}"
        if track == "plain-codex":
            if event.event_type == "workerbee_tool" or "workerbee_v1_" in text:
                _add(
                    findings,
                    "error",
                    "policy.plain_workerbee_use",
                    "Plain track used WorkerBee tooling.",
                    track=track,
                    ref=ref,
                )
            if event.event_type in COMMAND_EVENT_TYPES and re.search(
                r"\bdocker(?:-compose)?\b",
                command.lower(),
            ):
                _add(
                    findings,
                    "error",
                    "policy.plain_docker_use",
                    "Plain track used Docker in measured local/runtime work.",
                    track=track,
                    ref=ref,
                )
        if track == "workerbee-codex":
            if event.event_type == "ae_command":
                _add(
                    findings,
                    "warning",
                    "policy.workerbee_ae_action",
                    (
                        "WorkerBee track used an AE action; explain why WorkerBee "
                        "could not perform it."
                    ),
                    track=track,
                    ref=ref,
                )
            if event.event_type == "command" and "podman" in text:
                _add(
                    findings,
                    "error" if strict else "warning",
                    "policy.workerbee_host_podman_fallback",
                    "WorkerBee track used a host Podman fallback command.",
                    track=track,
                    ref=ref,
                    remediation="Record an explicit waiver or rerun through WorkerBee/containerd.",
                )
            if "podman project" in text:
                _add(
                    findings,
                    "error",
                    "policy.workerbee_podman_project_runtime",
                    "WorkerBee track used the Podman-backed project runtime.",
                    track=track,
                    ref=ref,
                )
        if "subagent" in text or "spawn agent" in text:
            _add(
                findings,
                "error",
                "policy.subagent_use",
                "Baseline run references subagent use, which is forbidden.",
                track=track,
                ref=ref,
            )

    if track == "workerbee-codex":
        has_containerd_capability = any(
            event.event_type == "workerbee_tool"
            and _contains_any(event, ("capabilities", "runtime.selected", "containerd"))
            for event in events
        )
        if not has_containerd_capability:
            _add(
                findings,
                "error" if strict else "warning",
                "policy.workerbee_missing_containerd_capability",
                "WorkerBee track lacks a recorded containerd capability check.",
                track=track,
                remediation="Record `workerbee_v1_capabilities` or equivalent before measurement.",
            )


def _check_evidence(
    run_root: Path,
    track: str,
    events: list[SimulationEvent],
    findings: list[AuditFinding],
) -> None:
    metrics = track_metrics(events)
    for phase in REQUIRED_EVIDENCE_PHASES:
        if phase not in metrics.completeness:
            continue
        _add(
            findings,
            "error",
            f"evidence.missing_{phase.replace('-', '_')}",
            f"Track is missing required `{phase}` evidence.",
            track=track,
        )

    evidence_events = [event for event in events if event.event_type == "evidence"]
    for event in evidence_events:
        ref = _event_ref(track, events, event)
        artifacts = event.payload.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            _add(
                findings,
                "error",
                "evidence.missing_artifacts",
                "Evidence event has no artifact list.",
                track=track,
                ref=ref,
            )
        else:
            for artifact in artifacts:
                path = _resolve_run_path(artifact, run_root)
                if not path.exists():
                    _add(
                        findings,
                        "error",
                        "evidence.artifact_missing",
                        f"Evidence artifact is missing: {artifact}",
                        track=track,
                        ref=ref,
                    )
        summary_path = event.payload.get("summary_path")
        if summary_path:
            _check_evidence_summary(run_root, track, ref, summary_path, findings)
        else:
            _add(
                findings,
                "warning",
                "evidence.summary_missing",
                "Evidence event has no summary_path for feature assertions.",
                track=track,
                ref=ref,
            )

    if "k1s-dev-a" in metrics.evidence_phases:
        _check_final_ingress_gate(run_root, track, findings)


def _check_evidence_summary(
    run_root: Path,
    track: str,
    event_ref: str,
    summary_path: object,
    findings: list[AuditFinding],
) -> None:
    path = _resolve_run_path(summary_path, run_root)
    if not path.exists():
        _add(
            findings,
            "error",
            "evidence.summary_path_missing",
            f"Evidence summary does not exist: {summary_path}",
            track=track,
            ref=event_ref,
        )
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _add(
            findings,
            "error",
            "evidence.summary_parse_error",
            f"Evidence summary is not valid JSON: {exc}",
            track=track,
            ref=str(path),
        )
        return
    if data.get("data_channel") != "open":
        _add(
            findings,
            "error",
            "evidence.data_channel_not_open",
            "Evidence summary does not show an open data channel.",
            track=track,
            ref=str(path),
        )
    screenshots = data.get("screenshots")
    if not isinstance(screenshots, list) or len(screenshots) < 2:
        _add(
            findings,
            "error",
            "evidence.screenshots_incomplete",
            "Evidence summary does not include both Padawan/Jedi screenshots.",
            track=track,
            ref=str(path),
        )


def _check_final_ingress_gate(
    run_root: Path,
    track: str,
    findings: list[AuditFinding],
) -> None:
    command_dir = run_root / track / "commands"
    candidates = sorted(
        {
            *command_dir.glob("*ingress-final*.json"),
            *command_dir.glob("*ingress*gate*.json"),
        }
    )
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not data.get("ok"):
            continue
        probe_url = str(data.get("probe_url") or "")
        body_contains = str(data.get("probe_body_contains") or "")
        if "/peer" in probe_url and body_contains:
            return
    _add(
        findings,
        "error",
        "evidence.missing_final_peer_body_gate",
        "Final k1s-dev-a evidence has no passing `/peer` body gate artifact.",
        track=track,
        ref=str(command_dir),
        remediation=(
            "Run `simctl check-k1s-dev-a-ingress --probe-url <app>/peer "
            "--probe-body-contains <marker>`."
        ),
    )


def _check_secret_hygiene(run_root: Path, findings: list[AuditFinding]) -> None:
    scan_roots = [run_root / "manifest.json", run_root / "report.md"]
    scan_roots.extend(sorted(run_root.glob("*/events.jsonl")))
    scan_roots.extend(sorted(run_root.glob("*/prompts/*.md")))
    scan_roots.extend(sorted(run_root.glob("*/commands/*")))
    for path in scan_roots:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:250_000]
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                _add(
                    findings,
                    "error",
                    "secret.possible_secret_material",
                    "Audit found possible secret material in a public report input.",
                    ref=str(path),
                    remediation="Redact the artifact and rerun the measurement/export.",
                )
                break


def _runtime_summary(
    events_by_track: dict[str, list[SimulationEvent]],
) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for track, events in events_by_track.items():
        metrics = track_metrics(events)
        window = duration_window(events)
        action_seconds = 0.0
        timed_actions = 0
        missing_timing = 0
        repair_events = _environment_repair_events(events)
        repair_indexes = {index for index, _event, _kind in repair_events}
        repair_seconds = 0.0
        for event in events:
            if event.event_type not in COMMAND_EVENT_TYPES:
                continue
            seconds = _event_action_seconds(event)
            if seconds is None:
                missing_timing += 1
                continue
            action_seconds += seconds
            timed_actions += 1
        for index, event, _kind in repair_events:
            if index not in repair_indexes:
                continue
            seconds = _event_action_seconds(event)
            if seconds is not None:
                repair_seconds += seconds
        summary[track] = {
            "event_window_seconds": window.seconds,
            "event_window_label": window.label,
            "observed_runtime_seconds": metrics.observed_duration.seconds,
            "observed_runtime_label": metrics.observed_duration.label,
            "manual_time_tax_seconds": round(metrics.manual_time_tax_seconds, 3),
            "manual_time_tax_label": metrics.manual_time_tax_label,
            "adjusted_runtime_seconds": metrics.duration.seconds,
            "adjusted_runtime_label": metrics.duration.label,
            "checkpoint_idle_excluded_seconds": round(metrics.lane_idle_seconds, 3),
            "checkpoint_idle_excluded_label": metrics.lane_idle_label,
            "prompt_bytes": metrics.prompt_bytes,
            "max_prompt_bytes": metrics.max_prompt_bytes,
            "copied_context_bytes": metrics.copied_context_bytes,
            "copied_context_available_bytes": metrics.copied_context_available_bytes,
            "copied_context_sources": metrics.copied_context_sources,
            "copied_context_truncated_sources": metrics.copied_context_truncated_sources,
            "copied_context_by_class": metrics.copied_context_by_class,
            "prompt_metadata_count": metrics.prompt_metadata_count,
            "prompt_metadata_missing": metrics.prompt_metadata_missing,
            "context_management_actions": metrics.context_management_actions,
            "environment_repair_events": len(repair_events),
            "environment_repair_seconds": round(repair_seconds, 3),
            "environment_repair_label": _format_duration(repair_seconds),
            "environment_repair_kinds": sorted({kind for _index, _event, kind in repair_events}),
            "recorded_action_seconds": round(action_seconds, 3),
            "recorded_action_label": _format_duration(action_seconds),
            "timed_actions": timed_actions,
            "actions_missing_timing": missing_timing,
        }
    return summary


def _read_track_events(
    run_root: Path,
    run_id: str,
    track: str,
    findings: list[AuditFinding],
) -> list[SimulationEvent]:
    path = run_root / track / "events.jsonl"
    if not path.exists():
        _add(
            findings,
            "error",
            "events.missing_file",
            "Track event file is missing.",
            track=track,
            ref=f"{track}/events.jsonl",
        )
        return []
    events = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        ref = f"{track}/events.jsonl:{line_no}"
        try:
            event = SimulationEvent.from_json(line)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            _add(
                findings,
                "error",
                "events.parse_error",
                f"Could not parse event JSONL line: {exc}",
                track=track,
                ref=ref,
            )
            continue
        if event.run_id != run_id:
            _add(
                findings,
                "error",
                "events.run_id_mismatch",
                f"Event run_id `{event.run_id}` does not match manifest run_id `{run_id}`.",
                track=track,
                ref=ref,
            )
        events.append(event)
    return events


def _read_json(
    path: Path,
    findings: list[AuditFinding],
    ref: str,
) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _add(
            findings,
            "error",
            "json.parse_error",
            f"Could not parse JSON: {exc}",
            ref=ref,
        )
        return {}
    return value if isinstance(value, dict) else {}


def _resolve_run_path(value: object, run_root: Path) -> Path:
    path = Path(str(value or "")).expanduser()
    if path.is_absolute():
        return path
    candidates = [run_root / path]
    if len(run_root.parents) >= 3:
        candidates.append(run_root.parents[2] / path)
    candidates.append(path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _track_run_root(events: list[SimulationEvent], track: str) -> Path:
    for event in events:
        if event.event_type == "checkpoint":
            root = event.payload.get("track_root")
            if root:
                return Path(str(root)).parent
    return Path(".local") / "runs" / "<unknown>" / track


def _event_action_seconds(event: SimulationEvent) -> float | None:
    started = _parse_timestamp(str(event.payload.get("started_at") or ""))
    ended = _parse_timestamp(str(event.payload.get("ended_at") or ""))
    if started and ended:
        return max(0.0, (ended - started).total_seconds())
    duration = event.payload.get("duration_seconds")
    if duration is None:
        return None
    try:
        return max(0.0, float(duration))
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _codex_fingerprint(event: SimulationEvent) -> tuple[object, ...]:
    return (
        event.payload.get("source_sha256"),
        event.payload.get("line_no"),
        event.payload.get("raw_type"),
    )


def _contains_any(event: SimulationEvent, needles: tuple[str, ...]) -> bool:
    text = json.dumps(event.payload, sort_keys=True, default=str).lower()
    text = f"{text}\n{event.summary.lower()}"
    return any(needle in text for needle in needles)


def _environment_repair_events(
    events: list[SimulationEvent],
) -> list[tuple[int, SimulationEvent, str]]:
    repairs = []
    for index, event in enumerate(events):
        if event.event_type not in COMMAND_EVENT_TYPES:
            continue
        kind = _environment_repair_kind(event)
        if kind:
            repairs.append((index, event, kind))
    return repairs


def _environment_repair_kind(event: SimulationEvent) -> str | None:
    summary = event.summary.lower()
    text = json.dumps(event.payload, sort_keys=True, default=str).lower()
    text = f"{summary}\n{text}"
    if summary.startswith("final ") and "passed after" in summary:
        return None
    if "lane service ports" in summary or "lane-scoped" in summary:
        return None
    if any(
        needle in text
        for needle in (
            "stale caddy",
            "ambiguous site definition",
            "duplicate caddy",
            "duplicate site repair",
            "duplicate-site repair",
        )
    ):
        return "caddy-state"
    if "empty-body route finding" in text or "empty body route finding" in text:
        return "empty-body-ingress"
    if re.search(r"\b(?:patch|repair)\b.*\bservice ports?\b", summary):
        return "service-port-patch"
    if any(
        needle in text
        for needle in (
            "edge route repair",
            "edge gateway route sync",
            "route sync repair",
        )
    ):
        return "edge-route-sync"
    if "controller routing drift" in text or "leader controller" in text:
        return "controller-routing"
    return None


def _has_audit_waiver(events: list[SimulationEvent], waiver_ids: set[str]) -> bool:
    normalized = {waiver.lower() for waiver in waiver_ids}
    for event in events:
        payload = event.payload
        for key in ("audit_waiver", "waiver"):
            value = payload.get(key)
            if isinstance(value, str) and value.lower() in normalized:
                return True
        values = payload.get("audit_waivers")
        if isinstance(values, list) and any(
            isinstance(value, str) and value.lower() in normalized for value in values
        ):
            return True
        text = event.summary.lower()
        if any(f"waiver: {waiver}" in text for waiver in normalized):
            return True
    return False


def _copied_context_stats(
    prompts: list[SimulationEvent],
    context_class: str,
) -> dict[str, int]:
    embedded = 0
    available = 0
    sources = 0
    truncated = 0
    for prompt in prompts:
        metadata = prompt.payload.get("prompt_metadata")
        if not isinstance(metadata, dict):
            continue
        if metadata.get("copied_context_class") != context_class:
            continue
        embedded += int(metadata.get("total_embedded_bytes") or 0)
        available += int(metadata.get("total_available_bytes") or 0)
        sources += int(metadata.get("source_count") or 0)
        truncated += int(metadata.get("truncated_source_count") or 0)
    return {
        "embedded": embedded,
        "available": available,
        "sources": sources,
        "truncated": truncated,
    }


def _check_plain_failed_command_repairs(
    events: list[SimulationEvent],
    track: str,
    findings: list[AuditFinding],
) -> None:
    for index, event in enumerate(events):
        if event.event_type not in {"command", "ae_command"}:
            continue
        exit_code = event.payload.get("exit_code")
        if exit_code in {None, 0}:
            continue
        if _has_later_repair_prompt(events, index):
            continue
        if _has_later_transient_readiness_recovery(events, index, event):
            continue
        _add(
            findings,
            "error",
            "plain_realism.missing_failure_repair_prompt",
            (
                "Plain track has a failed command without a later copied-log/"
                "troubleshooting touch and measured Codex repair prompt."
            ),
            track=track,
            ref=f"{track}/events.jsonl:{index + 1}",
            remediation=(
                "Copy the relevant failure logs, record a touch, and submit a "
                "run-scoped Codex repair checkpoint before continuing."
            ),
        )


def _has_later_repair_prompt(events: list[SimulationEvent], failure_index: int) -> bool:
    touch_seen = False
    for event in events[failure_index + 1 :]:
        if event.event_type == "human_action" and event.payload.get("kind") in {
            "copy_logs",
            "troubleshoot",
        }:
            touch_seen = True
            continue
        if not touch_seen or event.event_type != "human_prompt":
            continue
        metadata = event.payload.get("prompt_metadata")
        prompt_text = str(event.payload.get("prompt") or "").lower()
        if isinstance(metadata, dict) and int(metadata.get("total_embedded_bytes") or 0) > 0:
            return True
        if any(needle in prompt_text for needle in ("failed", "failure", "error", "logs")):
            return True
    return False


def _has_later_transient_readiness_recovery(
    events: list[SimulationEvent],
    failure_index: int,
    failure: SimulationEvent,
) -> bool:
    text = f"{failure.summary}\n{failure.payload.get('command') or ''}".lower()
    if "status" not in text:
        return False
    if not any(needle in text for needle in ("--watch", "readiness", "wait")):
        return False

    manual_wait = False
    later_ready_status = False
    later_final_evidence = False
    for event in events[failure_index + 1 :]:
        event_text = f"{event.summary}\n{event.payload.get('command') or ''}".lower()
        if event.event_type == "human_action" and event.payload.get("kind") == "manual_wait":
            manual_wait = True
            continue
        if (
            event.event_type in COMMAND_EVENT_TYPES
            and event.payload.get("exit_code") == 0
            and "status" in event_text
            and any(needle in event_text for needle in ("ready", "wide", "events", "convergence"))
        ):
            later_ready_status = True
            continue
        if event.event_type == "evidence" and event.payload.get("phase") == "k1s-dev-a":
            later_final_evidence = True
    return manual_wait and later_ready_status and later_final_evidence


def _check_plain_context_management(
    events: list[SimulationEvent],
    track: str,
    findings: list[AuditFinding],
) -> None:
    for index, event in enumerate(events):
        needs_management = False
        reason = ""
        if event.event_type == "human_prompt":
            prompt_chars = int(
                event.payload.get("prompt_char_count")
                or len(str(event.payload.get("prompt") or ""))
            )
            if prompt_chars > CONTEXT_MANAGEMENT_PROMPT_CHARS:
                needs_management = True
                reason = f"prompt size {prompt_chars} chars"
        usage = event.payload.get("usage")
        if isinstance(usage, dict):
            turn_input = int(usage.get("input_tokens") or 0)
            if turn_input > CONTEXT_MANAGEMENT_TURN_INPUT_TOKENS:
                needs_management = True
                reason = f"turn input {turn_input} tokens"
        if not needs_management:
            continue
        next_prompt_index = _next_event_index(events, index, "human_prompt")
        if next_prompt_index is None:
            continue
        if any(
            item.event_type == "human_action" and item.payload.get("kind") == "context_management"
            for item in events[index + 1 : next_prompt_index]
        ):
            continue
        _add(
            findings,
            "error",
            "plain_realism.missing_context_management_touch",
            (
                "Plain track crossed the context-management threshold "
                f"({reason}) without recording a context-management touch before "
                "the next Codex checkpoint."
            ),
            track=track,
            ref=f"{track}/events.jsonl:{index + 1}",
        )


def _check_plain_session_model(
    events: list[SimulationEvent],
    track: str,
    findings: list[AuditFinding],
) -> None:
    checkpoint_commands = [
        (index, event)
        for index, event in enumerate(events)
        if event.event_type == "command"
        and event.source == "human"
        and (
            event.payload.get("codex_invocation_mode")
            or "codex exec" in str(event.payload.get("command") or "")
        )
    ]
    prompts = [event for event in events if event.event_type == "human_prompt"]
    if prompts and not checkpoint_commands:
        _add(
            findings,
            "error",
            "codex.session_model_violation",
            "Plain track has prompts but no recorded Codex checkpoint command metadata.",
            track=track,
            remediation="Use `simctl run-codex-checkpoint` for measured plain checkpoints.",
        )
        return
    if checkpoint_commands:
        prior_session = None
        for ordinal, (index, event) in enumerate(checkpoint_commands):
            mode = str(event.payload.get("codex_invocation_mode") or "unknown")
            session_id = event.payload.get("codex_session_id")
            if ordinal == 0 and mode != "start":
                _add(
                    findings,
                    "error",
                    "codex.session_model_violation",
                    "Plain run-scoped Codex measurement must begin with mode=start.",
                    track=track,
                    ref=f"{track}/events.jsonl:{index + 1}",
                )
            if (
                ordinal > 0
                and mode != "resume"
                and not _has_context_management_before(events, index)
            ):
                _add(
                    findings,
                    "error",
                    "codex.session_model_violation",
                    (
                        "Plain checkpoint did not resume the run-scoped Codex "
                        "session and did not record a context-management reset."
                    ),
                    track=track,
                    ref=f"{track}/events.jsonl:{index + 1}",
                )
            if (
                ordinal > 0
                and prior_session
                and session_id
                and session_id != prior_session
                and not _has_context_management_before(events, index)
            ):
                _add(
                    findings,
                    "error",
                    "codex.session_model_violation",
                    (
                        "Plain checkpoint changed Codex session id without a "
                        "context-management touch."
                    ),
                    track=track,
                    ref=f"{track}/events.jsonl:{index + 1}",
                )
            if session_id:
                prior_session = session_id
        return

    thread_ids = _codex_thread_ids(events)
    if len(thread_ids) > 1 and not any(
        event.event_type == "human_action" and event.payload.get("kind") == "context_management"
        for event in events
    ):
        _add(
            findings,
            "error",
            "codex.session_model_violation",
            (
                "Plain track started multiple Codex threads without recording "
                "run-scoped resume or context-management reset semantics."
            ),
            track=track,
        )


def _check_plain_cert_tax(
    events: list[SimulationEvent],
    track: str,
    findings: list[AuditFinding],
) -> None:
    has_cert_tax = any(
        event.event_type == "human_action" and event.payload.get("kind") == "cert_setup"
        for event in events
    )
    if not has_cert_tax or _has_local_https_validation(events):
        return
    _add(
        findings,
        "error",
        "plain_realism.cert_tax_without_https",
        (
            "Plain track records cert_setup time tax, but local validation/evidence "
            "does not show an HTTPS Padawan endpoint."
        ),
        track=track,
        remediation=(
            "Exercise the local HTTPS/self-signed certificate path, or remove the "
            "cert_setup touch from strict observed metrics."
        ),
    )


def _next_event_index(
    events: list[SimulationEvent],
    start_index: int,
    event_type: str,
) -> int | None:
    for index, event in enumerate(events[start_index + 1 :], start=start_index + 1):
        if event.event_type == event_type:
            return index
    return None


def _has_context_management_before(events: list[SimulationEvent], index: int) -> bool:
    previous_prompt = None
    for prior_index in range(index - 1, -1, -1):
        if events[prior_index].event_type == "human_prompt":
            previous_prompt = prior_index
            break
    window_start = previous_prompt if previous_prompt is not None else 0
    return any(
        event.event_type == "human_action" and event.payload.get("kind") == "context_management"
        for event in events[window_start:index]
    )


def _codex_thread_ids(events: list[SimulationEvent]) -> set[str]:
    thread_ids = set()
    for event in events:
        if event.event_type != "codex_event":
            continue
        thread_id = event.payload.get("thread_id")
        if thread_id:
            thread_ids.add(str(thread_id))
    return thread_ids


def _has_local_https_validation(events: list[SimulationEvent]) -> bool:
    for event in events:
        if event.event_type == "evidence" and event.payload.get("phase") == "local":
            return False
        if event.event_type not in {"command", "evidence"}:
            continue
        text = json.dumps(event.payload, sort_keys=True, default=str).lower()
        if "https://" in text:
            return True
    return False


def _prompt_forbids_tools(event: SimulationEvent) -> bool:
    text = (
        str(event.payload.get("prompt") or "")
        + "\n"
        + str(event.payload.get("prompt_file") or "")
        + "\n"
        + event.summary
    ).lower()
    if "do not" not in text:
        return False
    return any(
        phrase in text
        for phrase in (
            "do not run",
            "do not read",
            "do not inspect",
            "do not edit",
            "do not deploy",
            "do not use tools",
            "do not use mcp",
            "no shell",
            "no tool",
        )
    )


def _event_ref(track: str, events: list[SimulationEvent], event: SimulationEvent) -> str:
    try:
        return f"{track}/events.jsonl:{events.index(event) + 1}"
    except ValueError:
        return f"{track}/events.jsonl"


def _finding_summary(findings: list[AuditFinding]) -> dict[str, int]:
    summary = {"error": 0, "warning": 0, "info": 0}
    for finding in findings:
        summary[finding.severity] += 1
    return summary


def _severity_rank(severity: str) -> int:
    return {"error": 0, "warning": 1, "info": 2}.get(severity, 3)


def _format_metric_value(value: float | int, unit: str) -> str:
    if unit == "duration":
        return _format_duration(float(value))
    rounded = int(round(float(value)))
    if unit == "tokens":
        return f"{rounded:,} tokens"
    if unit == "bytes":
        return f"{rounded:,} bytes"
    return f"{rounded:,}"


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _add(
    findings: list[AuditFinding],
    severity: Severity,
    check_id: str,
    message: str,
    *,
    track: str | None = None,
    ref: str | None = None,
    remediation: str | None = None,
) -> None:
    findings.append(
        AuditFinding(
            severity=severity,
            check_id=check_id,
            track=track,
            message=message,
            evidence_ref=ref,
            remediation=remediation,
        )
    )
