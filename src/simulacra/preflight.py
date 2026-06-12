from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Paths


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def run_preflight(paths: Paths) -> list[Check]:
    checks = [
        _dir_check("padawan checkout", paths.padawan_root),
        _dir_check("k1s checkout", paths.k1s_root),
        _dir_check("workerbee checkout", paths.workerbee_root),
        _command_check("python3"),
        _command_check("codex"),
        _command_check("podman"),
        _command_check("nerdctl"),
        _file_check("containerd socket", Path("/run/containerd/containerd.sock")),
        _command_check("microk8s"),
        _command_check("ae"),
        _command_check("k1s"),
        _command_check("ffmpeg"),
        _command_check("node"),
        _command_check("npm"),
    ]
    if paths.padawan_root.exists():
        checks.append(_git_check("padawan git", paths.padawan_root))
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
