from __future__ import annotations

from pathlib import Path

from simulacra.caddy_preflight import check_workerbee_caddy_routes
from simulacra.cli import main


def test_caddy_preflight_detects_duplicate_hosts(tmp_path: Path) -> None:
    first = tmp_path / "projects" / "alpha" / "caddy" / "app.caddy"
    second = tmp_path / "projects" / "alpha" / "caddy" / "profile-workload.caddy"
    first.parent.mkdir(parents=True)
    first.write_text(
        "https://app.alpha.workerbee.localhost {\n    reverse_proxy 127.0.0.1:8787\n}\n",
        encoding="utf-8",
    )
    second.write_text(
        "# generated route\n"
        "https://app.alpha.workerbee.localhost {\n"
        "    reverse_proxy 127.0.0.1:8787\n"
        "}\n",
        encoding="utf-8",
    )

    result = check_workerbee_caddy_routes(tmp_path)

    assert not result.ok
    assert len(result.findings) == 1
    assert (
        "duplicate Caddy site https://app.alpha.workerbee.localhost" in result.findings[0].message
    )


def test_caddy_preflight_detects_stale_project_routes(tmp_path: Path) -> None:
    route = tmp_path / "projects" / "baseline-004-clean-wb" / "caddy" / "old.caddy"
    route.parent.mkdir(parents=True)
    route.write_text(
        "https://app.baseline-004-clean-wb.workerbee.localhost {\n"
        "    reverse_proxy 127.0.0.1:8787\n"
        "}\n",
        encoding="utf-8",
    )

    result = check_workerbee_caddy_routes(tmp_path, project="baseline-004-clean-wb")

    assert not result.ok
    assert "pre-existing Caddy routes" in result.findings[0].message


def test_caddy_preflight_ignores_nested_directives(tmp_path: Path) -> None:
    route = tmp_path / "projects" / "alpha" / "caddy" / "app.caddy"
    route.parent.mkdir(parents=True)
    route.write_text(
        "https://app.alpha.workerbee.localhost {\n"
        "    handle /healthz {\n"
        '        respond "ok"\n'
        "    }\n"
        "    log {\n"
        "        output discard\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    result = check_workerbee_caddy_routes(tmp_path)

    assert result.ok
    assert result.findings == []


def test_check_workerbee_caddy_cli_returns_nonzero_on_failure(tmp_path: Path, capsys) -> None:
    route = tmp_path / "projects" / "baseline-004-clean-wb" / "caddy" / "old.caddy"
    route.parent.mkdir(parents=True)
    route.write_text("https://app.demo.workerbee.localhost {\n}\n", encoding="utf-8")

    status = main(
        [
            "check-workerbee-caddy",
            "--state-root",
            str(tmp_path),
            "--project",
            "baseline-004-clean-wb",
        ]
    )

    assert status == 1
    assert "pre-existing Caddy routes" in capsys.readouterr().out
