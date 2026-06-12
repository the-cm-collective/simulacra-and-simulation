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
- `evidence`: screenshot, video, log, report, or graph artifact
- `checkpoint`: checkpoint state transition
- `protocol_violation`: track-policy violation

`turn.completed` usage from Codex JSONL is normalized into `codex_event` payload
fields named `input_tokens`, `cached_input_tokens`, `output_tokens`, and
`reasoning_output_tokens`.

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

Codex JSONL transcripts:

```bash
simctl ingest-codex --run-id <run> --track <track> --jsonl <codex.jsonl>
```

Report completeness is intentionally strict. A baseline report that shows zero
prompt, command/tool, evidence, or token metrics for either track is incomplete
and must not be used for comparison.
