# Metric Schema

The canonical stream is JSON Lines under:

```text
.local/runs/<run-id>/<track>/events.jsonl
```

Common event fields:

- `schema_version`: currently `simulacra.event.v1`
- `run_id`
- `track`: `plain-codex` or `workerbee-codex`
- `event_type`
- `timestamp`
- `source`
- `summary`
- `payload`

Run manifests include `active_tracks`, `ops_mode`, `tracks`, and
`runtime_policy`. `ops_mode` is `comparison` when both supported lanes are
active and `single-lane` when one lane is active. `runtime_policy` is part of
the measurement contract, not advisory metadata:

- `plain-codex` must use Podman for measured local container work.
- `workerbee-codex` must use WorkerBee's native containerd profile target for
  measured local WorkerBee work.
- `workerbee-codex` must record a capabilities check showing
  `runtime.selected == containerd` before local WorkerBee measurement starts.
- Any Docker use in the plain track or Podman-backed WorkerBee project use in
  the WorkerBee track is a `protocol_violation` unless explicitly marked as a
  non-baseline smoke test.

Important event types:

- `human_prompt`: prompt submitted by the human operator
- `codex_event`: raw or normalized item from `codex exec --json`
- `command`: command executed by Codex or by the human outside Codex
- `workerbee_tool`: WorkerBee MCP action and outcome
- `mcp_observation`: targeted WorkerBee-visible tool/artifact token estimate
- `billing_reconciliation`: redacted API-key auth preparation or provider-side
  usage/cost reconciliation metadata
- `ae_command`: k1s `ae` CLI action and outcome
- `human_action`: manual non-command operator work such as log copy/paste,
  dashboard clicks, cert setup, waits, context management, or troubleshooting
- `evidence`: screenshot, video, log, report, or graph artifact
- `checkpoint`: checkpoint state transition
- `protocol_violation`: track-policy violation

`turn.completed` usage from Codex JSONL is normalized into `codex_event` payload
fields named `input_tokens`, `cached_input_tokens`, `output_tokens`, and
`reasoning_output_tokens`. Each usage object is one usage snapshot for one
Codex turn.

Derived token metrics intentionally separate several meanings:

- captured Codex token usage: sum of each recorded turn's Codex JSONL usage
- MCP observation input tokens: estimated tokens from targeted WorkerBee
  tool-result artifacts that were visible to the WorkerBee lane but may not
  appear in Codex JSONL usage
- estimated all-in input tokens: captured Codex input tokens plus visible MCP
  observation tokens, minus observations explicitly marked as already included
  in Codex usage
- Codex turn input tokens: final or maximum per-turn `input_tokens` usage
  snapshot
- cached turn input tokens: final or maximum per-turn `cached_input_tokens`
  usage snapshot, when available
- usage snapshots: count of Codex turns with usage records
- missing usage: count of Codex turns that started but did not emit a completed
  usage record
- provider-reconciled input/cache/output/request/cost fields: values imported
  from OpenAI organization usage/cost records when `billing_reconciliation`
  events are present

These values are measurement-system token metrics, not an authoritative billing
ledger. They are suitable for comparing simulation lanes. They must not be
called actual billable token counts unless reconciled against provider-side
usage or cost records for the account or organization that ran the requests.
The Codex CLI can provide transcript and usage-snapshot evidence, but final
billable-token or cost reconciliation requires an external billing authority:
OpenAI Platform/admin usage and costs APIs for API-key usage, or the applicable
ChatGPT Enterprise usage-monitoring surface for enterprise ChatGPT-auth usage.

The HTML chart package maps token data over time from those usage events:

- captured Codex token usage by track and token class
- MCP observation token usage by track
- estimated all-in input tokens by track
- provider-reconciled input token totals when billing reconciliation exists
- per-turn input usage using `input_tokens`
- cached input tokens per turn when available

The current Codex JSONL stream does not expose a separate model context-window
capacity field, so turn-input charts must not be labeled as literal context
window size. In controlled no-tool probes, per-turn input usage can act as a
context-pressure proxy. In full agent runs with tool calls, it is usage, not
context size. Do not compare captured or estimated all-in token usage to per-turn input
tokens as if they were the same metric; resumed sessions and tool loops can
count prior context repeatedly.

