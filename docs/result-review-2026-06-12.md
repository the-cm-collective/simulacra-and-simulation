# Result Review - 2026-06-12

## Status

The current artifacts prove the Padawan peer feature and browser evidence
automation, but they are not valid baseline simulation results.

## What Passed

- Padawan branch `simulacra-and-simulation` includes peer signaling, peer UI,
  runtime assets, WorkerBee manifests, and the offer-resend fix for the normal
  create-token-then-join flow.
- Padawan validation passed with `40 passed, 1 skipped`; static JavaScript
  parsing passed.
- Simulation harness branch `dev` includes run initialization, event schema,
  Codex JSONL ingest, report rendering, a multiphase plan, and a Playwright
  peer evidence runner.
- Harness validation passed with `ruff format --check`, `ruff check`, and
  `pytest`.
- The Playwright peer flow passed against source-served Padawan and against the
  WorkerBee-served Padawan endpoint at `http://127.0.0.1:8787`.
- The evidence runner confirmed data channel open, local and remote media
  streams on both sides, chat transfer, course transfer, and progress transfer.

## Current Evidence

Current run artifacts exist only under:

```text
.local/runs/calib-001/workerbee-codex/
```

The latest evidence summary reports:

- base URL: `http://127.0.0.1:8787`
- course ID: `git-advanced`
- data channel: `open`
- ICE profile: `none`
- video recording: `false`

Screenshots:

- `.local/runs/calib-001/workerbee-codex/evidence/screenshots/peer-flow/jedi-peer.png`
- `.local/runs/calib-001/workerbee-codex/evidence/screenshots/peer-flow/padawan-peer.png`

## Findings

- The feature proof is good: the Padawan/Jedi interaction works through the
  automated browser flow.
- The evidence automation is good: the same test can target source, local
  runtime, WorkerBee, or k1s dev HA by changing `PADAWAN_BASE_URL`.
- The current WorkerBee runtime evidence used a Podman-backed WorkerBee project
  path. WorkerBee project status reported `runtime: podman`.
- The corrected policy requires the `workerbee-codex` measured local runtime to
  use WorkerBee's native containerd profile path, not the Podman-backed project
  runtime.
- This MCP session reported WorkerBee `runtime.selected` as `podman`; the rerun
  must start from a WorkerBee MCP runtime that reports `runtime.selected` as
  `containerd`.
- There is no comparable `plain-codex` run yet.
- The current event log has evidence events only; it does not contain the full
  prompt, command, token, context-growth, or repair-loop data needed for the
  simulation claim.

## Conclusion

Treat the current data as a smoke-test and feature-proof result only. It should
not be used in the final comparison.

The simulation must be rerun with this runtime policy:

- `plain-codex`: Podman Compose or podman-compose for measured local container
  work; no Docker and no WorkerBee MCP.
- `workerbee-codex`: WorkerBee native containerd profile path for measured local
  WorkerBee work; use profile start/status/log/deploy tools and
  `target="profile"` after confirming `workerbee_v1_capabilities` reports
  `runtime.selected == containerd`.

Recommended next run IDs:

- `calib-002-workerbee-containerd`
- `calib-002-plain-podman`

After both calibrations pass, start baseline pairs from `baseline-001`.
