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