## Required Recording Commands

Human prompts:

```bash
simctl record-prompt --run-id <run> --track <track> --prompt-file <prompt.md>
```

Shell, WorkerBee, and `ae` actions:

```bash
simctl record-command --run-id <run> --track <track> \
  --event-type command --source human --summary "<summary>" --command "<command>"
simctl record-command --run-id <run> --track workerbee-codex \
  --event-type workerbee_tool --source workerbee --summary "<summary>" \
  --command "<tool or wb-containerd command>" \
  --artifact-file .local/runs/<run>/workerbee-codex/commands/<artifact>.json \
  --artifact-class targeted_status
simctl record-command --run-id <run> --track plain-codex \
  --event-type ae_command --source ae --summary "<summary>" --command "<ae command>"
```

WorkerBee targeted status/log/build/probe artifacts must be measured as MCP
observations before a public report is accepted:

```bash
simctl measure-mcp-artifacts --run-id <run> --track workerbee-codex \
  --commands-dir .local/runs/<run>/workerbee-codex/commands
```

By default, generated `mcp_observation` events are marked
`mcp_visible=true` and `included_in_codex_usage=false`. Use
`--included-in-codex-usage` only when the same tool output is known to be
present in the Codex JSONL usage stream and should not be added again.
The measurement uses the `cl100k_base` tokenizer through `tiktoken` when
available. If the tokenizer dependency is not installed, the event is still
recorded with a conservative bytes/4 estimate and `estimation_method` marks
the fallback explicitly.

OpenAI API-key billing reconciliation:

```bash
simctl prepare-openai-api-auth --run-id <run> --track plain-codex \
  --api-key-env SIM_OPENAI_KEY_PLAIN
simctl prepare-openai-api-auth --run-id <run> --track workerbee-codex \
  --api-key-env SIM_OPENAI_KEY_WORKERBEE
simctl reconcile-openai-usage --run-id <run> \
  --plain-project-id <proj_plain> \
  --workerbee-project-id <proj_workerbee>
```

`prepare-openai-api-auth` runs `codex login --with-api-key` with the key read
from stdin. It records only redacted metadata and defaults the auth cache to
`.local/auth/codex-api/<run>/<track>/`, outside the report package.
`reconcile-openai-usage` writes raw provider JSON under
`.local/runs/<run>/billing/openai/`, normalized results under
`.local/runs/<run>/billing/reconciliation.json`, and one
`billing_reconciliation` event per track. Use `--usage-json` and `--costs-json`
for offline fixtures; otherwise the command reads `OPENAI_ADMIN_KEY` and calls
OpenAI organization usage/cost APIs.

Manual non-command operator touches:

```bash
simctl record-touch --run-id <run> --track <track> \
  --kind copy_logs --summary "copied console logs into Codex"
```

Operator touches are a derived metric, not literal keystrokes. The count is:

```text
human_prompt + command/source=human + ae_command + human_action
```

WorkerBee tool calls are delegated automation and do not increase operator
touches.

Runtime is reported with four distinct views:

- Realistic runtime: pre-tax measured span plus explicit manual time-tax
  seconds from `human_action.duration_seconds`. This is the comparable runtime
  used for percentage deltas and report charts.
- Pre-tax measured span: first to last non-`checkpoint`/preflight event in the
  track. This is diagnostic only and should not be presented as a comparable
  human-performance runtime.
- Raw event span: first to last event including harness checkpoint setup.
- Checkpoint idle excluded: idle gap from run initialization to the first
  non-`checkpoint`/preflight measured work event.

Use `record-touch --duration-seconds` for manual non-command work such as
self-signed certificate setup, copied-log handling, dashboard work, or k1s docs
lookup time that should be included in realistic runtime.

Copied-context prompt builders write a sidecar file beside the prompt:

```text
<prompt-name>.prompt-meta.json
```

