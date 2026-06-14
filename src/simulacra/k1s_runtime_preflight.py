from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Any

from .scenario import Scenario


@dataclass(frozen=True)
class K1sRuntimeContainer:
    container_id: str
    name: str
    ports: str
    labels: str
    raw: str


@dataclass(frozen=True)
class K1sRuntimeFinding:
    severity: str
    message: str


@dataclass(frozen=True)
class K1sRuntimePreflight:
    ok: bool
    findings: list[K1sRuntimeFinding]
    reserved_ports: list[int]
    containers: list[K1sRuntimeContainer]


def scenario_reserved_ports(scenario: Scenario) -> list[int]:
    ports: list[int] = []
    ports.extend(_int_list(scenario.preflight.get("local_ports")))
    ports.extend(_nested_port_values(scenario.k1s_ingress.get("remote_service_ports")))
    ports.extend(_nested_port_values(scenario.workerbee_stage.get("local_profile_service_ports")))
    return sorted(set(ports))


def check_k1s_runtime_clean(
    *,
    reserved_ports: list[int],
    allow_run_id: str | None = None,
    nerdctl_bin: str = "/var/lib/ae/nerdctl-bin/nerdctl",
    containerd_socket: str = "unix:///var/snap/microk8s/common/run/containerd.sock",
    namespace: str = "ae",
    data_root: str = "/var/lib/ae/nerdctl",
    use_sudo: bool = True,
    timeout: float = 10.0,
) -> K1sRuntimePreflight:
    command = [
        nerdctl_bin,
        "--address",
        containerd_socket,
        "--namespace",
        namespace,
        "--data-root",
        data_root,
        "ps",
        "-a",
        "--format",
        "{{.ID}}\t{{.Names}}\t{{.Ports}}\t{{.Labels}}",
    ]
    if use_sudo:
        command = ["sudo", "-n", *command]
    try:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except Exception as exc:
        return K1sRuntimePreflight(
            ok=False,
            findings=[
                K1sRuntimeFinding(
                    severity="error",
                    message=f"failed to inspect MicroK8s ae runtime: {type(exc).__name__}: {exc}",
                )
            ],
            reserved_ports=sorted(set(reserved_ports)),
            containers=[],
        )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return K1sRuntimePreflight(
            ok=False,
            findings=[
                K1sRuntimeFinding(
                    severity="error",
                    message=f"failed to inspect MicroK8s ae runtime: {detail or proc.returncode}",
                )
            ],
            reserved_ports=sorted(set(reserved_ports)),
            containers=[],
        )
    return assess_k1s_runtime_clean(
        proc.stdout.splitlines(),
        reserved_ports=reserved_ports,
        allow_run_id=allow_run_id,
    )


def assess_k1s_runtime_clean(
    lines: list[str],
    *,
    reserved_ports: list[int],
    allow_run_id: str | None = None,
) -> K1sRuntimePreflight:
    containers = [_parse_container(line) for line in lines if line.strip()]
    ports = sorted(set(int(port) for port in reserved_ports))
    allowed_marker = f"sim-{allow_run_id}" if allow_run_id else None
    findings: list[K1sRuntimeFinding] = []

    for container in containers:
        if _is_prior_sim_container(container, allowed_marker=allowed_marker):
            findings.append(
                K1sRuntimeFinding(
                    severity="error",
                    message=(
                        "stale simulation container remains in MicroK8s ae runtime: "
                        f"{container.name} ({container.container_id}) ports={container.ports or '<none>'}"
                    ),
                )
            )
        bound_reserved = sorted(_bound_host_ports(container.ports).intersection(ports))
        if bound_reserved:
            port_text = ", ".join(str(port) for port in bound_reserved)
            findings.append(
                K1sRuntimeFinding(
                    severity="error",
                    message=(
                        f"reserved simulation port(s) {port_text} occupied by "
                        f"{container.name} ({container.container_id})"
                    ),
                )
            )

    return K1sRuntimePreflight(
        ok=not any(finding.severity == "error" for finding in findings),
        findings=findings,
        reserved_ports=ports,
        containers=containers,
    )


def _parse_container(line: str) -> K1sRuntimeContainer:
    parts = line.rstrip("\n").split("\t", 3)
    while len(parts) < 4:
        parts.append("")
    return K1sRuntimeContainer(
        container_id=parts[0].strip(),
        name=parts[1].strip(),
        ports=parts[2].strip(),
        labels=parts[3].strip(),
        raw=line.rstrip("\n"),
    )


def _is_prior_sim_container(
    container: K1sRuntimeContainer,
    *,
    allowed_marker: str | None,
) -> bool:
    text = f"{container.name} {container.labels}"
    if allowed_marker and allowed_marker in text:
        return False
    return "ae.namespace=sim-baseline-" in text or container.name.startswith(
        "ae-sim-baseline-"
    )


def _bound_host_ports(ports: str) -> set[int]:
    values: set[int] = set()
    for match in re.finditer(r"(?::|^)(\d+)->\d+/(?:tcp|udp)", ports):
        values.add(int(match.group(1)))
    return values


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [int(item) for item in value if _is_intish(item)]


def _nested_port_values(value: Any) -> list[int]:
    if isinstance(value, dict):
        ports: list[int] = []
        for item in value.values():
            ports.extend(_nested_port_values(item))
        return ports
    if _is_intish(value):
        return [int(value)]
    return []


def _is_intish(value: Any) -> bool:
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True
