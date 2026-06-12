# Implementation Plan

This plan converts the Joplin project note into a reproducible dual-track
simulation. It intentionally uses more checkpoints than a normal feature plan
because the experiment needs clean restart points, comparable evidence, and
consistent measurement across repeated runs.

## Scope

Compare two development tracks while both implement the same Padawan feature:

- `plain-codex`: human plus Codex CLI, local Podman Compose, and `ae`/k1s CLI
  or dashboard for k1s actions.
- `workerbee-codex`: human plus Codex CLI and WorkerBee MCP for build, deploy,
  logs, probes, and runtime repair through the native containerd profile path.

The target feature is Padawan/Jedi peer collaboration with WebRTC audio/video,
text chat, data-channel course transfer, local progress sync, local-only user
state, and a session token that either side can generate.

## Design Decisions

- The simulation harness is a new sibling repository so the experiment can be
  cloned and repeated without vendoring Padawan, k1s, or WorkerBee.
- The harness records canonical JSONL event streams under `.local/runs/`.
- The baseline uses one Codex agent per track. Subagents are reserved for a
  later variant because they would change the comparison.
- `codex exec --json` is the primary structured source for Codex actions and
  token usage. TUI/manual actions are represented as explicit harness events.
- Google is treated as public STUN only. The controlled test TURN path uses the
  local coturn service deployed with Padawan.
- Evidence capture must be runnable against any Padawan base URL, including
  local source, Compose, WorkerBee, and the k1s dev HA target.
- Measured `plain-codex` local container work must use Podman. Docker is not an
  allowed measured runtime for that track.
- Measured `workerbee-codex` local WorkerBee work must use the profile/native
  containerd target. A Podman-backed WorkerBee project is a smoke-test-only path
  and cannot be used for baseline measurements.
- Before WorkerBee-track measurement starts, `workerbee_v1_capabilities` must
  report `runtime.selected == containerd`.

## Phase 0: Repository And Baseline Lock

Goal: create reproducible starting state and record the invariants.

Checkpoint commit: `chore: scaffold simulation harness`

Required work:

- Create `simulacra-and-simulation` as a sibling of `padawan`, `k1s`, and
  `k1s-workerbee`.
- Add a Python package and `simctl` CLI for preflight, run initialization,
  prompt recording, Codex JSONL ingest, and report rendering.
- Add docs for prompt protocol and metric schema.
- Add `.local/` as the only mutable run-data root.
- Record target repo paths, active Padawan branch, active model/config, and the
  runtime policy in each run manifest.

Validation gate:

- `simctl preflight` passes.
- `ruff format --check`, `ruff check`, and `pytest` pass.
- A run can be initialized with both track directories and seed checkpoint
  events.

## Phase 1: Measurement Contract

Goal: make the measurement stream rich enough before any baseline run.

Checkpoint commit: `feat: record simulation measurements`

Required event classes:

- `human_prompt`: every prompt submitted by the human operator.
- `codex_event`: normalized events from `codex exec --json`.
- `command`: shell commands run by Codex or by the human outside Codex.
- `workerbee_tool`: WorkerBee MCP action, status, and artifact paths.
- `ae_command`: k1s `ae` CLI or dashboard-equivalent action.
- `evidence`: screenshots, videos, logs, reports, and graph artifacts.
- `checkpoint`: phase start/end and validation gates.
- `protocol_violation`: any track-policy violation.

Required metrics:

- Prompt count and prompt timestamps.
- Codex action timeline.
- Human manual command timeline.
- Tool and shell command durations.
- Input, cached input, output, and reasoning token totals.
- Context-growth samples when available from Codex event metadata.
- Evidence artifact inventory and validation status.
- Track-policy violations and repair loops.

Validation gate:

- Unit tests cover schema round-trip, Codex JSONL normalization, and report
  aggregation.
- A synthetic run renders a report with nonzero prompt, command, token, and
  evidence counts.

## Phase 2: Padawan Feature Implementation

Goal: implement the shared feature once as the target branch payload.

Checkpoint commits:

- `feat: add peer signaling backend`
- `feat: add peer collaboration UI`
- `fix: resend peer offer after join`

