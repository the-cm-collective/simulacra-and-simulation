from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def patch_padawan_stage(
    stage_dir: Path,
    *,
    project: str,
    app_host: str | None = None,
    domain: str = "workerbee.localhost",
) -> dict[str, str]:
    host = app_host or f"app.{project}.{domain}"
    manifest_path = stage_dir / "manifests" / "padawan.k1s.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Padawan manifest not found: {manifest_path}")

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"Padawan manifest is not a YAML mapping: {manifest_path}")

    spec = _mapping(manifest, "spec")
    ingress = _mapping(spec, "ingress")
    ingress["host"] = host

    env = spec.setdefault("env", [])
    if not isinstance(env, list):
        raise ValueError(f"Padawan manifest spec.env is not a list: {manifest_path}")
    _set_env(env, "PADAWAN_TURN_HOST", host)

    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, width=1000),
        encoding="utf-8",
    )
    return {"manifest": str(manifest_path), "app_host": host}


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.setdefault(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Expected {key} to be a mapping")
    return value


def _set_env(env: list[Any], name: str, value: str) -> None:
    for item in env:
        if isinstance(item, dict) and item.get("name") == name:
            item["value"] = value
            return
    env.append({"name": name, "value": value})
