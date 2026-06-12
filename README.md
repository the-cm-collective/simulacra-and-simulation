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

## Track Policy

`plain-codex` can use Codex CLI, shell, Podman/Docker Compose, self-signed local
cert setup, and `ae`/k1s CLI or dashboard for k1s actions. It must not use
WorkerBee MCP.

`workerbee-codex` can use the same Codex CLI plus WorkerBee MCP for image
builds, manifest staging/validation/deployment, logs, exec, ingress probes,
remote k1s deployment, and security review.

Baseline measured runs are single-agent in both tracks. Subagents are a later
variant, not part of the baseline.
