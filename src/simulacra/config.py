from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .scenario import Scenario, load_scenario


@dataclass(frozen=True)
class Paths:
    repo_root: Path
    target_root: Path
    target_label: str
    k1s_root: Path
    workerbee_root: Path

    @property
    def padawan_root(self) -> Path:
        return self.target_root

    @property
    def local_dir(self) -> Path:
        return self.repo_root / ".local"

    @property
    def runs_dir(self) -> Path:
        return self.local_dir / "runs"


def default_paths(repo_root: Path | None = None, scenario: Scenario | None = None) -> Paths:
    root = (repo_root or Path.cwd()).resolve()
    resolved = scenario or load_scenario(root)
    return Paths(
        repo_root=root,
        target_root=resolved.target_root,
        target_label=resolved.target_label,
        k1s_root=resolved.k1s_root,
        workerbee_root=resolved.workerbee_root,
    )