Backend requirements:

- Stable local peer identity using username, role, and a local seed.
- Suffix/hash appended to identities to reduce local username collisions.
- Ephemeral in-app session hub and `padsim1` invite token format.
- ICE profile endpoint for `local-turn`, `google-stun`, and `none`.
- WebSocket signaling for offer, answer, ICE candidate, and roster messages.
- Local course inbox and peer progress snapshot persistence.

Frontend requirements:

- Main-screen mode selection for Padawan and Jedi.
- Peer workspace with username, role, ICE profile, token create/join, local and
  remote video panes, chat, course transfer, progress sync, roster, and data
  channel status.
- WebRTC AV, text chat, data channel course payload transfer, and progress
  payload transfer.
- Initiator re-sends an existing local offer when the joining peer connects, so
  the normal create-token-then-join flow opens the data channel reliably.

Validation gate:

- Padawan Python tests pass.
- Padawan static JavaScript parses with `node --check`.
- The browser evidence runner passes against a source-served Padawan instance.

## Phase 3: Runtime Packaging

Goal: provide both track-compatible local runtimes.

Checkpoint commits:

- `ops: add peer runtime assets`
- `ops: repair workerbee peer runtime`

Plain track requirements:

- Compose stack with Padawan and coturn.
- Compose runner uses Podman Compose or podman-compose for measured runs.
- Docker Compose compatibility may exist for developer convenience, but Docker
  use is a protocol violation in measured `plain-codex` runs.
- Self-signed local certificate setup remains part of the measured human time
  tax when HTTPS is needed.

WorkerBee track requirements:

- Native k1s manifests for Padawan and coturn.
- Padawan image tag `localhost/padawan:dev`.
- Coturn uses a fully qualified public image.
- Manifests validate through WorkerBee.
- WorkerBee local validation uses direct containerd profiles through
  `workerbee_v1_profile_start`, `workerbee_v1_manifest_deploy_local` with
  `target="profile"`, `workerbee_v1_profile_workload_status`, and
  `workerbee_v1_logs(target="profile")`.
- `workerbee_v1_capabilities` must show `runtime.selected == containerd` before
  the run begins.
- Default local profile: `k1s-dev-min-sqlite`; HA-shaped local validation can
  use `k1s-ha-min`.
- WorkerBee runbook records profile runtime, profile name, status/log commands,
  and validation commands.

Validation gate:

- Compose config renders.
- WorkerBee image build succeeds in the native containerd-backed flow.
- WorkerBee manifest prepare and validate succeed.
- WorkerBee profile deployment serves `/healthz`, `/peer`, and ICE config from
  the profile endpoint.

## Phase 4: Browser Evidence Automation

Goal: make visual and behavioral evidence repeatable instead of ad hoc.

Checkpoint commit: `feat: add peer browser evidence runner`

Required work:

- Add Playwright configuration with fake camera/microphone media.
- Add `npm run evidence:peer`.
- Open independent Padawan and Jedi browser contexts against `PADAWAN_BASE_URL`.
- Select `none` ICE for deterministic same-host loopback evidence.
- Create a token from the Jedi side and join from the Padawan side.
- Assert data channel open on both sides.
- Assert local and remote media streams exist on both sides.
- Send chat from Padawan to Jedi.
- Send a course from Jedi to Padawan.
- Send progress from Padawan to Jedi.
- Capture screenshots and write `peer-flow-summary.json`.
- If `SIMULACRA_RUN_ID` and `SIMULACRA_TRACK` are set, append an `evidence`
  event to that track's event log.

Validation gate:

- `npm test -- --list` discovers the evidence test.
- `PADAWAN_BASE_URL=http://127.0.0.1:<port> npm run evidence:peer` passes
  against source-served Padawan.
- The same command passes against the WorkerBee profile-served Padawan endpoint.

## Phase 5: k1s Dev HA Deployment

Goal: validate both tracks on the shared k1s dev HA target.

Checkpoint commits:

- `ops: add k1s dev deployment notes`
- `test: record k1s dev evidence`

