import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.oig_cloud.api.oig_cloud_api import OigCloudAuthError
from custom_components.oig_cloud.api.oig_cloud_session_manager import (
    MIN_REQUEST_INTERVAL,
    OigCloudSessionManager,
)


class TestOigCloudSessionManagerInit:
    def test_init(self):
        mock_api = MagicMock()
        mgr = OigCloudSessionManager(mock_api)
        assert mgr.api is mock_api
        assert mgr._last_auth_time is None
        assert mgr._last_request_time is None
        assert mgr._stats["total_requests"] == 0

    def test_api_property(self):
        mock_api = MagicMock()
        mgr = OigCloudSessionManager(mock_api)
        assert mgr.api is mock_api


class TestOigCloudSessionManagerDebugSession:
    @pytest.fixture
    def mock_api(self):
        api = MagicMock()
        api.authenticate = AsyncMock()
        api.get_session = MagicMock(return_value=MagicMock(close=AsyncMock()))
        return api

    @pytest.fixture
    def mgr(self, mock_api):
        return OigCloudSessionManager(mock_api)

    async def test_log_api_session_info(self, mgr, mock_api):
        mock_api._base_url = "https://example.com/"
        session = MagicMock()
        session._default_headers = {"X-Test": "value"}
        session.close = AsyncMock()
        mock_api.get_session = MagicMock(return_value=session)
        await mgr._log_api_session_info()
        session.close.assert_awaited_once()

    async def test_log_api_session_info_no_session(self, mgr, mock_api):
        mock_api._base_url = "https://example.com/"
        mock_api.get_session = MagicMock(side_effect=Exception("no session"))
        await mgr._log_api_session_info()

    async def test_open_debug_session_success(self, mgr, mock_api):
        session = MagicMock()
        mock_api.get_session = MagicMock(return_value=session)
        result = mgr._open_debug_session()
        assert result is session

    async def test_open_debug_session_failure(self, mgr, mock_api):
        mock_api.get_session = MagicMock(side_effect=RuntimeError("fail"))
        result = mgr._open_debug_session()
        assert result is None

    def test_extract_session_headers_default_headers(self):
        session = MagicMock()
        session._default_headers = {"Authorization": "Bearer token"}
        headers = OigCloudSessionManager._extract_session_headers(session)
        assert headers == {"Authorization": "Bearer token"}

    def test_extract_session_headers_connector_headers(self):
        session = MagicMock()
        session._default_headers = None
        session._connector = MagicMock()
        session._connector._default_headers = {"X-Custom": "val"}
        headers = OigCloudSessionManager._extract_session_headers(session)
        assert headers == {"X-Custom": "val"}

    def test_extract_session_headers_none(self):
        session = MagicMock()
        session._default_headers = None
        del session._connector
        headers = OigCloudSessionManager._extract_session_headers(session)
        assert headers is None

    def test_log_session_headers(self, mgr):
        session = MagicMock()
        session._default_headers = {"Authorization": "secret"}
        mgr._log_session_headers(session)


class TestOigCloudSessionManagerAuth:
    @pytest.fixture
    def mock_api(self):
        api = MagicMock()
        api.authenticate = AsyncMock()
        api._phpsessid = "test_session"
        api._base_url = "https://example.com"
        return api

    @pytest.fixture
    def mgr(self, mock_api):
        return OigCloudSessionManager(mock_api)

    def test_is_session_expired_no_auth(self, mgr):
        assert mgr._is_session_expired() is True

    def test_is_session_expired_yes(self, mgr):
        mgr._last_auth_time = datetime.now() - timedelta(hours=1)
        assert mgr._is_session_expired() is True

    def test_is_session_expired_no(self, mgr):
        mgr._last_auth_time = datetime.now() - timedelta(minutes=5)
        assert mgr._is_session_expired() is False

    async def test_ensure_auth_first_time(self, mgr, mock_api):
        await mgr._ensure_auth()
        assert mgr._last_auth_time is not None
        mock_api.authenticate.assert_awaited_once()
        assert mgr._stats["auth_count"] == 1

    async def test_ensure_auth_not_expired(self, mgr, mock_api):
        mgr._last_auth_time = datetime.now() - timedelta(minutes=5)
        await mgr._ensure_auth()
        mock_api.authenticate.assert_not_awaited()

    async def test_ensure_auth_expired(self, mgr, mock_api):
        mgr._last_auth_time = datetime.now() - timedelta(hours=1)
        await mgr._ensure_auth()
        mock_api.authenticate.assert_awaited_once()

    async def test_ensure_auth_failure(self, mgr, mock_api):
        mock_api.authenticate = AsyncMock(side_effect=OigCloudAuthError("fail"))
        with pytest.raises(OigCloudAuthError):
            await mgr._ensure_auth()


