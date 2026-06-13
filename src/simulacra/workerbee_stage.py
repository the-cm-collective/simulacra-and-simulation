from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_PADAWAN_STAGE = {
    "manifest": "manifests/padawan.k1s.yaml",
    "domain": "workerbee.localhost",
    "app_host_template": "app.{project}.{domain}",
    "ingress_host_path": "spec.ingress.host",
    "env_updates": {"PADAWAN_TURN_HOST": "{app_host}"},
}


def patch_stage(
    stage_dir: Path,
    *,
    project: str,
    stage_config: dict[str, Any],
    app_host: str | None = None,
    domain: str | None = None,
    manifest: str | Path | None = None,
    ingress_host_path: str | None = None,
    env_updates: dict[str, str] | None = None,
) -> dict[str, str]:
    resolved_domain = domain or str(stage_config.get("domain") or "workerbee.localhost")
    host = app_host or _render_template(
        str(stage_config.get("app_host_template") or "app.{project}.{domain}"),
        project=project,
        domain=resolved_domain,
        app_host="",
    )
    manifest_value = manifest or stage_config.get("manifest") or DEFAULT_PADAWAN_STAGE["manifest"]
    manifest_path = _stage_manifest_path(stage_dir, manifest_value)
    if not manifest_path.exists():
        raise FileNotFoundError(f"WorkerBee stage manifest not found: {manifest_path}")

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"WorkerBee stage manifest is not a YAML mapping: {manifest_path}")

    spec = _mapping(manifest, "spec")
    host_path = ingress_host_path or str(stage_config.get("ingress_host_path") or "")
    if host_path:
        _set_dotted(manifest, host_path, host)

    updates = dict(stage_config.get("env_updates") or {})
    if env_updates:
        updates.update(env_updates)
    env = spec.setdefault("env", []) if updates else []
    if updates and not isinstance(env, list):
        raise ValueError(f"WorkerBee stage manifest spec.env is not a list: {manifest_path}")
    for name, value_template in updates.items():
        _set_env(
            env,
            str(name),
            _render_template(
                str(value_template),
                project=project,
                domain=resolved_domain,
                app_host=host,
            ),
        )

    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, width=1000),
        encoding="utf-8",
    )
    return {
        "manifest": str(manifest_path),
        "app_host": host,
        "domain": resolved_domain,
    }


def patch_padawan_stage(
    stage_dir: Path,
    *,
    project: str,
    app_host: str | None = None,
    domain: str = "workerbee.localhost",
) -> dict[str, str]:
    return patch_stage(
        stage_dir,
        project=project,
        stage_config=DEFAULT_PADAWAN_STAGE,
        app_host=app_host,
        domain=domain,
    )


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.setdefault(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Expected {key} to be a mapping")
    return value


def _stage_manifest_path(stage_dir: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else stage_dir / path


def _set_dotted(document: dict[str, Any], dotted_path: str, value: str) -> None:
    keys = [part for part in dotted_path.split(".") if part]
    if not keys:
        return
    cursor = document
    for key in keys[:-1]:
        cursor = _mapping(cursor, key)
    cursor[keys[-1]] = value


def _set_env(env: list[Any], name: str, value: str) -> None:
    for item in env:
        if isinstance(item, dict) and item.get("name") == name:
            item["value"] = value
            return
    env.append({"name": name, "value": value})


def _render_template(template: str, *, project: str, domain: str, app_host: str) -> str:
    return template.format(project=project, domain=domain, app_host=app_host)
