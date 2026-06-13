# Scenario Configuration

Simulacra uses Padawan as the built-in scenario. A custom scenario can replace
the target repo and feature prompt without changing the two measured tracks:
`plain-codex` and `workerbee-codex`.

Pass scenario options before the subcommand:

```bash
simctl --scenario scenarios/my-app.yaml init-run --run-id my-app-001
simctl --scenario scenarios/my-app.yaml --set k1s_ingress.probe_body_contains=MyApp \
  init-run --run-id my-app-002
```

Relative paths in a scenario file resolve from that file's directory. Relative
paths passed through `--set` resolve from the scenario file directory when one
is provided, or from the harness repo root when no scenario file is used.

## Minimal Custom Repo Scenario

```yaml
name: my-app-feature
target:
  label: MyApp
  repo_root: ../my-app
  feature_prompt: |
    Add the requested feature to MyApp and validate it through both tracks.
k1s_ingress:
  probe_body_contains: MyApp
evidence:
  command: npm run evidence:my-app
  base_url_env: MY_APP_BASE_URL
workerbee_stage:
  manifest: manifests/my-app.k1s.yaml
  ingress_host_path: spec.ingress.host
  env_updates:
    MY_APP_PUBLIC_HOST: "{app_host}"
```

## Supported Fields

- `name`: scenario identifier recorded in the run manifest.
- `target.label`: human-readable target name used by preflight and reports.
- `target.repo_root`: repo where Codex should work instead of the default
  `../padawan`.
- `target.feature_prompt`: default feature prompt copied into `manifest.json`.
- `k1s.repo_root` and `workerbee.repo_root`: sibling checkout overrides.
- `runtime_policy`: per-track policy text rendered into reports.
- `preflight.required_commands`: commands checked by `simctl preflight`.
- `preflight.required_files`: files checked by `simctl preflight`.
- `k1s_ingress.namespace`: default namespace for
  `simctl check-k1s-dev-a-ingress`.
- `k1s_ingress.controller_deployment`: default controller deployment name.
- `k1s_ingress.probe_body_contains`: expected app marker for final ingress
  probes.
- `evidence.command`: documented evidence command for the scenario.
- `workerbee_stage.manifest`: manifest path inside the WorkerBee stage.
- `workerbee_stage.domain`: default WorkerBee app domain suffix.
- `workerbee_stage.app_host_template`: Python format string using
  `{project}` and `{domain}`.
- `workerbee_stage.ingress_host_path`: dotted YAML path to patch with the app
  host.
- `workerbee_stage.env_updates`: environment variable templates using
  `{project}`, `{domain}`, and `{app_host}`.

Each `init-run` writes the fully resolved scenario into
`.local/runs/<run-id>/manifest.json`. Later run-scoped commands that accept
`--run-id` read that frozen scenario snapshot, so a run remains reproducible
even if the scenario YAML changes.
