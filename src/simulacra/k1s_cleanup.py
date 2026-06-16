from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .k1s_runtime_preflight import check_k1s_runtime_clean

DEFAULT_AE_SERVER = "http://127.0.0.1:49108"
DEFAULT_WORKERBEE_STATE_ROOT = "/tmp/workerbee-containerd-verify"  # noqa: S108


@dataclass(frozen=True)
class AeWorkload:
    namespace: str
    name: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class RuntimeContainer:
    container_id: str
    name: str
    image: str
    status: str
    ports: str
    labels: str
    raw: str


@dataclass(frozen=True)
class WorkerBeeNamespace:
    namespace: str
    project: str
    data_root: str


def cleanup_k1s_dev_a(
    *,
    run_id: str | None,
    execute: bool,
    ae_server: str = DEFAULT_AE_SERVER,
    ae_token_env: str | None = None,
    kubectl_namespace: str = "k1s-dev-a",
    auth_secret: str = "k1s-dev-a-k1s-core-ha-auth",  # noqa: S107
    ae_bin: str = "ae",
    kubectl_bin: str = "kubectl",
    nerdctl_bin: str = "/var/lib/ae/nerdctl-bin/nerdctl",
    containerd_socket: str = "unix:///var/snap/microk8s/common/run/containerd.sock",
    containerd_namespace: str = "ae",
    data_root: str = "/var/lib/ae/nerdctl",
    use_sudo: bool = True,
    reserved_ports: list[int] | None = None,
    include_workerbee_profiles: bool = False,
    workerbee_state_root: str | Path = DEFAULT_WORKERBEE_STATE_ROOT,
    workerbee_bin: str = "workerbee",
    workerbee_nerdctl_bin: str = "/usr/local/bin/nerdctl",
    timeout: float = 15.0,
) -> dict[str, Any]:
    token = _resolve_ae_token(
        ae_token_env=ae_token_env,
        kubectl_namespace=kubectl_namespace,
        auth_secret=auth_secret,
        kubectl_bin=kubectl_bin,
        timeout=timeout,
    )
    before_workloads = _list_ae_workloads(
        ae_server=ae_server,
        token=token,
        ae_bin=ae_bin,
        timeout=timeout,
    )
    selected_workloads = select_ae_workloads(before_workloads, run_id=run_id)
    workload_actions = [
        _delete_ae_workload(
            workload,
            execute=execute,
            ae_server=ae_server,
            token=token,
            ae_bin=ae_bin,
            timeout=timeout,
        )
        for workload in selected_workloads
    ]

    before_containers = _list_microk8s_runtime_containers(
        nerdctl_bin=nerdctl_bin,
        containerd_socket=containerd_socket,
        namespace=containerd_namespace,
        data_root=data_root,
        use_sudo=use_sudo,
        timeout=timeout,
    )
    selected_containers = select_runtime_containers(before_containers, run_id=run_id)
    runtime_actions = _remove_microk8s_containers(
        selected_containers,
        execute=execute,
        nerdctl_bin=nerdctl_bin,
        containerd_socket=containerd_socket,
        namespace=containerd_namespace,
        data_root=data_root,
        use_sudo=use_sudo,
        timeout=timeout,
    )

    workerbee_actions: list[dict[str, Any]] = []
    workerbee_namespaces: list[WorkerBeeNamespace] = []
    if include_workerbee_profiles:
        workerbee_namespaces = _discover_workerbee_namespaces(
            state_root=Path(workerbee_state_root),
            timeout=timeout,
        )
        for namespace in workerbee_namespaces:
            workerbee_actions.extend(
                _cleanup_workerbee_namespace(
                    namespace,
                    execute=execute,
                    workerbee_bin=workerbee_bin,
                    nerdctl_bin=workerbee_nerdctl_bin,
                    state_root=Path(workerbee_state_root),
                    timeout=timeout,
                )
            )

    after_workloads = _list_ae_workloads(
        ae_server=ae_server,
        token=token,
        ae_bin=ae_bin,
        timeout=timeout,
    )
    after_containers = _list_microk8s_runtime_containers(
        nerdctl_bin=nerdctl_bin,
        containerd_socket=containerd_socket,
        namespace=containerd_namespace,
        data_root=data_root,
        use_sudo=use_sudo,
        timeout=timeout,
    )
    runtime_check = None
    if reserved_ports is not None:
        result = check_k1s_runtime_clean(
            reserved_ports=reserved_ports,
            nerdctl_bin=nerdctl_bin,
            containerd_socket=containerd_socket,
            namespace=containerd_namespace,
            data_root=data_root,
            use_sudo=use_sudo,
            timeout=timeout,
        )
        runtime_check = {
            "ok": result.ok,
            "reserved_ports": result.reserved_ports,
            "container_count": len(result.containers),
            "host_listener_count": len(result.listeners),
            "findings": [asdict(finding) for finding in result.findings],
        }

    remaining_workloads = select_ae_workloads(after_workloads, run_id=run_id)
    remaining_containers = select_runtime_containers(after_containers, run_id=run_id)
    findings: list[dict[str, str]] = []
    if remaining_workloads:
        severity = "error" if execute else "warning"
        findings.append(
            {
                "severity": severity,
                "message": f"{len(remaining_workloads)} simulation k1s app record(s) remain",
            }
        )
    if remaining_containers:
        severity = "error" if execute else "warning"
        findings.append(
            {
                "severity": severity,
                "message": f"{len(remaining_containers)} simulation runtime container(s) remain",
            }
        )
    if runtime_check and not runtime_check["ok"]:
        for finding in runtime_check["findings"]:
            if execute:
                findings.append(finding)
            else:
                findings.append({**finding, "severity": "warning"})

    return {
        "ok": not any(finding["severity"] == "error" for finding in findings),
        "execute": execute,
        "run_id": run_id,
        "ae_server": ae_server,
        "kubectl_namespace": kubectl_namespace,
        "auth_secret": auth_secret,
        "before": {
            "ae_workload_count": len(before_workloads),
            "microk8s_container_count": len(before_containers),
            "workerbee_namespace_count": len(workerbee_namespaces),
        },
        "selected": {
            "ae_workloads": [asdict(workload) for workload in selected_workloads],
            "microk8s_containers": [asdict(container) for container in selected_containers],
            "workerbee_namespaces": [asdict(namespace) for namespace in workerbee_namespaces],
        },
        "actions": [*workload_actions, *runtime_actions, *workerbee_actions],
        "after": {
            "ae_workload_count": len(after_workloads),
            "microk8s_container_count": len(after_containers),
            "remaining_ae_workloads": [asdict(workload) for workload in remaining_workloads],
            "remaining_microk8s_containers": [
                asdict(container) for container in remaining_containers
            ],
            "runtime_check": runtime_check,
        },
        "findings": findings,
    }


