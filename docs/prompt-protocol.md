# Prompt Protocol

Every measured run uses the same ordered prompt checkpoints. The human may add
clarifying context only in the `human_note` field recorded by the harness.

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
