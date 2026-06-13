from __future__ import annotations

import json
import ssl
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class K1sFinding:
    severity: str
    message: str


@dataclass(frozen=True)
class K1sIngressPreflight:
    ok: bool
    findings: list[K1sFinding]
    controller_env: dict[str, str]
    core_proxy_ports_open: list[int]


def assess_k1s_ingress_env(
    controller_env: dict[str, str],
    *,
    core_proxy_ports_open: list[int] | None = None,
    require_translated_ingress: bool = True,
) -> K1sIngressPreflight:
    findings: list[K1sFinding] = []
    open_ports = sorted(core_proxy_ports_open or [])

    translated = _truthy(controller_env.get("AE_EDGE_INGRESS_TRANSLATE_APP_INGRESS"))
    if require_translated_ingress and not translated:
        findings.append(
            K1sFinding(
                severity="error",
                message="translated app ingress is disabled",
            )
        )

    backend = (controller_env.get("AE_TRANSPORT_BACKEND") or "http").strip().lower()
    explicit_mode = _normalize_mode(controller_env.get("AE_EDGE_INGRESS_TRANSLATE_MODE"))
    edge_mode = _normalize_mode(controller_env.get("AE_EDGE_INGRESS_MODE"))
    effective_mode = (
        explicit_mode or edge_mode or ("core-local" if backend == "http" else "core-proxy")
    )

    if effective_mode == "core-proxy" and not open_ports:
        findings.append(
            K1sFinding(
                severity="error",
                message=(
                    "translated app ingress resolves to core-proxy, but no controller "
                    "core-proxy site ports are reachable"
                ),
            )
        )
    if effective_mode == "core-local" and backend != "http":
        findings.append(
            K1sFinding(
                severity="warning",
                message=(
                    "translated app ingress resolves to core-local on a remote/HA transport; "
                    "post-deploy app-host probe is required because service endpoint rows "
                    "must exist"
                ),
            )
        )

    return K1sIngressPreflight(
        ok=not any(finding.severity == "error" for finding in findings),
        findings=findings,
        controller_env=controller_env,
        core_proxy_ports_open=open_ports,
    )


def check_k1s_dev_a_ingress(
    *,
    namespace: str = "k1s-dev-a",
    controller_deployment: str = "k1s-dev-a-k1s-core-ha-controller",
    probe_url: str | None = None,
    probe_body_contains: str | None = None,
    timeout: float = 5.0,
) -> K1sIngressPreflight:
    env = _controller_env(namespace, controller_deployment)
    ports = _open_core_proxy_ports(namespace, controller_deployment, timeout=timeout)
    result = assess_k1s_ingress_env(env, core_proxy_ports_open=ports)
    findings = list(result.findings)

    if probe_url:
        ok, detail = _probe_url(
            probe_url,
            timeout=timeout,
            body_contains=probe_body_contains,
        )
        if not ok:
            findings.append(K1sFinding(severity="error", message=detail))

    return K1sIngressPreflight(
        ok=not any(finding.severity == "error" for finding in findings),
        findings=findings,
        controller_env=env,
        core_proxy_ports_open=ports,
    )


def _controller_env(namespace: str, deployment: str) -> dict[str, str]:
    proc = subprocess.run(
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "deployment",
            deployment,
            "-o",
            "json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    doc = json.loads(proc.stdout)
    containers = doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    for container in containers:
        if container.get("name") != "controller":
            continue
        env: dict[str, str] = {}
        for item in container.get("env", []) or []:
            name = str(item.get("name") or "")
            if not name:
                continue
            if "value" in item:
                env[name] = str(item.get("value") or "")
            elif "valueFrom" in item:
                env[name] = "<valueFrom>"
        return env
    return {}


def _open_core_proxy_ports(namespace: str, deployment: str, *, timeout: float) -> list[int]:
    pod = _first_ready_controller_pod(namespace, deployment)
    if not pod:
        return []
    script = (
        "import socket\n"
        "ports=range(18080,18090)\n"
        "open_ports=[]\n"
        "for p in ports:\n"
        "    s=socket.socket(); s.settimeout(0.25)\n"
        "    try:\n"
        "        s.connect(('127.0.0.1', p)); open_ports.append(p)\n"
        "    except Exception:\n"
        "        pass\n"
        "    finally:\n"
        "        s.close()\n"
        "print(','.join(str(p) for p in open_ports))\n"
    )
    proc = subprocess.run(
        [
            "kubectl",
            "-n",
            namespace,
            "exec",
            pod,
            "-c",
            "controller",
            "--",
            "python3",
            "-c",
            script,
        ],
        text=True,
        capture_output=True,
        timeout=timeout + 2,
        check=False,
    )
    if proc.returncode != 0:
        return []
    ports: list[int] = []
    for item in proc.stdout.strip().split(","):
        if item.strip().isdigit():
            ports.append(int(item.strip()))
    return ports


def _first_ready_controller_pod(namespace: str, deployment: str) -> str | None:
    prefix = f"{deployment}-"
    proc = subprocess.run(
        ["kubectl", "-n", namespace, "get", "pods", "-o", "json"],
        check=True,
        text=True,
        capture_output=True,
    )
    doc = json.loads(proc.stdout)
    for pod in doc.get("items", []) or []:
        name = str(pod.get("metadata", {}).get("name") or "")
        if not name.startswith(prefix):
            continue
        phase = str(pod.get("status", {}).get("phase") or "")
        if phase != "Running":
            continue
        statuses = pod.get("status", {}).get("containerStatuses", []) or []
        if statuses and all(bool(item.get("ready")) for item in statuses):
            return name
    return None


def _probe_url(url: str, *, timeout: float, body_contains: str | None) -> tuple[bool, str]:
    scheme = urlparse(url).scheme.lower()
    if scheme not in {"http", "https"}:
        return False, f"probe failed: unsupported URL scheme {scheme or '<none>'}"
    expected = (body_contains or "").strip()
    if not expected:
        return False, "probe failed: --probe-body-contains is required with --probe-url"
    # k1s-dev-a app hosts use a local lab CA; preflight is reachability, not PKI validation.
    ctx = ssl._create_unverified_context()  # noqa: S323
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=ctx) as resp:  # noqa: S310
            status = int(getattr(resp, "status", 0) or 0)
            body = resp.read(1_000_000).decode("utf-8", errors="replace")
        if not 200 <= status < 400:
            return False, f"probe failed: {url} status={status}"
        if expected not in body:
            return (
                False,
                f"probe failed: {url} status={status} missing body text {expected!r}",
            )
        return True, f"probe ok: {url} status={status} body contains {expected!r}"
    except urllib.error.HTTPError as exc:
        return False, f"probe failed: {url} status={exc.code}"
    except Exception as exc:
        return False, f"probe failed: {url} error={type(exc).__name__}: {exc}"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_mode(value: str | None) -> str | None:
    raw = str(value or "").strip().lower().replace("_", "-")
    if raw in {"core", "core-local"}:
        return "core-local"
    if raw in {"core-proxy", "core-to-edge-public", "edge-local"}:
        return raw
    return None