Plain track path:

- Build image using the allowed local tooling.
- Push/tag according to the dev HA registry policy.
- Deploy using `ae` CLI or Hive dashboard only.
- Collect logs and ingress/test output manually or through allowed CLI.
- Record all manual commands and copy/paste log actions as measured events.

WorkerBee track path:

- Build image through WorkerBee or the repo build command as allowed by the
  runbook.
- Stage, validate, and deploy manifests through WorkerBee.
- Use WorkerBee profile/native-containerd local validation before the remote k1s
  dev HA deployment.
- Inspect status, logs, exec, and ingress probes through WorkerBee.
- Record WorkerBee actions as `workerbee_tool` events.

Validation gate for both tracks:

- k1s deployment is running with Padawan and coturn.
- Public or dev ingress loads `/peer`.
- ICE config points at the deployed TURN host.
- Browser evidence runner passes against the deployed base URL.
- Screenshots and optional video are linked into the run event log.

## Phase 6: Calibration Runs

Goal: dry-run the whole protocol before baseline measurements.

Checkpoint commit: `test: add calibration run report`

Required work:

- Run one calibration for `plain-codex`.
- Run one calibration for `workerbee-codex`.
- Do not use calibration data in final claims.
- Adjust prompt wording, missing event capture, and evidence scripts only after
  both calibrations are reviewed.

Validation gate:

- Both calibration reports render.
- Both contain prompt counts, command counts, token usage, timeline entries,
  evidence links, and any protocol violations.
- The same feature outcome is demonstrated in both tracks.

## Phase 7: Baseline Measurement Runs

Goal: produce enough paired samples to compare patterns without overfitting one
run.

Checkpoint commits:

- `data: record baseline run 001`
- `data: record baseline run 002`
- `data: record baseline run 003`

Protocol:

- Run at least three paired samples after calibration.
- Use the same ordered prompt checkpoints for both tracks.
- Keep the human operator policy consistent.
- Reset local run state before each pair.
- Preserve all event logs, Codex JSONL, screenshots, videos, reports, and
  generated graphs under `.local/runs/<run-id>/`.

Validation gate:

- Each pair reaches the same acceptance state.
- Each pair has complete event streams and evidence artifacts.
- Reports render without missing required metrics.

## Phase 8: Analysis And Output Package

Goal: produce reviewable artifacts for humans and repeatable artifacts for other
developers.

Checkpoint commits:

- `feat: add comparison graphs`
- `docs: add executive and technical reports`

Required outputs:

- Executive summary.
- Technical report.
- Two-box evidence review comparing the two systems.
- Screenshot sets.
- Timeline, prompt-count, command-count, token, and repair-loop graphs.
- Architecture and pipeline diagrams.
- Reproduction instructions for cloning and rerunning the simulation.

Analysis expectations:

- Prefer trend and variance language over single-run claims.
- Separate measured data from interpretation.
- Show where the human submitted prompts.
- Show where manual console work occurred.
- Show where WorkerBee removed manual work or changed repair-loop behavior.

Validation gate:

- Reports link to concrete evidence artifacts.
- Graphs are generated from JSONL data, not hand-entered values.
- A fresh clone can run preflight, initialize a run, capture peer evidence, and
  render a report.

## Initial Suggested Path

The current best path is to finish the WorkerBee-backed proof loop first, then
use it as the reference behavior for the constrained plain-Codex track. This
reduces ambiguity: the target feature and evidence runner are proven before the
experiment intentionally adds the plain-track manual time tax.

Immediate order:

1. Keep Padawan feature checkpoints green.
2. Start or select a WorkerBee MCP runtime with selected runtime `containerd`.
3. Rerun WorkerBee local validation through the native containerd profile path.
4. Add k1s dev HA deployment notes and registry target values.
5. Run one WorkerBee calibration.
6. Run one plain-Codex calibration with Podman Compose and manual k1s actions.
7. Repair instrumentation gaps found by calibration.
8. Run three paired baselines.
9. Generate comparative reports and graphs.

This order avoids measuring a broken target and keeps every later run anchored
to artifacts that can be replayed.
