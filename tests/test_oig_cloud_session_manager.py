from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.oig_cloud.api.oig_cloud_session_manager import (
    MIN_REQUEST_INTERVAL,
    SESSION_TTL,
    OigCloudSessionManager,
)
from custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api import (
    OigCloudAuthError,
)


class DummySession:
    def __init__(self, headers=None, connector_headers=None):
        self._default_headers = headers
        self._connector = (
            SimpleNamespace(_default_headers=connector_headers)
            if connector_headers is not None
            else None
        )
        self.closed = False

    async def close(self):
        self.closed = True


class DummyApi:
    def __init__(self):
        self._phpsessid = "abc123" * 5
        self._base_url = "https://example.test"
        self.authenticate = AsyncMock()
        self.get_stats = AsyncMock(return_value={"ok": True})
        self.get_extended_stats = AsyncMock(return_value={"ok": True})
        self.set_battery_working_mode = AsyncMock(return_value={"ok": True})
        self.set_grid_delivery = AsyncMock(return_value={"ok": True})
        self.set_boiler_mode = AsyncMock(return_value={"ok": True})
        self.format_battery = AsyncMock(return_value={"ok": True})
        self.set_battery_capacity = AsyncMock(return_value={"ok": True})
        self.set_box_mode = AsyncMock(return_value={"ok": True})
        self.set_grid_delivery_limit = AsyncMock(return_value=True)
        self.set_formating_mode = AsyncMock(return_value={"ok": True})

    def get_session(self):
        return DummySession(headers={"User-Agent": "test"})


@pytest.mark.asyncio
async def test_log_api_session_info_variants(monkeypatch):
    api = DummyApi()
    manager = OigCloudSessionManager(api)

    session = DummySession(headers={"User-Agent": "test"})
    api.get_session = lambda: session
    await manager._log_api_session_info()
    assert session.closed is True

    session = DummySession(headers=None, connector_headers={"Accept": "json"})
    api.get_session = lambda: session
    await manager._log_api_session_info()
    assert session.closed is True

    session = DummySession(headers=None, connector_headers=None)
    api.get_session = lambda: session
    await manager._log_api_session_info()
    assert session.closed is True

    api.get_session = lambda: None
    await manager._log_api_session_info()


def test_is_session_expired():
    api = DummyApi()
    manager = OigCloudSessionManager(api)
    assert manager._is_session_expired() is True


def test_api_property():
    api = DummyApi()
    manager = OigCloudSessionManager(api)
    assert manager.api is api

    manager._last_auth_time = datetime.now() - SESSION_TTL + timedelta(seconds=10)
    assert manager._is_session_expired() is False

    manager._last_auth_time = datetime.now() - SESSION_TTL - timedelta(seconds=1)
    assert manager._is_session_expired() is True


@pytest.mark.asyncio
async def test_rate_limit(monkeypatch):
    api = DummyApi()
    manager = OigCloudSessionManager(api)
    manager._last_request_time = datetime.now()

    slept = {"seconds": 0}

    async def _sleep(seconds):
        slept["seconds"] = seconds

    monkeypatch.setattr("custom_components.oig_cloud.api.oig_cloud_session_manager.asyncio.sleep", _sleep)

    await manager._rate_limit()
    assert slept["seconds"] >= 0
    assert manager._last_request_time is not None


@pytest.mark.asyncio
async def test_call_with_retry_success(monkeypatch):
    api = DummyApi()
    manager = OigCloudSessionManager(api)
    manager._last_auth_time = datetime.now()

    await manager.get_stats()
    assert manager._stats["successful_requests"] == 1


@pytest.mark.asyncio
async def test_call_with_retry_auth_error(monkeypatch):
    api = DummyApi()
    manager = OigCloudSessionManager(api)

    async def _raise():
        raise OigCloudAuthError("nope")

    api.get_stats = _raise

    async def _sleep(_seconds):
        return None

    monkeypatch.setattr("custom_components.oig_cloud.api.oig_cloud_session_manager.asyncio.sleep", _sleep)

    with pytest.raises(OigCloudAuthError):
        await manager.get_stats()

    assert manager._stats["retry_count"] >= 1
    assert manager._stats["failed_requests"] == 1


@pytest.mark.asyncio
async def test_call_with_retry_unexpected_error():
    api = DummyApi()
    manager = OigCloudSessionManager(api)

    async def _raise():
        raise RuntimeError("boom")

    api.get_stats = _raise

    with pytest.raises(RuntimeError):
        await manager.get_stats()
    assert manager._stats["failed_requests"] == 1


def test_get_statistics_populates_rates():
    api = DummyApi()
    manager = OigCloudSessionManager(api)
    manager._stats["total_requests"] = 10
    manager._stats["successful_requests"] = 7
    manager._last_auth_time = datetime.now() - timedelta(minutes=5)

    stats = manager.get_statistics()
    assert stats["success_rate_percent"] == 70.0
    assert stats["current_session_age_minutes"] > 0


@pytest.mark.asyncio
async def test_log_api_session_info_with_errors(monkeypatch):
    class BrokenApi:
        def __getattr__(self, _name):
            raise RuntimeError("boom")

    manager = OigCloudSessionManager(BrokenApi())
    await manager._log_api_session_info()

    api = DummyApi()
    manager = OigCloudSessionManager(api)

    def _raise_session():
        raise RuntimeError("boom")

    api.get_session = _raise_session
    await manager._log_api_session_info()


@pytest.mark.asyncio
async def test_ensure_auth_failure(monkeypatch):
    api = DummyApi()
    api.authenticate = AsyncMock(side_effect=RuntimeError("fail"))
    manager = OigCloudSessionManager(api)

    with pytest.raises(RuntimeError):
        await manager._ensure_auth()


@pytest.mark.asyncio
async def test_wrapper_methods_cover_args(monkeypatch):
    api = DummyApi()
    manager = OigCloudSessionManager(api)
    manager._last_auth_time = datetime.now()

    async def _noop():
        return None

    monkeypatch.setattr(manager, "_ensure_auth", _noop)
    monkeypatch.setattr(manager, "_rate_limit", _noop)

    await manager.get_extended_stats("batt", "2025-01-01", "2025-01-02")
    await manager.set_battery_working_mode("123", "1", "a", "b")
    await manager.set_grid_delivery(1)
    await manager.set_boiler_mode(1)
    await manager.format_battery(1)
    await manager.set_battery_capacity(10.0)
    await manager.set_box_mode("1")
    await manager.set_grid_delivery_limit(5)
    await manager.set_formating_mode("x")


@pytest.mark.asyncio
async def test_close_resets_state():
    api = DummyApi()
    manager = OigCloudSessionManager(api)
    manager._last_auth_time = datetime.now()
    manager._last_request_time = datetime.now()
    manager._stats["total_requests"] = 1

    await manager.close()

    assert manager._last_auth_time is None
    assert manager._last_request_time is None
