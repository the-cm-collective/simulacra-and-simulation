# Result Review - 2026-06-12

## Status

The current artifacts prove the Padawan peer feature, the browser evidence
runner, the plain Podman runtime path, and the WorkerBee direct-containerd
profile path. They are still not valid baseline simulation results because the
measurement stream is incomplete.

## What Passed

- Padawan branch `simulacra-and-simulation` includes peer signaling, peer UI,
  runtime assets, WorkerBee manifests, and the offer-resend fix for the normal
  create-token-then-join flow.
- Padawan validation previously passed with `40 passed, 1 skipped`; static
  JavaScript parsing passed.
- The Playwright peer flow passed against the plain Podman runtime at
  `http://127.0.0.1:8787`.
- The Playwright peer flow passed against the WorkerBee direct-containerd
  profile runtime at `http://127.0.0.1:8787`.
- The evidence runner confirmed data channel open, local and remote media
  streams on both sides, chat transfer, course transfer, and progress transfer.
- Podman Compose compatibility was restored for this system by installing
  `podman-compose`.
- WorkerBee direct-containerd validation was proven through
  `scripts/dev/wb-containerd` with project `simcal2`, profile
  `k1s-dev-min-sqlite`, image `localhost/padawan:dev`, Padawan on port `8787`,
  and coturn on port `3478`.

## Current Calibration Artifacts

WorkerBee direct-containerd calibration:

```text
.local/runs/calib-002-workerbee-containerd/report.md
```

- `workerbee-codex`: 2 events, 1 evidence artifact.
- `plain-codex`: checkpoint only.
- Prompt, command, and token metrics are all zero.

Plain Podman calibration:

```text
.local/runs/calib-002-plain-podman/report.md
```

- `plain-codex`: 2 events, 1 evidence artifact.
- `workerbee-codex`: checkpoint only.
- Prompt, command, and token metrics are all zero.

Evidence screenshots and summary JSON are present under each run's track
`evidence/` directory.

## Findings

- The feature proof is good: the Padawan/Jedi interaction works through the
  automated browser flow in both required local runtimes.
- The corrected runtime policy is now clear: `plain-codex` uses Podman, and
  `workerbee-codex` uses WorkerBee's native containerd profile path.
- The configured WorkerBee MCP endpoint still reports the Podman-backed project
  runtime, so measured WorkerBee runs must continue to use
  `scripts/dev/wb-containerd` until the MCP endpoint is switched to the same
  containerd backend.
- The reports showed zero prompt, command, and token metrics because the
  calibration commands were not recorded through the harness and the Codex JSONL
  transcripts were not ingested.
- The WorkerBee stage contained a stale hardcoded ingress/TURN host. That caused
  route ambiguity during local profile deployment and had to be corrected before
  baseline measurement.

## Required Corrections Before Baseline

- Use `simctl record-prompt` for every human prompt.
- Use `simctl record-command` for shell commands, WorkerBee actions, and `ae`
  actions.
- Use `simctl ingest-codex` for every captured `codex exec --json` transcript.
- Use `simctl patch-workerbee-stage` after WorkerBee manifest preparation and
  before validation/deployment.
- Treat any baseline report with zero prompt, command/tool, evidence, or token
  usage as incomplete.

## Conclusion

The current data should be retained as runtime smoke-test evidence only. The
next valid comparison starts with the paired `baseline-001` retest described in
[`baseline-retest-plan.md`](baseline-retest-plan.md).
