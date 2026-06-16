# Baseline Retest Plan

This retest replaces the calibration outputs that showed zero prompt, command,
token, and turn-input metrics. Those artifacts remain useful runtime smoke
tests, but they are not valid simulation measurements.

## Objectives

- Produce one paired baseline run under a single run ID: `baseline-001`.
- Keep `plain-codex` constrained to Podman Compose or `podman-compose`.
- Keep `workerbee-codex` constrained to WorkerBee's direct-containerd profile
  path through `scripts/dev/wb-containerd`.
- Record every human prompt, shell command, WorkerBee action, `ae` action,
  manual non-command operator touch, Codex JSONL transcript, and evidence
  artifact before rendering the report.
- Measure targeted WorkerBee MCP/tool observation artifacts so the WorkerBee
  lane reports captured Codex tokens, MCP observation tokens, and estimated
  all-in input tokens.
- Treat those token fields as comparative measurement data, not actual billable
  usage. A final billable-token or cost layer must reconcile the run against
  provider-side usage/cost records for the account or organization that ran the
  Codex requests.
- Explicitly model the plain-track raw-log copy/paste tax by running a second
  measured Codex prompt that includes manually copied Podman validation logs.
  WorkerBee remains measured through targeted tool/log actions instead of raw
  console dumps.
- Explicitly model the plain-track k1s documentation/deploy tax before the
  final HA deployment. The operator must gather the relevant k1s docs, submit a
  measured Codex checkpoint with those excerpts, and then perform the deploy
  with `ae` CLI or Hive dashboard actions only.
- End both tracks with a Padawan/coturn app deployment to the MicroK8s-hosted
  `k1s-dev-a` HA stack, followed by deploy status, logs/probes, and browser
  evidence against that deployed ingress URL.
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
  --command "WORKERBEE_REFRESH_SUDO=0 scripts/dev/wb-containerd capabilities" \
  --artifact-file .local/instrumentation/wb-capabilities.json \
  --artifact-class targeted_status
simctl measure-mcp-artifacts --run-id instrumentation-001 --track workerbee-codex \
  --artifact-file .local/instrumentation/wb-capabilities.json \
  --artifact-class targeted_status
simctl render-report --run-id instrumentation-001
```

Acceptance:

- The report shows at least one prompt.
- The report shows at least one command or WorkerBee action.
- The report shows nonzero token usage after ingesting a Codex JSONL fixture or
  real `codex exec --json` output.
- The WorkerBee track shows nonzero MCP observation accounting when WorkerBee
  tool artifacts are recorded.
- Any missing metric is listed in `Measurement completeness`.

Optional API-key billing instrumentation proof:

```bash
simctl prepare-openai-api-auth --run-id instrumentation-001 --track plain-codex \
  --api-key-env SIM_OPENAI_KEY_PLAIN
simctl prepare-openai-api-auth --run-id instrumentation-001 --track workerbee-codex \
  --api-key-env SIM_OPENAI_KEY_WORKERBEE
simctl reconcile-openai-usage --run-id instrumentation-001 \
  --plain-project-id <plain-project-id> \
  --workerbee-project-id <workerbee-project-id> \
  --usage-json <usage-fixture.json> --costs-json <costs-fixture.json>
```

Acceptance:

- Auth preparation records env var names and `codex_home` paths only, not key
  values.
- Reconciliation writes raw provider fixtures under
  `.local/runs/<run>/billing/openai/` and appends provider reconciliation
  events for both tracks.
- The two tracks use distinct OpenAI project IDs.

## Gate 1: Runtime Reset

Reset shared local ports before each track:

- `8787/tcp` for Padawan
- `3478/tcp` and `3478/udp` for coturn
- any WorkerBee profile controller/API ports reported by `wb-containerd`

The reset must be recorded as command events. If a port is held by the other
track, stop that track and record the cleanup action before continuing.

Before `workerbee-codex` measurement starts, run the hard WorkerBee Caddy
preflight and fail the run if it reports any finding:

```bash
simctl check-workerbee-caddy \
  --state-root /tmp/workerbee-containerd-verify \
  --project baseline-001-wb
