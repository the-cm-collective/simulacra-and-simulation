from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RUNTIME_POLICY: dict[str, dict[str, Any]] = {
    "plain-codex": {
        "local_container_runtime": "podman",
        "compose_engine": "podman compose or podman-compose",
        "workerbee_allowed": False,
        "docker_allowed_in_measured_run": False,
        "k1s_actions": "ae CLI or Hive dashboard only",
    },
    "workerbee-codex": {
        "local_container_runtime": "workerbee native containerd profile",
        "workerbee_target": "profile",
        "default_profile": "k1s-dev-min-sqlite",
        "ha_profile": "k1s-ha-min",
        "podman_project_runtime_allowed_in_measured_run": False,
    },
}

DEFAULT_FEATURE_PROMPT = (
    "Add Padawan/Jedi peer collaboration with WebRTC audio/video, text chat, "
    "data-channel course transfer, local progress sync, local-only user state, "
    "and a session token that either role can generate."
)


@dataclass(frozen=True)
class Scenario:
    name: str
    source: str
    target_label: str
    target_root: Path
    feature_prompt: str
    k1s_root: Path
    workerbee_root: Path
    runtime_policy: dict[str, Any]
    preflight: dict[str, Any]
    k1s_ingress: dict[str, Any]
    evidence: dict[str, Any]
    workerbee_stage: dict[str, Any]

    def to_manifest(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "target": {
                "label": self.target_label,
                "repo_root": str(self.target_root),
                "feature_prompt": self.feature_prompt,
            },
            "k1s": {"repo_root": str(self.k1s_root)},
            "workerbee": {"repo_root": str(self.workerbee_root)},
            "runtime_policy": copy.deepcopy(self.runtime_policy),
            "preflight": copy.deepcopy(self.preflight),
            "k1s_ingress": copy.deepcopy(self.k1s_ingress),
            "evidence": copy.deepcopy(self.evidence),
            "workerbee_stage": copy.deepcopy(self.workerbee_stage),
        }


def load_scenario(
    repo_root: Path,
    scenario_file: Path | None = None,
    overrides: list[str] | None = None,
) -> Scenario:
    root = repo_root.resolve()
    data = _default_scenario_data(root)
    source = "built-in:padawan-peer"
    path_base = root

    if scenario_file is not None:
        scenario_path = scenario_file.expanduser().resolve()
        loaded = _read_scenario_yaml(scenario_path)
        data = _deep_merge(data, loaded)
        source = str(scenario_path)
        path_base = scenario_path.parent

    for override in overrides or []:
        _apply_override(data, override)

    return scenario_from_mapping(data, source=source, path_base=path_base)


def load_run_scenario(run_root: Path, fallback: Scenario) -> Scenario:
    manifest_path = run_root / "manifest.json"
    if not manifest_path.exists():
        return fallback
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenario_data = manifest.get("scenario")
    if not isinstance(scenario_data, dict):
        return fallback
    return scenario_from_mapping(
        scenario_data,
        source=f"manifest:{run_root.name}",
        path_base=run_root,
    )


def scenario_from_mapping(
    data: dict[str, Any],
    *,
    source: str,
    path_base: Path,
) -> Scenario:
    target = _mapping(data, "target")
    k1s = _mapping(data, "k1s")
    workerbee = _mapping(data, "workerbee")
    return Scenario(
        name=str(data.get("name") or "custom"),
        source=source,
        target_label=str(target.get("label") or "Target"),
        target_root=_resolve_path(target.get("repo_root"), path_base),
        feature_prompt=str(target.get("feature_prompt") or ""),
        k1s_root=_resolve_path(k1s.get("repo_root"), path_base),
        workerbee_root=_resolve_path(workerbee.get("repo_root"), path_base),
        runtime_policy=_copy_mapping(data.get("runtime_policy")),
        preflight=_copy_mapping(data.get("preflight")),
        k1s_ingress=_copy_mapping(data.get("k1s_ingress")),
        evidence=_copy_mapping(data.get("evidence")),
        workerbee_stage=_copy_mapping(data.get("workerbee_stage")),
    )


def _default_scenario_data(repo_root: Path) -> dict[str, Any]:
    sibling_root = repo_root.parent
    return {
        "name": "padawan-peer",
        "target": {
            "label": "Padawan",
            "repo_root": str(sibling_root / "padawan"),
            "feature_prompt": DEFAULT_FEATURE_PROMPT,
        },
        "k1s": {"repo_root": str(sibling_root / "k1s")},
        "workerbee": {"repo_root": str(sibling_root / "k1s-workerbee")},
        "runtime_policy": copy.deepcopy(DEFAULT_RUNTIME_POLICY),
        "preflight": {
            "local_ports": [8787, 3478],
            "required_commands": [
                "python3",
                "codex",
                "podman",
                "nerdctl",
                "microk8s",
                "ae",
                "k1s",
                "ffmpeg",
                "node",
                "npm",
            ],
            "required_files": ["/run/containerd/containerd.sock"],
        },
        "k1s_ingress": {
            "namespace": "k1s-dev-a",
            "controller_deployment": "k1s-dev-a-k1s-core-ha-controller",
            "probe_body_contains": "Padawan",
        },
        "evidence": {
            "command": "npm run evidence:peer",
            "base_url_env": "PADAWAN_BASE_URL",
            "phase_env": "SIMULACRA_EVIDENCE_PHASE",
        },
        "workerbee_stage": {
            "manifest": "manifests/padawan.k1s.yaml",
            "domain": "workerbee.localhost",
            "app_host_template": "app.{project}.{domain}",
            "ingress_host_path": "spec.ingress.host",
            "env_updates": {"PADAWAN_TURN_HOST": "{app_host}"},
        },
    }


def _read_scenario_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Scenario file must be a YAML mapping: {path}")
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _apply_override(data: dict[str, Any], override: str) -> None:
    if "=" not in override:
        raise ValueError(f"Scenario override must use key=value: {override}")
    raw_key, raw_value = override.split("=", 1)
    keys = [part.strip() for part in raw_key.split(".") if part.strip()]
    if not keys:
        raise ValueError(f"Scenario override key is empty: {override}")
    value = yaml.safe_load(raw_value)
    cursor: dict[str, Any] = data
    for key in keys[:-1]:
        current = cursor.setdefault(key, {})
        if not isinstance(current, dict):
            raise ValueError(f"Scenario override crosses non-mapping key: {raw_key}")
        cursor = current
    cursor[keys[-1]] = value


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    raise ValueError(f"Scenario {key} must be a mapping")


def _copy_mapping(value: Any) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _resolve_path(value: Any, base: Path) -> Path:
    raw = Path(str(value or "")).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    return (base / raw).resolve()