class TestOigCloudSessionManagerRateLimit:
    @pytest.fixture
    def mgr(self):
        mock_api = MagicMock()
        return OigCloudSessionManager(mock_api)

    async def test_rate_limit_first_request(self, mgr):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await mgr._rate_limit()
            mock_sleep.assert_not_awaited()
            assert mgr._last_request_time is not None

    async def test_rate_limit_enforced(self, mgr):
        mgr._last_request_time = datetime.now()
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await mgr._rate_limit()
            mock_sleep.assert_awaited_once()
            assert mgr._stats["rate_limited_count"] == 1

    async def test_rate_limit_not_needed(self, mgr):
        mgr._last_request_time = datetime.now() - MIN_REQUEST_INTERVAL - timedelta(seconds=1)
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await mgr._rate_limit()
            mock_sleep.assert_not_awaited()


class TestOigCloudSessionManagerCallWithRetry:
    @pytest.fixture
    def mock_api(self):
        api = MagicMock()
        api.authenticate = AsyncMock()
        api.get_session = MagicMock(return_value=MagicMock(close=AsyncMock()))
        return api

    @pytest.fixture
    def mgr(self, mock_api):
        return OigCloudSessionManager(mock_api)

    async def test_call_success(self, mgr, mock_api):
        method = AsyncMock(return_value={"data": "ok"})
        result = await mgr._call_with_retry(method, "arg1", key="val")
        assert result == {"data": "ok"}
        method.assert_awaited_once_with("arg1", key="val")
        assert mgr._stats["successful_requests"] == 1

    async def test_call_auth_error_then_success(self, mgr, mock_api):
        method = AsyncMock(side_effect=[OigCloudAuthError("401"), {"data": "ok"}])
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await mgr._call_with_retry(method)
        assert result == {"data": "ok"}
        assert mgr._stats["retry_count"] == 1
        assert method.await_count == 2

    async def test_call_auth_error_exhausted(self, mgr, mock_api):
        method = AsyncMock(side_effect=OigCloudAuthError("401"))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(OigCloudAuthError):
                await mgr._call_with_retry(method)
        assert mgr._stats["failed_requests"] == 1

    async def test_call_unexpected_error(self, mgr, mock_api):
        method = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            await mgr._call_with_retry(method)
        assert mgr._stats["failed_requests"] == 1

    async def test_call_auth_error_resets_auth_time(self, mgr, mock_api):
        mgr._last_auth_time = datetime.now()
        method = AsyncMock(side_effect=[OigCloudAuthError("401"), {"ok": True}])
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await mgr._call_with_retry(method)
        assert mock_api.authenticate.await_count >= 1


