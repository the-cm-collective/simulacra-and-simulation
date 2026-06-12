# Simulacra And Simulation

Reproducible dual-track simulation harness for comparing:

- a human developer using Codex CLI
- a human developer using Codex CLI plus WorkerBee MCP

The target feature is the Padawan Padawan/Jedi peer collaboration workflow with
WebRTC audio/video, text chat, data-channel course transfer, and progress sync.

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
[`docs/implementation-plan.md`](docs/implementation-plan.md).

## Quickstart

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e .[dev]
simctl preflight
simctl init-run --run-id calib-001
```

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

Baseline measured runs are single-agent in both tracks. Subagents are a later
variant, not part of the baseline.
