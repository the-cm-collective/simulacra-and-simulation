# Simulacra And Simulation

Reproducible dual-track simulation harness for comparing:

- a human developer using Codex CLI
- a human developer using Codex CLI plus WorkerBee MCP

The default target feature is Padawan/Jedi peer collaboration with WebRTC
audio/video, text chat, data-channel course transfer, and progress sync. Custom
scenarios can point the harness at a different target repository and feature
prompt.

## Repository Shape

This repository owns the experiment harness, evidence capture, metric schema,
prompt protocol, and generated reports. It does not vendor Padawan, k1s, or
WorkerBee. By default it expects the sibling checkout layout:

```text
k1s-wt/
  k1s/
  k1s-workerbee/
  padawan/
  simulacra-and-simulation/
```

Mutable run state, copied Codex homes, videos, screenshots, logs, generated
reports, k1s tokens, and TURN credentials live under `.local/` and are ignored.

The detailed multiphase execution plan is in
[`docs/implementation-plan.md`](docs/implementation-plan.md). The corrected
baseline rerun procedure is in
[`docs/baseline-retest-plan.md`](docs/baseline-retest-plan.md).
Custom scenario configuration is described in
[`docs/scenario-config.md`](docs/scenario-config.md).

## Quickstart

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e .[dev]
simctl preflight
simctl check-workerbee-caddy --state-root /tmp/workerbee-containerd-verify \
  --project baseline-001-wb
simctl check-k1s-dev-a-ingress
simctl cleanup-k1s-dev-a --run-id calib-001
simctl init-run --run-id calib-001
```

By default `init-run` creates the paired comparison lanes. To run one lane as
a standalone ops package, pass `--track`:

```bash
simctl init-run --run-id wb-only-001 --track workerbee-codex
simctl init-run --run-id plain-only-001 --track plain-codex
```

Single-lane reports keep audit status, metrics, evidence, billing, timeline,
and artifacts, but omit comparison deltas and paired scorecards.

To run the same harness against a custom repo, pass a scenario before the
subcommand:

```bash
simctl --scenario scenarios/my-app.yaml init-run --run-id my-app-001
simctl --scenario scenarios/my-app.yaml --set target.feature_prompt="Add import filters" \
  init-run --run-id my-app-002
```

For final `k1s-dev-a` HA evidence, the post-deploy ingress gate must prove the
target app route returned expected content, not just HTTP 200. This is the
default Padawan form:

```bash
simctl check-k1s-dev-a-ingress \
  --probe-url https://<padawan-app-host>/peer \
  --probe-body-contains Padawan
```

After final `k1s-dev-a` evidence, clean simulation-owned app records and runtime
containers outside the measured lane. Dry-run is the default; pass `--execute`
only after reviewing the selected records:

```bash
simctl cleanup-k1s-dev-a --run-id calib-001 --include-workerbee-profiles
simctl cleanup-k1s-dev-a --run-id calib-001 --include-workerbee-profiles --execute \
  > .local/runs/calib-001/<track>/commands/cleanup-k1s-dev-a-post-evidence.json
```

This cleanup command targets only simulation-owned records and WorkerBee
baseline profile namespaces. It does not prune unrelated `default/live-*`
workloads or reserved containerd namespaces.

Record measured prompts and actions before rendering reports:

```bash
simctl record-prompt --run-id calib-001 --track plain-codex --prompt-file prompt.md
simctl record-command --run-id calib-001 --track workerbee-codex \
  --event-type workerbee_tool --source workerbee \
  --summary "checked WorkerBee capabilities" --command "workerbee_v1_capabilities"
simctl record-touch --run-id calib-001 --track plain-codex \
  --kind copy_logs --summary "copied console logs into Codex"