class TestOigCloudSessionManagerWrappedMethods:
    @pytest.fixture
    def mock_api(self):
        api = MagicMock()
        api.authenticate = AsyncMock()
        api.get_session = MagicMock(return_value=MagicMock(close=AsyncMock()))
        return api

    @pytest.fixture
    def mgr(self, mock_api):
        return OigCloudSessionManager(mock_api)

    async def test_get_stats(self, mgr, mock_api):
        mock_api.get_stats = AsyncMock(return_value={"stats": True})
        result = await mgr.get_stats()
        assert result == {"stats": True}
        mock_api.get_stats.assert_awaited_once()

    async def test_get_extended_stats(self, mgr, mock_api):
        mock_api.get_extended_stats = AsyncMock(return_value={"ext": True})
        result = await mgr.get_extended_stats("batt", "2024-01-01", "2024-01-02")
        mock_api.get_extended_stats.assert_awaited_once_with("batt", "2024-01-01", "2024-01-02")

    async def test_set_battery_working_mode(self, mgr, mock_api):
        mock_api.set_battery_working_mode = AsyncMock(return_value={"ok": True})
        result = await mgr.set_battery_working_mode("SN123", "HOME_I", "08:00", "10:00")
        mock_api.set_battery_working_mode.assert_awaited_once_with("SN123", "HOME_I", "08:00", "10:00")

    async def test_set_grid_delivery(self, mgr, mock_api):
        mock_api.set_grid_delivery = AsyncMock(return_value={"ok": True})
        result = await mgr.set_grid_delivery(1)
        mock_api.set_grid_delivery.assert_awaited_once_with(1)

    async def test_set_boiler_mode(self, mgr, mock_api):
        mock_api.set_boiler_mode = AsyncMock(return_value={"ok": True})
        result = await mgr.set_boiler_mode(2)
        mock_api.set_boiler_mode.assert_awaited_once_with(2)

    async def test_format_battery(self, mgr, mock_api):
        mock_api.format_battery = AsyncMock(return_value={"ok": True})
        result = await mgr.format_battery(1)
        mock_api.format_battery.assert_awaited_once_with(1)

    async def test_set_battery_capacity(self, mgr, mock_api):
        mock_api.set_battery_capacity = AsyncMock(return_value={"ok": True})
        result = await mgr.set_battery_capacity(100.0)
        mock_api.set_battery_capacity.assert_awaited_once_with(100.0)

    async def test_set_box_mode(self, mgr, mock_api):
        mock_api.set_box_mode = AsyncMock(return_value={"ok": True})
        result = await mgr.set_box_mode("HOME_I")
        mock_api.set_box_mode.assert_awaited_once_with("HOME_I")

    async def test_set_box_prm2_app(self, mgr, mock_api):
        mock_api.set_box_prm2_app = AsyncMock(return_value={"ok": True})
        result = await mgr.set_box_prm2_app(1)
        mock_api.set_box_prm2_app.assert_awaited_once_with(1)

    async def test_set_grid_delivery_limit(self, mgr, mock_api):
        mock_api.set_grid_delivery_limit = AsyncMock(return_value=True)
        result = await mgr.set_grid_delivery_limit(5000)
        mock_api.set_grid_delivery_limit.assert_awaited_once_with(5000)

    async def test_set_formating_mode(self, mgr, mock_api):
        mock_api.set_formating_mode = AsyncMock(return_value={"ok": True})
        result = await mgr.set_formating_mode("AUTO")
        mock_api.set_formating_mode.assert_awaited_once_with("AUTO")


class TestOigCloudSessionManagerStatsAndClose:
    @pytest.fixture
    def mgr(self):
        mock_api = MagicMock()
        mock_api.authenticate = AsyncMock()
        return OigCloudSessionManager(mock_api)

    async def test_get_statistics_basic(self, mgr):
        stats = mgr.get_statistics()
        assert "uptime_seconds" in stats
        assert stats["total_requests"] == 0

    async def test_get_statistics_with_requests(self, mgr):
        mgr._stats["total_requests"] = 10
        mgr._stats["successful_requests"] = 8
        mgr._last_auth_time = datetime.now() - timedelta(minutes=5)
        stats = mgr.get_statistics()
        assert stats["total_requests"] == 10
        assert stats["success_rate_percent"] == 80.0
        assert "current_session_age_seconds" in stats
        assert "session_expires_in_minutes" in stats

    async def test_close(self, mgr):
        mgr._last_auth_time = datetime.now()
        mgr._last_request_time = datetime.now()
        await mgr.close()
        assert mgr._last_auth_time is None
        assert mgr._last_request_time is None

    async def test_close_with_stats(self, mgr):
        mgr._stats["total_requests"] = 5
        mgr._stats["successful_requests"] = 4
        await mgr.close()
