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

Run manifests include a `runtime_policy` object. It is part of the measurement
contract, not advisory metadata:

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
- `ae_command`: k1s `ae` CLI action and outcome
- `human_action`: manual non-command operator work such as log copy/paste,
  dashboard clicks, cert setup, waits, or troubleshooting
- `evidence`: screenshot, video, log, report, or graph artifact
- `checkpoint`: checkpoint state transition
- `protocol_violation`: track-policy violation

`turn.completed` usage from Codex JSONL is normalized into `codex_event` payload
fields named `input_tokens`, `cached_input_tokens`, `output_tokens`, and
`reasoning_output_tokens`. Each usage object is one usage snapshot for one
Codex turn.

Derived token metrics intentionally separate two meanings:

- cumulative billed token usage: sum of each recorded turn's token usage
- Codex turn input tokens: final or maximum per-turn `input_tokens` usage
  snapshot
- cached turn input tokens: final or maximum per-turn `cached_input_tokens`
  usage snapshot, when available
- usage snapshots: count of Codex turns with usage records
- missing usage: count of Codex turns that started but did not emit a completed
  usage record

The HTML chart package maps token data over time from those usage events:

- cumulative billed token usage by track and token class
- per-turn input usage using `input_tokens`
- cached input tokens per turn when available

The current Codex JSONL stream does not expose a separate model context-window
capacity field, so turn-input charts must not be labeled as literal context
window size. In controlled no-tool probes, per-turn input usage can act as a
context-pressure proxy. In full agent runs with tool calls, it is usage, not
context size. Do not compare cumulative billed token usage to per-turn input
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
  --command "<tool or wb-containerd command>"
simctl record-command --run-id <run> --track plain-codex \
  --event-type ae_command --source ae --summary "<summary>" --command "<ae command>"
```

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
