# Baseline Retest Plan

This retest replaces the calibration outputs that showed zero prompt, command,
token, and context metrics. Those artifacts remain useful runtime smoke tests,
but they are not valid simulation measurements.

## Objectives

- Produce one paired baseline run under a single run ID: `baseline-001`.
- Keep `plain-codex` constrained to Podman Compose or `podman-compose`.
- Keep `workerbee-codex` constrained to WorkerBee's direct-containerd profile
  path through `scripts/dev/wb-containerd`.
- Record every human prompt, shell command, WorkerBee action, `ae` action,
  Codex JSONL transcript, and evidence artifact before rendering the report.
- Ensure Padawan WorkerBee staged manifests use the active project host instead
  of a stale hardcoded ingress/TURN host.

## Gate 0: Instrumentation Proof

Before running the baseline, create a disposable run and prove the report can
show nonzero metrics.

```bash
simctl init-run --run-id instrumentation-001
simctl record-prompt --run-id instrumentation-001 --track plain-codex \
  --prompt-file .local/instrumentation/plain-prompt-001.md
simctl record-command --run-id instrumentation-001 --track plain-codex \
  --event-type command --source human --summary "checked Podman version" \
  --command "podman version"
simctl ingest-codex --run-id instrumentation-001 --track plain-codex \
  --jsonl .local/instrumentation/plain-codex.jsonl
simctl record-command --run-id instrumentation-001 --track workerbee-codex \
  --event-type workerbee_tool --source workerbee \
  --summary "checked WorkerBee containerd capabilities" \
  --command "WORKERBEE_REFRESH_SUDO=0 scripts/dev/wb-containerd capabilities"
simctl render-report --run-id instrumentation-001
```

Acceptance:

- The report shows at least one prompt.
- The report shows at least one command or WorkerBee action.
- The report shows nonzero token usage after ingesting a Codex JSONL fixture or
  real `codex exec --json` output.
- Any missing metric is listed in `Measurement completeness`.

## Gate 1: Runtime Reset

Reset shared local ports before each track:

- `8787/tcp` for Padawan
- `3478/tcp` and `3478/udp` for coturn
- any WorkerBee profile controller/API ports reported by `wb-containerd`

The reset must be recorded as command events. If a port is held by the other
track, stop that track and record the cleanup action before continuing.

## Gate 2: Plain-Codex Baseline

Run ID: `baseline-001`

Track: `plain-codex`

Runtime requirement:

- Podman is required.
- `podman-compose` is acceptable when `podman compose` is unavailable.
- Docker is a protocol violation for measured local container work.
- WorkerBee MCP/tools are protocol violations in this track.

Measurement loop for each prompt checkpoint:

1. Write the human prompt to `.local/runs/baseline-001/plain-codex/prompts/`.
2. Record it with `simctl record-prompt`.
3. Run Codex with JSON output captured under the track `codex/` directory.
4. Ingest the JSONL with `simctl ingest-codex`.
5. Record every shell command the human runs outside Codex with
   `simctl record-command --event-type command --source human`.
6. Record every `ae` or dashboard-equivalent k1s action with
   `simctl record-command --event-type ae_command --source ae`.

Local validation:

- Start Padawan/coturn with the Podman Compose path.
- Probe `/healthz`, `/peer`, and `/peer/ice-config?profile=local-turn`.
- Run `npm run evidence:peer` against the local Padawan endpoint.
- Preserve screenshots, summary JSON, and optional video under the track
  evidence directory.

k1s dev HA validation:

- Build/tag/push by the plain track's allowed commands.
- Deploy with `ae` CLI or Hive dashboard only.
- Record deploy/status/log/probe actions.
- Run the same browser evidence flow against the deployed ingress URL.

## Gate 3: WorkerBee-Codex Baseline

Run ID: `baseline-001`

Track: `workerbee-codex`

Runtime requirement:

- Use WorkerBee's native containerd profile backend on this system.
- Use `scripts/dev/wb-containerd` until the configured MCP endpoint reports the
  same containerd backend.
- The Podman-backed WorkerBee project path is a protocol violation for measured
  local WorkerBee work.

Measurement loop for each prompt checkpoint:

1. Write the human prompt to
   `.local/runs/baseline-001/workerbee-codex/prompts/`.
2. Record it with `simctl record-prompt`.
3. Run Codex with JSON output captured under the track `codex/` directory.
4. Ingest the JSONL with `simctl ingest-codex`.
5. Record every WorkerBee action with
   `simctl record-command --event-type workerbee_tool --source workerbee`.
6. Record any shell command outside WorkerBee with
   `simctl record-command --event-type command --source human` or `codex`.

Direct-containerd local validation:

```bash
cd /home/m4xx3d0ut/git/k1s-wt/k1s-workerbee
WORKERBEE_REFRESH_SUDO=0 scripts/dev/wb-containerd --project baseline-001-wb \
  profile start --profile k1s-dev-min-sqlite --k1s-root ../k1s
WORKERBEE_REFRESH_SUDO=0 scripts/dev/wb-containerd --project baseline-001-wb \
  build-image --tag localhost/padawan:dev -f Containerfile ../padawan
WORKERBEE_REFRESH_SUDO=0 scripts/dev/wb-containerd --project baseline-001-wb \
  manifest prepare --name padawan-peer --source ../padawan/ops/workerbee
cd /home/m4xx3d0ut/git/k1s-wt/simulacra-and-simulation
simctl patch-workerbee-stage --project baseline-001-wb --stage-dir <stage_dir>
cd /home/m4xx3d0ut/git/k1s-wt/k1s-workerbee
WORKERBEE_REFRESH_SUDO=0 scripts/dev/wb-containerd --project baseline-001-wb \
  manifest validate --stage <stage_dir>
WORKERBEE_REFRESH_SUDO=0 scripts/dev/wb-containerd --project baseline-001-wb \
  manifest deploy-local --stage <stage_dir> --target profile \
  --profile k1s-dev-min-sqlite --k1s-root ../k1s --timeout 180
```

After deploy:

- Record profile status and logs as WorkerBee actions.
- Probe `/healthz`, `/peer`, and `/peer/ice-config?profile=local-turn`.
- Run `npm run evidence:peer` against the profile endpoint.
- Preserve screenshots, summary JSON, and optional video under the track
  evidence directory.

k1s dev HA validation:

- Build and deploy through the WorkerBee path when available for that target.
- Record WorkerBee deploy/status/log/probe actions.
- Run the same browser evidence flow against the deployed ingress URL.

## Gate 4: Report Acceptance

Render the paired report:

```bash
simctl render-report --run-id baseline-001
simctl export-html --run-id baseline-001
```

The report is accepted only when both tracks show:

- Nonzero human prompts.
- Nonzero command/tool actions.
- Nonzero Codex token usage.
- At least one local evidence artifact.
- At least one k1s dev HA evidence artifact when that phase is included.
- Zero unwaived protocol violations.
- Matching feature acceptance: AV, text chat, data channel, course transfer,
  progress sync, and local-only data persistence.

If any required metric is zero, fix instrumentation and rerun the affected
track. Do not patch the report by hand.

The HTML export is part of baseline acceptance. Review
`.local/runs/baseline-001/html/index.html` locally and verify that the summary,
timeline, and artifact pages include the same artifacts referenced by the raw
event stream.
