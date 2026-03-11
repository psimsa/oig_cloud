from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shared import logging as logging_module


class DummyResponse:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummySession:
    def __init__(self, response):
        self._response = response
        self.closed = False

    async def close(self):
        self.closed = True

    def post(self, *_args, **_kwargs):
        return self._response


@pytest.mark.asyncio
async def test_send_event_success(monkeypatch):
    telemetry = logging_module.SimpleTelemetry("http://example.test", {})
    response = DummyResponse(200, "ok")
    session = DummySession(response)

    async def _get_session():
        return session

    monkeypatch.setattr(telemetry, "_get_session", _get_session)

    result = await telemetry.send_event("test", "service", {"a": 1})
    assert result is True


@pytest.mark.asyncio
async def test_send_event_failure(monkeypatch):
    telemetry = logging_module.SimpleTelemetry("http://example.test", {})
    response = DummyResponse(400, "bad")
    session = DummySession(response)

    async def _get_session():
        return session

    monkeypatch.setattr(telemetry, "_get_session", _get_session)

    result = await telemetry.send_event("test", "service", {})
    assert result is False


@pytest.mark.asyncio
async def test_send_event_exception(monkeypatch):
    telemetry = logging_module.SimpleTelemetry("http://example.test", {})

    async def _get_session():
        raise RuntimeError("boom")

    monkeypatch.setattr(telemetry, "_get_session", _get_session)

    result = await telemetry.send_event("test", "service", {})
    assert result is False


@pytest.mark.asyncio
async def test_get_session_reuses_connector(monkeypatch):
    created = {"count": 0}

    class DummyClientSession:
        def __init__(self, *args, **kwargs):
            created["count"] += 1
            self.closed = False

    monkeypatch.setattr(logging_module.aiohttp, "ClientSession", DummyClientSession)
    monkeypatch.setattr(logging_module.aiohttp, "TCPConnector", lambda ssl: None)

    telemetry = logging_module.SimpleTelemetry("http://example.test", {})
    s1 = await telemetry._get_session()
    s2 = await telemetry._get_session()
    assert s1 is s2
    assert created["count"] == 1


@pytest.mark.asyncio
async def test_get_session_recreates_when_closed(monkeypatch):
    created = {"count": 0}

    class DummyClientSession:
        def __init__(self, *args, **kwargs):
            created["count"] += 1
            self.closed = False

    monkeypatch.setattr(logging_module.aiohttp, "ClientSession", DummyClientSession)
    monkeypatch.setattr(logging_module.aiohttp, "TCPConnector", lambda ssl: None)

    telemetry = logging_module.SimpleTelemetry("http://example.test", {})
    telemetry.session = SimpleNamespace(closed=True)
    await telemetry._get_session()
    assert created["count"] == 1


@pytest.mark.asyncio
async def test_close_session():
    telemetry = logging_module.SimpleTelemetry("http://example.test", {})
    session = DummySession(DummyResponse(200, "ok"))
    telemetry.session = session
    await telemetry.close()
    assert session.closed is True


def test_setup_simple_telemetry(monkeypatch):
    monkeypatch.setattr(logging_module, "OT_ENDPOINT", "http://otel.test")
    monkeypatch.setattr(logging_module, "OT_HEADERS", [("X-Key", "value")])
    telemetry = logging_module.setup_simple_telemetry("x", "y")
    assert telemetry is not None
    assert telemetry.url == "http://otel.test/log/v1"
    assert telemetry.headers["X-Key"] == "value"


def test_setup_simple_telemetry_error(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(logging_module, "SimpleTelemetry", _boom)
    assert logging_module.setup_simple_telemetry("x", "y") is None