`record-prompt` imports that metadata into the `human_prompt` event payload.
Reports derive these metrics from the imported metadata:

- cumulative prompt bytes and maximum prompt bytes
- prompt metadata coverage (`prompt_metadata_count / human_prompt` count)
- copied context bytes and available copied context bytes
- copied context source count and truncated source count
- copied context bytes by class: `local_logs`, `k1s_docs`,
  `remote_failure_logs`, `operator_summary`, or `other`
- `context_management` human-action count

If a prompt is missing `prompt_metadata`, copied-context bytes for that prompt
are unknown, not confirmed zero. Public reports surface missing metadata
separately so old runs cannot understate copied-log or copied-doc context.

Plain-Codex context growth is measured with `simctl run-codex-checkpoint`.
Strict plain runs start checkpoint 1 with `--mode start` and use `--mode
resume --session-id <id>` for later checkpoints. A fresh session is allowed only
after a recorded `context_management` action.

Evidence events may include `payload.phase`. Use `local` for local Podman or
WorkerBee profile validation and `k1s-dev-a` for the final MicroK8s-hosted HA
deployment evidence. Phase labels are reported so local screenshots do not get
mistaken for final deployment evidence.

Codex JSONL transcripts:

```bash
simctl ingest-codex --run-id <run> --track <track> --jsonl <codex.jsonl>
```

Report completeness is intentionally strict. A baseline report that shows zero
prompt, command/tool, evidence, or token metrics for either track is incomplete
and must not be used for comparison.

## Public Report Audit Gate

Run the audit gate before accepting or publishing a baseline:

```bash
simctl audit-run --run-id <run> --profile public-tech-report
```

The gate writes `.local/runs/<run>/audit.json` and `audit.md`. A public
baseline is accepted only when `audit.json` has `accepted=true` and zero
`error` findings. Warnings remain visible in the report package.

Audit checks cover:

- manifest/scenario completeness and legacy manifest fallbacks
- event stream parseability, schema version, timestamps, and event/source
  classification
- prompt-to-Codex transcript coverage and duplicate Codex JSONL ingestion
  through source transcript fingerprints
- Codex checkpoint isolation flags (`--ephemeral --ignore-rules`) and no-tool
  checkpoint transcripts that emit shell-command or MCP tool items
- plain-lane run-scoped Codex session continuity, copied-context thresholds,
  failed-command repair prompts, context-management touches, and cert setup
  evidence
- WorkerBee one-prompt token sanity: max turn input above 20,000 tokens blocks
  the baseline unless an explicit audit waiver is recorded
- optional provider reconciliation gate: when
  `manifest.billing_reconciliation.required=true`, each active track must have a
  provider reconciliation event, distinct OpenAI project IDs, nonzero provider
  input tokens, a non-mismatched match basis, existing raw artifacts, and no
  secret-looking values in billing payloads
- WorkerBee MCP observation accounting: WorkerBee runs with tool actions must
  include targeted tool-result observation token estimates unless the tool
  results are captured directly in Codex usage
- billing reconciliation boundary: captured Codex usage plus MCP observation
  estimates may be reported as estimated all-in input tokens, but actual
  billable usage requires provider-side usage/cost reconciliation
- environment repair noise such as stale Caddy state, empty-body ingress repair,
  service-port patching, edge route sync repair, or controller routing drift
- strict core metric expectations: if all other gates are clean, a plain-Codex
  win on runtime, operator touches, human commands, tokens, or prompt/context
  bytes blocks as `comparison.plain_core_metric_win` unless explicitly waived
- checkpoint requirements, including the plain copied-log and k1s-doc prompts
  and WorkerBee targeted status/log/tool validation
- track runtime policy violations such as plain-track WorkerBee/Docker use or
  WorkerBee-track host Podman fallback commands
- local and final `k1s-dev-a` evidence artifacts, feature summary JSON, and the
  final `/peer` body gate
- likely secret material in prompts, command logs, event streams, and report
  inputs

`render-report` and `export-html` include the latest audit result when present.
If no audit has been run, reports explicitly show `Audit not run`.
