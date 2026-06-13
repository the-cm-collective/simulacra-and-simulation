from __future__ import annotations

from simulacra import k1s_preflight
from simulacra.k1s_preflight import assess_k1s_ingress_env


def test_k1s_ingress_preflight_fails_core_proxy_without_open_ports() -> None:
    result = assess_k1s_ingress_env(
        {
            "AE_TRANSPORT_BACKEND": "nats-js",
            "AE_EDGE_INGRESS_TRANSLATE_APP_INGRESS": "1",
        },
        core_proxy_ports_open=[],
    )

    assert not result.ok
    assert "core-proxy" in result.findings[0].message


def test_k1s_ingress_preflight_accepts_core_proxy_with_open_ports() -> None:
    result = assess_k1s_ingress_env(
        {
            "AE_TRANSPORT_BACKEND": "nats-js",
            "AE_EDGE_INGRESS_TRANSLATE_APP_INGRESS": "1",
        },
        core_proxy_ports_open=[18081],
    )

    assert result.ok
    assert result.findings == []


def test_k1s_ingress_preflight_warns_for_core_local_remote_transport() -> None:
    result = assess_k1s_ingress_env(
        {
            "AE_TRANSPORT_BACKEND": "nats-js",
            "AE_EDGE_INGRESS_TRANSLATE_APP_INGRESS": "1",
            "AE_EDGE_INGRESS_TRANSLATE_MODE": "core-local",
        },
        core_proxy_ports_open=[],
    )

    assert result.ok
    assert result.findings[0].severity == "warning"
    assert "post-deploy app-host probe" in result.findings[0].message


class _FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._body


def test_probe_url_requires_expected_body_text() -> None:
    ok, detail = k1s_preflight._probe_url(
        "https://padawan.example.test/peer",
        timeout=1.0,
        body_contains=None,
    )

    assert not ok
    assert "--probe-body-contains is required" in detail


def test_probe_url_rejects_http_200_without_expected_body(monkeypatch) -> None:
    monkeypatch.setattr(
        k1s_preflight.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(200, ""),
    )

    ok, detail = k1s_preflight._probe_url(
        "https://padawan.example.test/peer",
        timeout=1.0,
        body_contains="Padawan",
    )

    assert not ok
    assert "missing body text 'Padawan'" in detail


def test_probe_url_accepts_http_200_with_expected_body(monkeypatch) -> None:
    monkeypatch.setattr(
        k1s_preflight.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(200, "<title>Padawan</title>"),
    )

    ok, detail = k1s_preflight._probe_url(
        "https://padawan.example.test/peer",
        timeout=1.0,
        body_contains="Padawan",
    )

    assert ok
    assert "body contains 'Padawan'" in detail
