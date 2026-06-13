from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SITE_RE = re.compile(
    r"^\s*("
    r"[A-Za-z][A-Za-z0-9+.-]*://[^\s{]+"
    r"|[A-Za-z0-9_.-]*\.[A-Za-z0-9_.-]+(?::\d+)?"
    r"|:\d+"
    r")\s*\{"
)


@dataclass(frozen=True)
class CaddyFinding:
    severity: str
    message: str


@dataclass(frozen=True)
class CaddyPreflight:
    ok: bool
    findings: list[CaddyFinding]
    files: list[Path]


def check_workerbee_caddy_routes(
    state_root: Path,
    *,
    project: str | None = None,
) -> CaddyPreflight:
    project_root = state_root / "projects"
    files = _caddy_files(project_root)
    findings: list[CaddyFinding] = []
    by_host: dict[str, list[Path]] = {}

    for path in files:
        for host in _site_hosts(path):
            by_host.setdefault(host, []).append(path)

    for host, paths in sorted(by_host.items()):
        unique_paths = sorted({item.resolve() for item in paths})
        if len(unique_paths) > 1:
            finding_paths = ", ".join(str(item) for item in unique_paths)
            findings.append(
                CaddyFinding(
                    severity="error",
                    message=f"duplicate Caddy site {host}: {finding_paths}",
                )
            )

    if project:
        project_caddy = state_root / "projects" / project / "caddy"
        project_files = sorted(path for path in files if project_caddy in path.parents)
        if project_files:
            finding_paths = ", ".join(str(path) for path in project_files)
            findings.append(
                CaddyFinding(
                    severity="error",
                    message=f"project {project} has pre-existing Caddy routes: {finding_paths}",
                )
            )

    return CaddyPreflight(
        ok=not any(finding.severity == "error" for finding in findings),
        findings=findings,
        files=files,
    )


def _caddy_files(project_root: Path) -> list[Path]:
    if not project_root.exists():
        return []
    return sorted(path for path in project_root.glob("*/caddy/*.caddy") if path.is_file())


def _site_hosts(path: Path) -> list[str]:
    hosts: list[str] = []
    brace_depth = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            brace_depth += line.count("{") - line.count("}")
            brace_depth = max(brace_depth, 0)
            continue
        match = SITE_RE.match(line) if brace_depth == 0 else None
        if match:
            hosts.append(match.group(1))
        brace_depth += line.count("{") - line.count("}")
        brace_depth = max(brace_depth, 0)
    return hosts