simctl ingest-codex --run-id calib-001 --track plain-codex --jsonl codex.jsonl
simctl audit-run --run-id calib-001
simctl render-report --run-id calib-001
simctl export-html --run-id calib-001
```

The HTML export writes a local browser review set to
`.local/runs/<run-id>/html/`: executive, summary, technical, charts, timeline,
and artifact pages with links back to prompts, Codex JSONL/final responses,
command logs, screenshots, videos, JSON summaries, event logs, and `report.md`.
The executive, summary, and technical pages show the target repo, feature/input
prompt, repository roots, runtime policy, preflight gates, ingress expectations,
evidence command, and WorkerBee stage patch settings from the frozen run
manifest. Run `simctl audit-run` before report export to add public-report audit
status, blocking findings, warnings, and timing/provenance checks to the
Markdown and HTML packages.
For LAN preview, serve the run root, not the `html/` subdirectory, so artifact
links such as `../plain-codex/...` and `../workerbee-codex/...` remain
reachable from remote browsers.
Operator touches are derived from human prompts, human shell commands,
`ae`/dashboard actions, and explicit `record-touch` events. The charts page uses
a local Chart.js bundle and the k1s docs light/dark visual system to map
operator touches, command/tool actions, captured Codex tokens, MCP observation
tokens, estimated all-in input tokens, and per-turn Codex input-token usage over
time. Runtime deltas use realistic runtime:
first-to-last measured non-checkpoint/preflight event plus explicit manual time-tax
seconds from `record-touch --duration-seconds`. Raw event span and excluded
checkpoint idle remain visible only for audit review. Captured Codex tokens sum
each recorded Codex turn. MCP observation tokens estimate targeted WorkerBee
tool-result artifacts visible to the model, and estimated all-in input tokens
combine the two streams unless an observation is explicitly marked as already
included in Codex usage. Per-turn input is usage metadata, not a literal
context-window measurement; it is useful as a context-pressure proxy only in
controlled no-tool probe runs.
These token metrics are suitable for lane comparison, but they are not an
authoritative billing reconciliation. Final billable-token or cost proof
requires provider-side usage/cost records for the account or organization that
ran the requests. The Codex CLI exposes transcript and usage-snapshot surfaces,
not a local billing ledger; use Platform/admin usage and costs APIs, or the
applicable ChatGPT Enterprise usage-monitoring surface, for final reconciliation.
See `docs/billing-reconciliation.md` for the implementation boundary.
For OpenAI Platform API-key runs, use separate projects or API keys for each
lane, prepare run-scoped Codex auth homes outside the report package, then
reconcile the completed run against organization usage/cost records:

```bash
export SIM_OPENAI_KEY_PLAIN=...
export SIM_OPENAI_KEY_WORKERBEE=...
export OPENAI_ADMIN_KEY=...
simctl prepare-openai-api-auth --run-id calib-001 --track plain-codex \
  --api-key-env SIM_OPENAI_KEY_PLAIN
simctl prepare-openai-api-auth --run-id calib-001 --track workerbee-codex \
  --api-key-env SIM_OPENAI_KEY_WORKERBEE
# pass the printed codex_home values to run-codex-checkpoint --codex-home
simctl reconcile-openai-usage --run-id calib-001 \
  --plain-project-id proj_plain... \
  --workerbee-project-id proj_workerbee...
```

For single-lane runs, use the generic active-track mapping form:

```bash
simctl reconcile-openai-usage --run-id wb-only-001 \
  --track-project-id workerbee-codex=proj_workerbee...
```

API key values are read from environment variables and are not written to run
events, reports, HTML exports, or archives.
The strict plain-Codex lane uses `simctl run-codex-checkpoint` with a
run-scoped Codex session: checkpoint 1 starts the session and later checkpoints
resume it. Prompt builders emit `.prompt-meta.json` sidecars so reports can show
copied log/doc bytes, source counts, truncation, and context-management touches.
Strict public audits block plain runs that omit sufficient copied context,
failure repair prompts, run-scoped session continuity, or observed HTTPS cert
evidence for `cert_setup` time tax.

Run tests:

```bash
ruff format --check
ruff check
pytest
```

Install the browser once and capture Padawan/Jedi peer-flow evidence against a
running Padawan instance:

```bash
npm install
npm run install-browsers
PADAWAN_BASE_URL=http://127.0.0.1:8787 npm run evidence:peer
```

To bind evidence to a simulation run, set `SIMULACRA_RUN_ID` and
`SIMULACRA_TRACK` (`plain-codex` or `workerbee-codex`). Screenshots and the JSON
summary are written below `.local/runs/<run>/<track>/evidence/` and an
`evidence` event is appended to the track event log.

## Track Policy

`plain-codex` can use Codex CLI, shell, Podman Compose or podman-compose,
self-signed local cert setup, and `ae`/k1s CLI or dashboard for k1s actions. It
must not use Docker for measured local container work and must not use WorkerBee
MCP.

`workerbee-codex` can use the same Codex CLI plus WorkerBee MCP for image
builds, manifest staging/validation/deployment, logs, exec, ingress probes,
remote k1s deployment, and security review. Measured local WorkerBee work must
use the native containerd profile path (`workerbee_v1_profile_start`,
`workerbee_v1_manifest_deploy_local(target="profile")`, profile logs/status, and
profile probes). Before measurement, `workerbee_v1_capabilities` must report
`runtime.selected == containerd`. The Podman-backed WorkerBee project path is
allowed only for non-baseline smoke tests.

For WorkerBee-lane-only operating loops, `simctl workerbee-lane` records
higher-level, scenario-aware automation events that can be audited and reported:

```bash
simctl workerbee-lane --run-id wb-only-001 --project sim-wb prepare
simctl workerbee-lane --run-id wb-only-001 --project sim-wb deploy-local
simctl workerbee-lane --run-id wb-only-001 --project sim-wb probe
simctl workerbee-lane --run-id wb-only-001 --project sim-wb collect-evidence
simctl workerbee-lane --run-id wb-only-001 --project sim-wb cleanup
```

These wrapper events document the intended WorkerBee MCP sequence and attach
targeted artifacts when provided. Run `simctl measure-mcp-artifacts` afterward
when those artifacts were visible to Codex as MCP/tool observations.

Baseline measured runs are single-agent in both tracks. Subagents are a later
variant, not part of the baseline.

## License

Licensed under the Apache License, Version 2.0. See [`LICENSE`](LICENSE).