def select_ae_workloads(
    workloads: list[AeWorkload],
    *,
    run_id: str | None = None,
) -> list[AeWorkload]:
    return [workload for workload in workloads if _is_sim_ae_workload(workload, run_id=run_id)]


def select_runtime_containers(
    containers: list[RuntimeContainer],
    *,
    run_id: str | None = None,
) -> list[RuntimeContainer]:
    return [container for container in containers if _is_sim_runtime_container(container, run_id)]


def parse_ae_status(data: object) -> list[AeWorkload]:
    if isinstance(data, dict):
        raw_items = data.get("workloads") if isinstance(data.get("workloads"), list) else []
    elif isinstance(data, list):
        raw_items = data
    else:
        raw_items = []
    workloads: list[AeWorkload] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        namespace = str(item.get("namespace") or item.get("ns") or "default")
        name = str(item.get("name") or item.get("app") or item.get("app_name") or "")
        if not name and isinstance(item.get("metadata"), dict):
            metadata = item["metadata"]
            namespace = str(metadata.get("namespace") or namespace)
            name = str(metadata.get("name") or "")
        if name:
            workloads.append(AeWorkload(namespace=namespace, name=name, raw=item))
    return workloads


def parse_runtime_container_line(line: str) -> RuntimeContainer:
    parts = line.rstrip("\n").split("\t", 5)
    while len(parts) < 6:
        parts.append("")
    return RuntimeContainer(
        container_id=parts[0].strip(),
        name=parts[1].strip(),
        image=parts[2].strip(),
        status=parts[3].strip(),
        ports=parts[4].strip(),
        labels=parts[5].strip(),
        raw=line.rstrip("\n"),
    )


