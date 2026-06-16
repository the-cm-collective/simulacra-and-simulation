from __future__ import annotations

from pathlib import Path

from simulacra import cli
from simulacra.k1s_cleanup import (
    AeWorkload,
    RuntimeContainer,
    WorkerBeeNamespace,
    _cleanup_workerbee_namespace,
    select_ae_workloads,
    select_runtime_containers,
)
from simulacra.k1s_runtime_preflight import (
    K1sRuntimeListener,
    K1sRuntimePreflight,
    assess_k1s_runtime_clean,
    check_k1s_runtime_clean,
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


def test_select_ae_workloads_covers_simulation_records() -> None:
    workloads = [
        AeWorkload(namespace="sim-baseline-032-plain", name="padawan", raw={}),
        AeWorkload(namespace="default", name="coturn-024", raw={}),
        AeWorkload(namespace="sim-preflight", name="coreproxy-smoke", raw={}),
        AeWorkload(namespace="default", name="live-standard", raw={}),
    ]

    selected = select_ae_workloads(workloads)

    assert [f"{item.namespace}/{item.name}" for item in selected] == [
        "sim-baseline-032-plain/padawan",
        "default/coturn-024",
        "sim-preflight/coreproxy-smoke",
    ]


def test_select_runtime_containers_covers_workerbee_baseline_orphans() -> None:
    containers = [
        RuntimeContainer(
            container_id="abc",
            name="ae-coturn-024-rev1-0",
            image="docker.io/coturn/coturn:4.12.0",
            status="Up",
            ports="0.0.0.0:24478->3478/tcp",
            labels="workerbee.project=baseline-024-wb-mcp-fresh-wb,ae.app=coturn-024",
            raw="",
        ),
        RuntimeContainer(
            container_id="def",
            name="ae-sim-baseline-032-plain-padawan-rev1-0",
            image="reg/simulacra/padawan:baseline-032-plain",
            status="Up",
            ports="0.0.0.0:18787->8787/tcp",
            labels="ae.namespace=sim-baseline-032-plain",
            raw="",
        ),
        RuntimeContainer(
            container_id="ghi",
            name="ae-live-standard-rev1-0",
            image="reg/live-standard:latest",
            status="Up",
            ports="",
            labels="ae.namespace=default,ae.app=live-standard",
            raw="",
        ),
    ]

    selected = select_runtime_containers(containers)

    assert [item.container_id for item in selected] == ["abc", "def"]


def test_workerbee_namespace_cleanup_uses_single_state_root_flag(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    class FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        return FakeProc()

    monkeypatch.setattr("simulacra.k1s_cleanup.subprocess.run", fake_run)

    actions = _cleanup_workerbee_namespace(
        WorkerBeeNamespace(
            namespace="workerbee-abc-baseline-032-api-clean-wb",
            project="baseline-032-api-clean-wb",
            data_root=str(tmp_path / "containerd-data"),
        ),
        execute=False,
        workerbee_bin="workerbee",
        nerdctl_bin="nerdctl",
        state_root=tmp_path,
        timeout=1,
    )

    assert actions[0]["command"].count("--state-root") == 1
    assert actions[0]["command"] == [
        "workerbee",
        "--runtime",
        "containerd",
        "--containerd-privilege",
        "sudo-helper",
        "--state-root",
        str(tmp_path),
        "--project",
        "baseline-032-api-clean-wb",
        "profile",
        "stop",
        "--purge",
    ]


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


def test_assess_k1s_runtime_clean_rejects_reserved_host_listener() -> None:
    result = assess_k1s_runtime_clean(
        [],
        reserved_ports=[13479],
        listeners=[
            K1sRuntimeListener(
                protocol="tcp",
                local_address="0.0.0.0:13479",
                port=13479,
                raw="tcp LISTEN 0 4096 0.0.0.0:13479 0.0.0.0:*",
            )
        ],
    )

    assert not result.ok
    assert result.listeners[0].port == 13479
    assert "host listener 0.0.0.0:13479" in result.findings[0].message


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


def test_check_k1s_runtime_clean_inspects_host_listeners(monkeypatch) -> None:
    calls: list[list[str]] = []

    class FakeProc:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        if command[:3] == ["ss", "-H", "-ltnu"]:
            return FakeProc(
                0,
                "tcp LISTEN 0 4096 0.0.0.0:13479 0.0.0.0:*\n",
            )
        return FakeProc(0, "")

    monkeypatch.setattr("simulacra.k1s_runtime_preflight.subprocess.run", fake_run)

    result = check_k1s_runtime_clean(
        reserved_ports=[13479],
        nerdctl_bin="nerdctl",
        containerd_socket="unix:///tmp/containerd.sock",  # noqa: S108
        data_root="/tmp/nerdctl",  # noqa: S108
        use_sudo=False,
    )

    assert not result.ok
    assert any(call[:3] == ["ss", "-H", "-ltnu"] for call in calls)
    assert result.listeners[0].port == 13479
    assert "reserved simulation port 13479" in result.findings[0].message
