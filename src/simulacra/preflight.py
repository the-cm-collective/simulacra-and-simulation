from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Paths
from .scenario import Scenario


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def run_preflight(paths: Paths, scenario: Scenario | None = None) -> list[Check]:
    required_commands = _list_value(
        scenario.preflight.get("required_commands") if scenario else None,
        [
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
    )
    required_files = _list_value(
        scenario.preflight.get("required_files") if scenario else None,
        ["/run/containerd/containerd.sock"],
    )
    checks = [
        _dir_check(f"{paths.target_label.lower()} checkout", paths.target_root),
        _dir_check("k1s checkout", paths.k1s_root),
        _dir_check("workerbee checkout", paths.workerbee_root),
    ]
    checks.extend(_command_check(command) for command in required_commands)
    checks.extend(
        _file_check(Path(file_path).name, Path(file_path)) for file_path in required_files
    )
    if paths.target_root.exists():
        checks.append(_git_check(f"{paths.target_label.lower()} git", paths.target_root))
    if paths.k1s_root.exists():
        checks.append(_git_check("k1s git", paths.k1s_root))
    return checks


def _dir_check(name: str, path: Path) -> Check:
    return Check(name=name, ok=path.is_dir(), detail=str(path))


def _file_check(name: str, path: Path) -> Check:
    return Check(name=name, ok=path.exists(), detail=str(path))


def _command_check(name: str) -> Check:
    path = shutil.which(name)
    return Check(name=name, ok=path is not None, detail=path or "not found")


def _git_check(name: str, cwd: Path) -> Check:
    proc = subprocess.run(
        ["git", "status", "--short", "--branch"],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    output = (proc.stdout or proc.stderr).strip()
    return Check(name=name, ok=proc.returncode == 0, detail=output)


def _list_value(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if not isinstance(value, list):
        return list(default)
    return [str(item) for item in value]