def _resolve_ae_token(
    *,
    ae_token_env: str | None,
    kubectl_namespace: str,
    auth_secret: str,
    kubectl_bin: str,
    timeout: float,
) -> str:
    if ae_token_env:
        token = os.environ.get(ae_token_env)
        if token:
            return token
        raise RuntimeError(f"AE token environment variable is not set: {ae_token_env}")
    proc = subprocess.run(
        [
            kubectl_bin,
            "-n",
            kubectl_namespace,
            "get",
            "secret",
            auth_secret,
            "-o",
            "jsonpath={.data.apishim-admin-token}",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"failed to read k1s admin token secret: {detail or proc.returncode}")
    raw = proc.stdout.strip()
    if not raw:
        raise RuntimeError("k1s admin token secret is empty")
    return base64.b64decode(raw).decode("utf-8")


def _list_ae_workloads(
    *,
    ae_server: str,
    token: str,
    ae_bin: str,
    timeout: float,
) -> list[AeWorkload]:
    proc = subprocess.run(
        [ae_bin, "--server", ae_server, "--token", token, "status", "--json"],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"failed to query ae status: {detail or proc.returncode}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse ae status JSON: {exc}") from exc
    return parse_ae_status(data)


def _delete_ae_workload(
    workload: AeWorkload,
    *,
    execute: bool,
    ae_server: str,
    token: str,
    ae_bin: str,
    timeout: float,
) -> dict[str, Any]:
    command = [
        ae_bin,
        "--server",
        ae_server,
        "--token",
        token,
        "-n",
        workload.namespace,
        "delete",
        workload.name,
        "--purge",
    ]
    action: dict[str, Any] = {
        "kind": "ae_workload",
        "target": f"{workload.namespace}/{workload.name}",
        "action": "delete --purge",
        "execute": execute,
        "command": _redacted_command(command),
    }
    if execute:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        action.update(
            {
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }
        )
    return action


def _list_microk8s_runtime_containers(
    *,
    nerdctl_bin: str,
    containerd_socket: str,
    namespace: str,
    data_root: str,
    use_sudo: bool,
    timeout: float,
) -> list[RuntimeContainer]:
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
        "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Labels}}",
    ]
    if use_sudo:
        command = ["sudo", "-n", *command]
    proc = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"failed to list MicroK8s ae containers: {detail or proc.returncode}")
    return [parse_runtime_container_line(line) for line in proc.stdout.splitlines() if line.strip()]


def _remove_microk8s_containers(
    containers: list[RuntimeContainer],
    *,
    execute: bool,
    nerdctl_bin: str,
    containerd_socket: str,
    namespace: str,
    data_root: str,
    use_sudo: bool,
    timeout: float,
) -> list[dict[str, Any]]:
    if not containers:
        return []
    ids = [container.container_id for container in containers]
    command = [
        nerdctl_bin,
        "--address",
        containerd_socket,
        "--namespace",
        namespace,
        "--data-root",
        data_root,
        "rm",
        "-f",
        *ids,
    ]
    if use_sudo:
        command = ["sudo", "-n", *command]
    action: dict[str, Any] = {
        "kind": "microk8s_container",
        "target": ids,
        "action": "rm -f",
        "execute": execute,
        "command": command,
    }
    if execute:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        action.update(
            {
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }
        )
    return [action]


