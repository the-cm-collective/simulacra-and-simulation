from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    repo_root: Path
    padawan_root: Path
    k1s_root: Path
    workerbee_root: Path

    @property
    def local_dir(self) -> Path:
        return self.repo_root / ".local"

    @property
    def runs_dir(self) -> Path:
        return self.local_dir / "runs"


def default_paths(repo_root: Path | None = None) -> Paths:
    root = (repo_root or Path.cwd()).resolve()
    sibling_root = root.parent
    return Paths(
        repo_root=root,
        padawan_root=sibling_root / "padawan",
        k1s_root=sibling_root / "k1s",
        workerbee_root=sibling_root / "k1s-workerbee",
    )
