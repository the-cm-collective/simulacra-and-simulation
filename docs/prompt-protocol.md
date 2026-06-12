# Prompt Protocol

Every measured run uses the same ordered prompt checkpoints. The human may add
clarifying context only in the `human_note` field recorded by the harness.

Before checkpoint 1, the run operator records the runtime policy from the run
manifest. The `plain-codex` track uses Podman for measured local container work.
The `workerbee-codex` track uses WorkerBee's native containerd profile path for
measured local WorkerBee work, and must include a capabilities check showing
`runtime.selected == containerd`. Runtime mismatches are protocol violations and
require a rerun for comparable data.

1. Inspect the Padawan repo and propose the implementation path.
2. Implement peer mode identity and signaling.
3. Implement WebRTC AV, text chat, and data-channel behavior.
4. Implement course transfer and progress sync.
5. Add local validation assets and run tests.
6. Build and deploy to the assigned k1s dev target.
7. Repair failures from observed logs/probes only.
8. Produce a concise implementation report with evidence links.

The baseline forbids subagents in both tracks. A command, prompt, or instruction
that attempts to spawn subagents is recorded as a protocol violation.

After every checkpoint prompt, the operator must ingest the corresponding
Codex JSONL transcript and record any manual console work before moving to the
next checkpoint. A zero prompt count, zero command/tool count, or zero token
usage in the rendered report invalidates that track's measurement and requires
a rerun from the last clean checkpoint.
