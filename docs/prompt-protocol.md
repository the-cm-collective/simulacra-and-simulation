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
6. Review k1s deployment documentation and prepare the final `k1s-dev-a` HA
   deploy path.
7. Build and deploy to the assigned k1s dev target.
8. Repair failures from observed logs/probes only.
9. Produce a concise implementation report with evidence links.

The plain `human + Codex + Podman` baseline includes one required extra local
validation checkpoint immediately after the first Podman evidence run: the
operator records a `copy_logs` human action, builds a prompt with
`simctl build-log-review-prompt`, and submits those uncurated copied logs to
Codex. This checkpoint models the common manual behavior where a developer
pastes too much terminal output into the assistant while troubleshooting. It
must be counted as a normal `human_prompt` and must be ingested from Codex JSONL
like every other checkpoint.

The `human + Codex + WorkerBee` baseline must not use an equivalent raw-log
paste unless the operator actually performs one during the measured run.
WorkerBee status/log inspection is recorded as `workerbee_tool` events so the
report distinguishes targeted runtime retrieval from manual copied context.

The plain `human + Codex + Podman` baseline includes one required extra k1s
documentation checkpoint immediately before the final remote deploy. The
operator gathers the relevant k1s docs, builds a prompt with
`simctl build-context-review-prompt`, and submits those copied excerpts to
Codex. This models the common cost of having to discover and translate
deployment docs into exact `ae` or Hive dashboard actions.

Both tracks must end with a Padawan/coturn deployment to the MicroK8s-hosted
`k1s-dev-a` HA stack. The plain track may use only `ae` CLI or Hive dashboard
for k1s actions. The WorkerBee track should use WorkerBee remote deploy/status,
log, and probe actions. Final browser evidence must set
`SIMULACRA_EVIDENCE_PHASE=k1s-dev-a` so the report can distinguish it from
local validation evidence.

The final HA phase is gated by `simctl check-k1s-dev-a-ingress`. Run it before
deploy work to catch broken translated-ingress topology, and run it again with
`--probe-url <deployed-peer-url> --probe-body-contains Padawan` before browser
evidence. A bare HTTP 200, including `/healthz`, is insufficient for final HA
evidence because it can pass without proving the Padawan UI route is served.
Direct node-host ports can be recorded as troubleshooting evidence, but they do
not satisfy the final HA ingress evidence requirement.

The baseline forbids subagents in both tracks. A command, prompt, or instruction
that attempts to spawn subagents is recorded as a protocol violation.

After every checkpoint prompt, the operator must ingest the corresponding
Codex JSONL transcript and record any manual console work before moving to the
next checkpoint. Use `record-command` for shell/AE work and `record-touch` for
manual non-command work such as log copy/paste, dashboard clicks, cert setup,
waits, and troubleshooting. A zero prompt count, zero command/tool/action count,
zero operator-touch count, or zero token usage in the rendered report
invalidates that track's measurement and requires a rerun from the last clean
checkpoint.