```

Acceptance:

- No duplicate Caddy site definitions exist under
  `/tmp/workerbee-containerd-verify/projects/*/caddy/*.caddy`.
- The measured WorkerBee project has no pre-existing Caddy route files before
  profile start or manifest deploy.
- Any cleanup needed to satisfy this gate is recorded before the measured
  WorkerBee prompt/runtime sequence begins.

Before either track starts the final `k1s-dev-a` deployment phase, run the hard
k1s HA app-ingress preflight and fail the run if it reports an error:

```bash
simctl check-k1s-dev-a-ingress
```

Acceptance:

- `AE_EDGE_INGRESS_TRANSLATE_APP_INGRESS=1` is present on the HA controller.
- If translated app ingress resolves to `core-proxy`, at least one controller
  core-proxy site port in `18080..18089` is reachable from a controller pod.
- If translated app ingress resolves to `core-local` on the HA/remote transport,
  the warning is accepted only when a post-deploy app-host probe is also run
  and passes for the deployed Padawan host.
- Any failure means the baseline is blocked before spending measured prompt
  tokens on final deployment evidence.

After each track captures final `k1s-dev-a` evidence, run the cleanup gate
outside measured runtime and preserve its JSON output under that track's
`commands/` directory:

```bash
simctl cleanup-k1s-dev-a --run-id baseline-001 --include-workerbee-profiles --execute
simctl check-k1s-runtime-clean
```

The cleanup artifact must show `ok=true` and `execute=true`. A later
`check-k1s-runtime-clean` must show no stale simulation runtime containers and
no reserved simulation ports bound. This hygiene step is not counted as lane
runtime; it prevents finished evidence runs from leaving dashboard records,
MicroK8s `ae` containers, or direct-containerd WorkerBee profile listeners
behind.

Reserve lane-scoped remote k1s service ports before measured deploy. The
host-b node agent treats `spec.service.port` as a node-local allocation. Clean
baselines must not assume that the app's default local ports are free on the
shared remote node, and two simultaneous final Padawan/coturn deployments cannot
both use the same node-local ports. Patch remote manifests before apply rather
than repairing this inside a measured lane. Keep `targetPort` at the container
port and vary only `service.port`, for example:

- `plain-codex`: Padawan `18787`, coturn `13478`
- `workerbee-codex`: Padawan `28787`, coturn `23478`

Also reserve WorkerBee local profile service ports before measured local
WorkerBee deploy. The profile's node-agent also uses `spec.service.port` as a
host-local allocation, so patch the local WorkerBee stage before deploy:

- `workerbee-codex` local profile: Padawan `18878`, coturn `13479`

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
2. Run it with `simctl run-codex-checkpoint`.
3. Use `--mode start` for checkpoint 1 and `--mode resume --session-id <id>`
   for later checkpoints.
4. Let the wrapper record the prompt, write/ingest Codex JSONL, and record the
   Codex submission command.
5. Record every shell command the human runs outside Codex with
   `simctl record-command --event-type command --source human`.
6. Record every `ae` or dashboard-equivalent k1s action with
   `simctl record-command --event-type ae_command --source ae`.
7. Record manual non-command work with `simctl record-touch`, including log
   copy/paste, cert setup, dashboard clicks, waits, and troubleshooting.

Local validation:

- Start Padawan/coturn with the Podman Compose path.
- Probe `/healthz`, `/peer`, and `/peer/ice-config?profile=local-turn`.
- Run `npm run evidence:peer` against the local Padawan endpoint.
- Preserve screenshots, summary JSON, and optional video under the track
  evidence directory.
- Before moving to deploy validation, record a `copy_logs` human action and
  run a second measured Codex checkpoint containing copied raw Podman/evidence
  logs:

```bash
simctl record-touch --run-id baseline-001 --track plain-codex \
  --kind copy_logs \
  --summary "copied raw Podman validation logs into Codex"
simctl build-log-review-prompt \
  --output .local/runs/baseline-001/plain-codex/prompts/002-log-review.md \
  --title "Plain Codex checkpoint 2: copied local logs" \
  --instruction "Review the copied Podman/evidence logs and recommend the next action. Do not edit files. Do not run commands. Do not use WorkerBee." \
  --log-file .local/runs/baseline-001/plain-codex/commands/compose-up.log \
  --log-file .local/runs/baseline-001/plain-codex/commands/probes.log \
  --log-file .local/runs/baseline-001/plain-codex/commands/evidence-peer.log
simctl run-codex-checkpoint --run-id baseline-001 --track plain-codex \
  --checkpoint-id 002-log-review \
  --prompt-file .local/runs/baseline-001/plain-codex/prompts/002-log-review.md \
  --cwd ../padawan --mode resume --session-id <checkpoint-1-session-id>
```

Acceptance:

- The prompt file contains copied log text from the local Podman run.
- The prompt metadata shows at least 25,000 embedded local copied-log bytes
  from at least 4 local artifacts when that much captured context is available.
- The track records at least one `human_action` with `kind=copy_logs`.
- The plain track has at least two measured prompts and at least two Codex
  usage snapshots after JSONL ingestion.

k1s dev HA validation:

This phase is required and must be the final operational step for the track.
The plain track must read and reference the k1s repo docs before deploying:

- `../k1s/docs/ops/microk8s-dev-stack.md`
- `../k1s/README.md`, especially "Remote CLI (over LAN)"
- `../k1s/docs/ops/runbook.md`, especially API tokens and API shim guidance
- `../k1s/docs/reference/apishim-compatibility-matrix.md`

Before running `ae`, record the documentation lookup and build a measured docs
checkpoint:

```bash
simctl record-touch --run-id baseline-001 --track plain-codex \
  --kind troubleshoot \
  --summary "gathered k1s remote deploy docs for k1s-dev-a"
simctl build-context-review-prompt \
  --output .local/runs/baseline-001/plain-codex/prompts/003-k1s-docs-deploy.md \
  --title "Plain Codex checkpoint 3: k1s-dev-a docs deploy path" \
  --instruction "Review the copied k1s docs and recommend the exact final deploy/status/log/probe path for Padawan on k1s-dev-a. Do not edit files. Do not run commands. Do not use WorkerBee." \
  --context-label "k1s doc excerpt" \
  --context-file .local/runs/baseline-001/plain-codex/commands/k1s-doc-excerpts.txt
simctl run-codex-checkpoint --run-id baseline-001 --track plain-codex \
  --checkpoint-id 003-k1s-docs-deploy \
  --prompt-file .local/runs/baseline-001/plain-codex/prompts/003-k1s-docs-deploy.md \
  --cwd ../k1s --mode resume --session-id <checkpoint-1-session-id>
```

The k1s docs checkpoint metadata must show at least 30,000 embedded copied
context bytes from at least 3 k1s docs/artifacts when available.

Then:

- Build/tag/push Padawan and coturn images with the plain track's allowed
  commands.
- Deploy to the existing `k1s-dev-a` HA controller with `ae` CLI or Hive
  dashboard only. Record every apply/status/events/log/probe action as
  `ae_command` or dashboard `human_action`.
- Use the controller API server and token discovered from the MicroK8s
  deployment without pasting secret values into event payloads.
- Run
  `simctl check-k1s-dev-a-ingress --probe-url <deployed-peer-url> --probe-body-contains Padawan`
  and fail the track if the deployed app host does not return a 2xx/3xx
  response containing the expected Padawan UI marker. A bare HTTP 200 from
  `/healthz` is not sufficient for final HA evidence.
- Run `SIMULACRA_EVIDENCE_PHASE=k1s-dev-a npm run evidence:peer` against the
  deployed ingress URL.
- Preserve deployed screenshots, summary JSON, and optional video under the
  track evidence directory.
- Run `simctl cleanup-k1s-dev-a --run-id baseline-001 --execute`, save the JSON
  artifact, and rerun `simctl check-k1s-runtime-clean`.
- If any Podman, evidence, `ae`, or final k1s gate command fails, record a
  `copy_logs` or `troubleshoot` touch and submit a later measured repair
  checkpoint with the relevant copied failure logs before continuing.
- If a prompt exceeds 30,000 characters or a Codex turn exceeds 40,000 input
  tokens, record a `context_management` touch before the next checkpoint.

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
   Attach targeted status/log/probe/build output with `--artifact-file` and an
   `--artifact-class` such as `targeted_status`, `targeted_logs`,
   `deploy_result`, `probe_result`, or `build_output`.
6. Record any shell command outside WorkerBee with
   `simctl record-command --event-type command --source human` or `codex`.
7. Record manual non-command work with `simctl record-touch`, including log
   copy/paste, dashboard clicks, waits, and troubleshooting.
8. Before rendering, run `simctl measure-mcp-artifacts` for the WorkerBee
   command artifact directory. This appends idempotent `mcp_observation` events
   and lets the report show estimated all-in input tokens.

Direct-containerd local validation:

```bash
cd ../k1s-workerbee
WORKERBEE_REFRESH_SUDO=0 scripts/dev/wb-containerd --project baseline-001-wb \
  profile start --profile k1s-dev-min-sqlite --k1s-root ../k1s
WORKERBEE_REFRESH_SUDO=0 scripts/dev/wb-containerd --project baseline-001-wb \
  build-image --tag localhost/padawan:dev -f Containerfile ../padawan
WORKERBEE_REFRESH_SUDO=0 scripts/dev/wb-containerd --project baseline-001-wb \
  manifest prepare --name padawan-peer --source ../padawan/ops/workerbee
cd ../simulacra-and-simulation
simctl patch-workerbee-stage --project baseline-001-wb --stage-dir <stage_dir>
cd ../k1s-workerbee
WORKERBEE_REFRESH_SUDO=0 scripts/dev/wb-containerd --project baseline-001-wb \
  manifest validate --stage <stage_dir>
WORKERBEE_REFRESH_SUDO=0 scripts/dev/wb-containerd --project baseline-001-wb \
  manifest deploy-local --stage <stage_dir> --target profile \
  --profile k1s-dev-min-sqlite --k1s-root ../k1s --timeout 180
```

After deploy:

- Record profile status and logs as WorkerBee actions.
- Use WorkerBee's targeted log/status retrieval as the measured advantage. Do
  not paste full WorkerBee logs into a follow-up Codex prompt unless the
  operator actually does so; if that happens, record it as `copy_logs`.
- Run a post-deploy duplicate-route check:

```bash
simctl check-workerbee-caddy --state-root /tmp/workerbee-containerd-verify
```

  This catches current-project route generation collisions that the preflight
  gate cannot see before deploy. The accepted path requires WorkerBee profile
  deploy to skip `profile-workload.caddy` routes when another project Caddy
  file already owns the same host.
- Probe `/healthz`, `/peer`, and `/peer/ice-config?profile=local-turn`.
- Run `npm run evidence:peer` against the profile endpoint.
- Preserve screenshots, summary JSON, and optional video under the track
  evidence directory.

k1s dev HA validation:

This phase is required and must be the final operational step for the track.
The WorkerBee track should use WorkerBee for the k1s remote path:

- Build/tag/push the same Padawan and coturn images through WorkerBee or the
  approved WorkerBee wrapper for the target registry.
- Deploy the staged app to the existing `k1s-dev-a` HA controller with
  `workerbee_v1_manifest_deploy_remote_k1s` or the equivalent WorkerBee CLI
  path. Do not use Podman project runtime for this measured path.
- Record WorkerBee deploy/status/log/probe actions as `workerbee_tool`.
- Use targeted WorkerBee status/log retrieval. Do not paste full remote logs
  into Codex unless the operator actually does so; if it happens, record
  `copy_logs`.
- Measure the targeted WorkerBee command artifacts with
  `simctl measure-mcp-artifacts --run-id baseline-001 --track workerbee-codex`
  before `render-report`.
- Run `SIMULACRA_EVIDENCE_PHASE=k1s-dev-a npm run evidence:peer` against the
  deployed ingress URL.
- Run
  `simctl check-k1s-dev-a-ingress --probe-url <deployed-peer-url> --probe-body-contains Padawan`
  before final browser evidence and fail the track if the deployed app host does
  not return a 2xx/3xx response containing the expected Padawan UI marker. A
  bare HTTP 200 from `/healthz` is not sufficient for final HA evidence.
- Preserve deployed screenshots, summary JSON, and optional video under the
  track evidence directory.
- Run `simctl cleanup-k1s-dev-a --run-id baseline-001 --include-workerbee-profiles --execute`,
  save the JSON artifact, and rerun `simctl check-k1s-runtime-clean`.

## Gate 4: Provider Billing Reconciliation

For the clean API-key baseline, use one OpenAI project or project-scoped API key
per lane. Prepare auth before measured Codex checkpoints:

```bash
simctl prepare-openai-api-auth --run-id baseline-001 --track plain-codex \
  --api-key-env SIM_OPENAI_KEY_PLAIN
simctl prepare-openai-api-auth --run-id baseline-001 --track workerbee-codex \
  --api-key-env SIM_OPENAI_KEY_WORKERBEE
```

Pass the printed `codex_home` path to each `simctl run-codex-checkpoint
--codex-home` invocation for that track.

After both lanes complete, reconcile provider usage:

```bash
export OPENAI_ADMIN_KEY=...
simctl reconcile-openai-usage --run-id baseline-001 \
  --plain-project-id <plain-project-id> \
  --workerbee-project-id <workerbee-project-id>
```

Acceptance:

- Provider input tokens are nonzero for both tracks.
- `match_basis` is `captured_codex` or `estimated_all_in`, not `mismatch`.
- Provider project IDs are distinct.
- No API key values appear in events, reports, or HTML output.
- Cost values are present or an explicit note explains provider cost lag.

## Gate 5: Report Acceptance

Render the paired report:

```bash
simctl render-report --run-id baseline-001
simctl export-html --run-id baseline-001
```

The report is accepted only when both tracks show:

- Nonzero human prompts.
- Nonzero command/tool actions.
- Nonzero operator-touch metrics, where touches are human prompts, human shell
  commands, `ae`/dashboard actions, and explicit `human_action` events.
- Nonzero Codex token usage.
- WorkerBee runs with WorkerBee actions include nonzero MCP observation event
  accounting unless all tool-result tokens are captured directly in Codex JSONL
  and marked `included_in_codex_usage`.
- Token reports use `estimated all-in input tokens` for comparison. Do not label
  them actual billable usage unless the run has been reconciled with OpenAI
  Platform/admin usage and costs APIs for API-key runs, or the applicable
  ChatGPT Enterprise usage-monitoring surface for ChatGPT-auth enterprise runs.
- Plain track includes the copied-log checkpoint and shows the resulting second
  token snapshot; WorkerBee track shows targeted WorkerBee action events instead
  of a raw-log prompt for the same local validation phase.
- At least one local evidence artifact with `payload.phase=local`.
- At least one k1s dev HA evidence artifact with `payload.phase=k1s-dev-a`.
- Zero unwaived protocol violations.
- Matching feature acceptance: AV, text chat, data channel, course transfer,
  progress sync, and local-only data persistence.

If any required metric is zero, fix instrumentation and rerun the affected
track. Do not patch the report by hand.

The HTML export is part of baseline acceptance. Review
`.local/runs/baseline-001/html/index.html` locally and verify that the summary,
executive, technical, charts, timeline, and artifact pages include the same
artifacts referenced by the raw event stream. The charts page must show
cumulative operator touches, command/tool actions, captured Codex tokens, MCP
observation tokens, estimated all-in input tokens, and per-turn Codex
input-token usage over the run timeline. Treat context growth as a separate
controlled no-tool probe, not as a direct runtime baseline metric.