def _discover_workerbee_namespaces(
    *,
    state_root: Path,
    timeout: float,
) -> list[WorkerBeeNamespace]:
    projects_dir = state_root.expanduser().resolve() / "projects"
    if not projects_dir.is_dir():
        return []
    projects = {
        path.name: path
        for path in projects_dir.iterdir()
        if path.is_dir() and _is_sim_workerbee_project(path.name)
    }
    if not projects:
        return []
    proc = subprocess.run(
        ["sudo", "-n", "ctr", "namespaces", "list", "-q"],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        return []
    namespaces: list[WorkerBeeNamespace] = []
    for namespace in (line.strip() for line in proc.stdout.splitlines()):
        if not namespace.startswith("workerbee-"):
            continue
        project = next((name for name in projects if namespace.endswith(f"-{name}")), "")
        if not project:
            continue
        data_root = _workerbee_data_root(projects[project])
        if data_root:
            namespaces.append(
                WorkerBeeNamespace(namespace=namespace, project=project, data_root=str(data_root))
            )
    return namespaces


def _cleanup_workerbee_namespace(
    namespace: WorkerBeeNamespace,
    *,
    execute: bool,
    workerbee_bin: str,
    nerdctl_bin: str,
    state_root: Path,
    timeout: float,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    stop_command = [
        workerbee_bin,
        "--runtime",
        "containerd",
        "--containerd-privilege",
        "sudo-helper",
        "--state-root",
        str(state_root),
        "--project",
        namespace.project,
        "profile",
        "stop",
        "--purge",
    ]
    stop_action: dict[str, Any] = {
        "kind": "workerbee_profile",
        "target": namespace.project,
        "action": "profile stop --purge",
        "execute": execute,
        "command": stop_command,
    }
    if execute:
        proc = subprocess.run(
            stop_command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        stop_action.update(
            {
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }
        )
    actions.append(stop_action)

    ids = _workerbee_namespace_container_ids(
        namespace,
        nerdctl_bin=nerdctl_bin,
        timeout=timeout,
    )
    if ids:
        command = [
            "sudo",
            "-n",
            nerdctl_bin,
            "--namespace",
            namespace.namespace,
            "--data-root",
            namespace.data_root,
            "rm",
            "-f",
            *ids,
        ]
        action: dict[str, Any] = {
            "kind": "workerbee_profile_container",
            "target": ids,
            "action": "rm -f",
            "execute": execute,
            "command": command,
        }
        if execute:
            proc = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
            action.update(
                {
                    "returncode": proc.returncode,
                    "stdout": proc.stdout.strip(),
                    "stderr": proc.stderr.strip(),
                }
            )
        actions.append(action)
    return actions


def _workerbee_namespace_container_ids(
    namespace: WorkerBeeNamespace,
    *,
    nerdctl_bin: str,
    timeout: float,
) -> list[str]:
    proc = subprocess.run(
        [
            "sudo",
            "-n",
            nerdctl_bin,
            "--namespace",
            namespace.namespace,
            "--data-root",
            namespace.data_root,
            "ps",
            "-aq",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _workerbee_data_root(project_dir: Path) -> Path | None:
    root = project_dir / "containerd-data"
    if not root.is_dir():
        return None
    candidates = [
        path for path in root.iterdir() if path.is_dir() and path.name != "filesystem-ops"
    ]
    if not candidates:
        return root
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def _is_sim_ae_workload(workload: AeWorkload, *, run_id: str | None) -> bool:
    namespace = workload.namespace
    name = workload.name
    text = f"{namespace}/{name}".lower()
    if run_id and run_id.lower() in text:
        return True
    if namespace.startswith("sim-baseline-"):
        return name in {"padawan", "coturn"} or name.startswith(("padawan", "coturn"))
    if namespace == "sim-preflight" and name == "coreproxy-smoke":
        return True
    return bool(namespace == "default" and re.fullmatch(r"(?:padawan|coturn)-\d{3,}", name))


def _is_sim_runtime_container(container: RuntimeContainer, run_id: str | None) -> bool:
    text = " ".join(
        [container.name, container.image, container.status, container.ports, container.labels]
    ).lower()
    if run_id and run_id.lower() in text:
        return True
    if "ae.namespace=sim-baseline-" in text or container.name.startswith("ae-sim-baseline-"):
        return True
    if "ae.namespace=sim-preflight" in text or container.name.startswith("ae-sim-preflight-"):
        return True
    if "workerbee.project=baseline-" in text and (
        "ae.app=padawan" in text
        or "ae.app=coturn" in text
        or container.name.startswith(("ae-padawan-", "ae-coturn-"))
    ):
        return True
    return "simulacra/padawan:baseline-" in text


def _is_sim_workerbee_project(project: str) -> bool:
    return project.startswith("baseline-") and project.endswith("-wb")


def _redacted_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for item in command:
        if skip_next:
            redacted.append("***")
            skip_next = False
            continue
        redacted.append(item)
        if item == "--token":
            skip_next = True
    return redacted
