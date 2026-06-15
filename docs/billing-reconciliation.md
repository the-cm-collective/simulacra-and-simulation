# Billing Reconciliation Boundary

The simulation report distinguishes comparative token measurement from final
billing reconciliation.

## What the Harness Measures

- Captured Codex token usage from Codex JSONL usage snapshots.
- WorkerBee MCP observation payload tokens from targeted artifact tokenization.
- Estimated all-in input tokens: captured Codex input tokens plus visible MCP
  observation tokens, minus observations explicitly marked as already included
  in Codex usage.

These fields are appropriate for comparing the two simulation lanes. They are
not authoritative billing records.

## Codex CLI Boundary

Codex CLI can produce transcript and usage-snapshot evidence, including JSONL
events from `codex exec --json` and saved session token-count events. The
installed CLI exposes no local command that reconciles a run to final billed
tokens or monetary cost. Treat CLI output as measurement evidence, not as the
billing ledger.

## Final Billing Layer

Final billable-token or cost proof requires provider-side usage/cost records:

- For Codex authenticated with an OpenAI Platform API key, use OpenAI
  Platform/admin usage and costs APIs or dashboard exports. Prefer isolating
  each sim lane with a distinct API project or API key so usage can be grouped
  by `project_id` or `api_key_id`.
- For Codex authenticated with ChatGPT plan credentials, Platform API usage
  endpoints are not the billing source for that run. ChatGPT Enterprise
  workspaces may have usage monitoring through enterprise/admin surfaces; for
  non-enterprise ChatGPT plan usage, treat local Codex usage snapshots as the
  highest available local measurement unless an official workspace billing
  export is available.

## Implemented OpenAI API-Key Path

The harness supports an optional OpenAI Platform reconciliation layer for
measured runs that use API-key authentication.

1. Create two OpenAI projects or project-scoped API keys: one for
   `plain-codex`, one for `workerbee-codex`.
2. Export lane key values only in the operator environment.
3. Prepare run-scoped Codex auth homes outside the report package:

```bash
simctl prepare-openai-api-auth --run-id baseline-001 --track plain-codex \
  --api-key-env SIM_OPENAI_KEY_PLAIN
simctl prepare-openai-api-auth --run-id baseline-001 --track workerbee-codex \
  --api-key-env SIM_OPENAI_KEY_WORKERBEE
```

The command runs `codex login --with-api-key` with the key on stdin and records
only redacted metadata: env var name, `codex_home`, Codex binary, return code,
and auth method. The default auth location is:

```text
.local/auth/codex-api/<run-id>/<track>/
```

Pass the printed `codex_home` to the measured `run-codex-checkpoint` commands.
The auth cache is outside `.local/runs/<run-id>/` so report archives do not
include key material.

After both lanes complete, reconcile usage and costs:

```bash
export OPENAI_ADMIN_KEY=...
simctl reconcile-openai-usage --run-id baseline-001 \
  --plain-project-id proj_plain... \
  --workerbee-project-id proj_workerbee...
```

The command calls OpenAI organization usage and costs admin endpoints, groups by
project/API key where available, writes raw provider JSON under
`.local/runs/<run-id>/billing/openai/`, writes normalized reconciliation to
`.local/runs/<run-id>/billing/reconciliation.json`, and appends sanitized
`billing_reconciliation` events to both lane streams.

Offline fixtures are supported for tests and review:

```bash
simctl reconcile-openai-usage --run-id baseline-001 \
  --plain-project-id proj_plain --workerbee-project-id proj_workerbee \
  --usage-json usage.fixture.json --costs-json costs.fixture.json
```

## Audit Contract

`reconcile-openai-usage` marks `manifest.billing_reconciliation.required=true`
by default. Public audit then requires:

- one provider reconciliation event per track
- distinct OpenAI project IDs for the two tracks
- nonzero provider input tokens for each track
- a match basis of `captured_codex` or `estimated_all_in`
- referenced raw and normalized billing artifacts to exist
- no secret-looking values in billing payloads

Provider cost values are warnings by default when missing because provider cost
records can lag usage records. Use `--require-costs` to make missing costs an
audit error.

Reports and HTML exports show provider-reconciled input/cache/output/request
counts and costs as a separate section. Local captured Codex and MCP estimated
all-in fields remain comparative measurements, not billing proof, unless the
provider reconciliation section is present and accepted by audit.

References:

- Codex authentication supports ChatGPT sign-in and API-key sign-in:
  https://developers.openai.com/codex/auth
- API-key Codex usage is billed through the OpenAI Platform account:
  https://developers.openai.com/codex/pricing
- Organization usage and costs are exposed through OpenAI API reference admin
  resources:
  https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage
