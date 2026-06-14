from __future__ import annotations

from pathlib import Path

from simulacra import cli
from simulacra.k1s_runtime_preflight import (
    K1sRuntimePreflight,
    assess_k1s_runtime_clean,
    scenario_reserved_ports,
)
from simulacra.scenario import load_scenario


def test_assess_k1s_runtime_clean_rejects_prior_sim_container() -> None:
    result = assess_k1s_runtime_clean(
        [
            "abc123\tae-sim-baseline-020-plain-padawan-rev1-0-aaa\t"
            "0.0.0.0:18787->8787/tcp\tae.namespace=sim-baseline-020-plain"
        ],
        reserved_ports=[18787],
    )

    assert not result.ok
    messages = [finding.message for finding in result.findings]
    assert any("stale simulation container" in message for message in messages)
    assert any("reserved simulation port(s) 18787 occupied" in message for message in messages)


def test_assess_k1s_runtime_clean_allows_current_run_when_requested() -> None:
    result = assess_k1s_runtime_clean(
        [
            "abc123\tae-sim-baseline-022-plain-padawan-rev1-0-aaa\t"
            "0.0.0.0:19787->8787/tcp\tae.namespace=sim-baseline-022-plain"
        ],
        reserved_ports=[18787],
        allow_run_id="baseline-022",
    )

    assert result.ok
    assert result.findings == []


def test_scenario_reserved_ports_includes_all_default_lane_ports(tmp_path: Path) -> None:
    scenario = load_scenario(tmp_path)

    ports = scenario_reserved_ports(scenario)

    assert 8787 in ports
    assert 3478 in ports
    assert 18787 in ports
    assert 13478 in ports
    assert 18878 in ports
    assert 13479 in ports
    assert 28787 in ports
    assert 23478 in ports


def test_cli_check_k1s_runtime_clean_uses_scenario_ports(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    scenario_file = tmp_path / "custom.yaml"
    scenario_file.write_text(
        """
preflight:
  local_ports: [8000]
k1s_ingress:
  remote_service_ports:
    plain-codex:
      padawan: 18000
workerbee_stage:
  local_profile_service_ports:
    coturn: 19000
""".lstrip(),
        encoding="utf-8",
    )

    seen_ports: list[int] = []

    def fake_check(**kwargs):
        seen_ports.extend(kwargs["reserved_ports"])
        return K1sRuntimePreflight(
            ok=True,
            findings=[],
            reserved_ports=sorted(kwargs["reserved_ports"]),
            containers=[],
        )

    monkeypatch.setattr(cli, "check_k1s_runtime_clean", fake_check)

    status = cli.main(
        [
            "--repo-root",
            str(tmp_path),
            "--scenario",
            str(scenario_file),
            "check-k1s-runtime-clean",
            "--port",
            "20000",
            "--no-sudo",
        ]
    )

    assert status == 0
    assert 8000 in seen_ports
    assert 18000 in seen_ports
    assert 19000 in seen_ports
    assert 20000 in seen_ports
    out = capsys.readouterr().out
    assert '"reserved_ports": [' in out
