"""Tests for the OIG Cloud API client."""

import asyncio
import importlib
import ssl
import json
import sys
import types
from unittest.mock import AsyncMock, Mock, patch

import aiohttp

import pytest

from custom_components.oig_cloud.lib.oig_cloud_client.api import oig_cloud_api as api_module
from custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api import (
    OigCloudApi,
    OigCloudApiError,
    OigCloudAuthError,
    OigCloudConnectionError,
    OigCloudTimeoutError,
)


def _make_response(
    *, status: int = 200, json_data=None, text_data: str = "", headers=None
) -> AsyncMock:
    response = AsyncMock()
    response.status = status
    response.headers = headers or {}
    response.json = AsyncMock(return_value=json_data)
    response.text = AsyncMock(return_value=text_data)
    response.request_info = Mock()
    response.history = ()
    return response


def _make_context_manager(response: AsyncMock) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__.return_value = response
    cm.__aexit__.return_value = None
    return cm


def _make_context_manager_raises(exc: Exception) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__.side_effect = exc
    cm.__aexit__.return_value = None
    return cm


def _make_session(*, get_response=None, post_response=None) -> Mock:
    session = Mock()
    if get_response is not None:
        session.get = Mock(return_value=_make_context_manager(get_response))
    if post_response is not None:
        session.post = Mock(return_value=_make_context_manager(post_response))
    return session


def _make_session_context(session: Mock) -> AsyncMock:
    cm = AsyncMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = None
    return cm


def test_opentelemetry_import(monkeypatch):
    fake_trace = types.SimpleNamespace(get_tracer=lambda name: "tracer")
    monkeypatch.setitem(
        sys.modules, "opentelemetry", types.SimpleNamespace(trace=fake_trace)
    )
    monkeypatch.setitem(
        sys.modules, "opentelemetry.trace", types.SimpleNamespace(SpanKind="span")
    )

    spec = importlib.util.spec_from_file_location(
        "custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api_otel",
        api_module.__file__,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["oig_cloud_api_otel"] = module
    spec.loader.exec_module(module)
    assert module._has_opentelemetry is True
    assert module.tracer == "tracer"


@pytest.mark.asyncio
class TestOigCloudApi:
    """Test the OIG Cloud API client."""

    def setup_method(self):
        """Set up test fixtures."""
        self.api = OigCloudApi("username", "password", False, None)

        # Sample API response data
        with open("tests/sample-response.json", "r") as f:
            self.sample_data = json.load(f)

    async def test_ssl_context_cached(self):
        ctx1 = self.api._get_ssl_context_with_intermediate()
        ctx2 = self.api._get_ssl_context_with_intermediate()
        assert ctx1 is ctx2

    async def test_get_connector_modes(self, monkeypatch):
        self.api._ssl_mode = 1
        monkeypatch.setattr(
            self.api, "_get_ssl_context_with_intermediate", ssl.create_default_context
        )
        connector = self.api._get_connector()
        assert isinstance(connector._ssl, ssl.SSLContext)

        self.api._ssl_mode = 2
        connector = self.api._get_connector()
        assert connector._ssl is False

    async def test_get_stats(self):
        """Test getting stats from API."""
        mock_response = _make_response(
            status=200, json_data={"key": "value"}, headers={}
        )
        session = _make_session(get_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.get_stats()

        assert result == {"key": "value"}
        assert self.api.last_state == {"key": "value"}
        assert self.api.box_id == "key"
        assert self.api._last_update is not None

        expected_url = f"{self.api._base_url}{self.api._get_stats_url}"
        session.get.assert_called_once_with(expected_url, headers={})

    async def test_get_stats_etag_cache(self):
        """Test ETag cache usage for stats."""
        cached = {"cached_key": "cached_value"}
        self.api._cache["json.php"] = {"etag": "etag123", "data": cached, "ts": 1}

        mock_response = _make_response(status=304, headers={"ETag": "etag123"})
        session = _make_session(get_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.get_stats()

        assert result == cached

        expected_url = f"{self.api._base_url}{self.api._get_stats_url}"
        session.get.assert_called_once_with(
            expected_url, headers={"If-None-Match": "etag123"}
        )

    @patch(
        "custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.aiohttp.ClientSession"
    )
    async def test_authenticate_success(self, mock_session):
        """Test successful authentication."""
        # Configure mock response
        mock_response = _make_response(status=200, text_data='[[2,"",false]]')
        response_ctx = _make_context_manager(mock_response)

        # Setup cookie
        mock_cookie = Mock()
        mock_cookie.value = "test_session_id"
        mock_cookie_jar = Mock()
        mock_cookie_jar.filter_cookies.return_value = {"PHPSESSID": mock_cookie}

        session = Mock()
        session.post.return_value = response_ctx
        session.cookie_jar = mock_cookie_jar
        session_ctx = _make_session_context(session)
        mock_session.return_value = session_ctx

        result = await self.api.authenticate()
        assert result is True
        assert self.api._phpsessid == "test_session_id"
        session.post.assert_called_once()

    @patch(
        "custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.aiohttp.ClientSession"
    )
    async def test_authenticate_failure_wrong_response(self, mock_session):
        """Test authentication failure with wrong response."""
        # Configure mock response
        mock_response = _make_response(
            status=200, text_data='{"error": "Invalid credentials"}'
        )
        response_ctx = _make_context_manager(mock_response)

        session = Mock()
        session.post.return_value = response_ctx
        session_ctx = _make_session_context(session)
        mock_session.return_value = session_ctx

        with pytest.raises(OigCloudAuthError):
            await self.api.authenticate()

        session.post.assert_called_once()

    @patch(
        "custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.aiohttp.ClientSession"
    )
    async def test_authenticate_failure_http_error(self, mock_session):
        """Test authentication failure with HTTP error."""
        # Configure mock response
        mock_response = _make_response(status=401, text_data="Unauthorized")
        response_ctx = _make_context_manager(mock_response)

        session = Mock()
        session.post.return_value = response_ctx
        session_ctx = _make_session_context(session)
        mock_session.return_value = session_ctx

        with pytest.raises(OigCloudAuthError):
            await self.api.authenticate()

        session.post.assert_called_once()

    @patch(
        "custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.aiohttp.ClientSession"
    )
    async def test_authenticate_timeout(self, mock_session):
        """Test authentication timeout handling."""
        timeout_cm = _make_context_manager_raises(asyncio.TimeoutError("timeout"))
        session = Mock()
        session.post.return_value = timeout_cm
        session_ctx = _make_session_context(session)
        mock_session.return_value = session_ctx

        with pytest.raises(OigCloudTimeoutError):
            await self.api.authenticate()

    @patch(
        "custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.aiohttp.ClientSession"
    )
    async def test_authenticate_ssl_fallback_success(self, mock_session):
        """Test SSL fallback on connector error."""
        class _FakeConnectorError(aiohttp.ClientConnectorError):
            def __str__(self):
                return "SSL error"

        ssl_error = _FakeConnectorError(Mock(), OSError("SSL error"))
        bad_cm = _make_context_manager_raises(ssl_error)

        ok_response = _make_response(status=200, text_data='[[2,"",false]]')
        ok_cm = _make_context_manager(ok_response)

        session_bad = Mock()
        session_bad.post.return_value = bad_cm
        session_good = Mock()
        mock_cookie = Mock()
        mock_cookie.value = "test_session_id"
        mock_cookie_jar = Mock()
        mock_cookie_jar.filter_cookies.return_value = {"PHPSESSID": mock_cookie}
        session_good.cookie_jar = mock_cookie_jar
        session_good.post.return_value = ok_cm

        mock_session.side_effect = [
            _make_session_context(session_bad),
            _make_session_context(session_good),
        ]

        result = await self.api.authenticate()
        assert result is True

    @patch(
        "custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.aiohttp.ClientSession"
    )
    async def test_authenticate_ssl_fallback_exhausted(self, mock_session):
        """Test SSL fallback exhausted handling."""
        self.api._ssl_mode = 2
        class _FakeConnectorError(aiohttp.ClientConnectorError):
            def __str__(self):
                return "SSL error"

        ssl_error = _FakeConnectorError(Mock(), OSError("SSL error"))
        bad_cm = _make_context_manager_raises(ssl_error)
        session_bad = Mock()
        session_bad.post.return_value = bad_cm
        mock_session.return_value = _make_session_context(session_bad)

        with pytest.raises(OigCloudConnectionError):
            await self.api.authenticate()

    @patch(
        "custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.aiohttp.ClientSession"
    )
    async def test_authenticate_unexpected_error(self, mock_session):
        """Test authentication unexpected error handling."""
        bad_cm = _make_context_manager_raises(ValueError("boom"))
        session = Mock()
        session.post.return_value = bad_cm
        mock_session.return_value = _make_session_context(session)

        with pytest.raises(OigCloudAuthError):
            await self.api.authenticate()

    async def test_authenticate_no_ssl_modes_left(self):
        """Test authenticate when no SSL modes remain."""
        self.api._ssl_mode = 3
        with pytest.raises(OigCloudAuthError):
            await self.api._authenticate_internal()

    @patch(
        "custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.aiohttp.ClientSession"
    )
    async def test_get_session_not_authenticated(self, mock_session):
        """Test get_session when not authenticated."""
        self.api._phpsessid = None

        with pytest.raises(OigCloudAuthError):
            self.api.get_session()

        mock_session.assert_not_called()

    @patch(
        "custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.aiohttp.ClientSession"
    )
    async def test_get_session_headers(self, mock_session):
        """Test get_session header construction."""
        self.api._phpsessid = "abc"
        connector = object()
        with patch.object(self.api, "_get_connector", return_value=connector):
            self.api.get_session()

        args, kwargs = mock_session.call_args
        headers = kwargs["headers"]
        assert headers["Cookie"] == "PHPSESSID=abc"
        assert kwargs["connector"] is connector

    async def test_try_get_stats_auth_retry(self):
        """Test retry when stats response is invalid."""
        mock_response1 = _make_response(status=200, json_data="Not a dict")
        mock_response2 = _make_response(status=200, json_data={"key": "value"})

        session1 = _make_session(get_response=mock_response1)
        session2 = _make_session(get_response=mock_response2)
        session_ctx1 = _make_session_context(session1)
        session_ctx2 = _make_session_context(session2)

        with (
            patch.object(
                self.api, "get_session", side_effect=[session_ctx1, session_ctx2]
            ),
            patch.object(self.api, "authenticate", return_value=True) as mock_auth,
        ):
            result = await self.api._try_get_stats()
            assert result == {"key": "value"}
            mock_auth.assert_called_once()

    async def test_update_cache_with_etag(self):
        response = _make_response(status=200, json_data={"k": "v"}, headers={"ETag": "abc"})
        self.api._update_cache("json.php", response, {"k": "v"})
        assert self.api._cache["json.php"]["etag"] == "abc"

    async def test_get_stats_internal_timeout_cached(self):
        self.api.last_state = {"cached": 1}

        async def _raise():
            raise asyncio.TimeoutError("boom")

        with patch.object(self.api, "_try_get_stats", _raise):
            result = await self.api._get_stats_internal()
        assert result == {"cached": 1}

    async def test_get_stats_internal_timeout_raises(self):
        async def _raise():
            raise asyncio.TimeoutError("boom")

        with patch.object(self.api, "_try_get_stats", _raise):
            with pytest.raises(OigCloudTimeoutError):
                await self.api._get_stats_internal()

    async def test_get_stats_internal_connection_cached(self):
        self.api.last_state = {"cached": 1}
        error = aiohttp.ClientConnectorError(Mock(), OSError("connection"))

        async def _raise():
            raise error

        with patch.object(self.api, "_try_get_stats", _raise):
            result = await self.api._get_stats_internal()
        assert result == {"cached": 1}

    async def test_get_stats_internal_connection_raises(self):
        error = aiohttp.ClientConnectorError(Mock(), OSError("connection"))

        async def _raise():
            raise error

        with patch.object(self.api, "_try_get_stats", _raise):
            with pytest.raises(OigCloudConnectionError):
                await self.api._get_stats_internal()

    async def test_get_stats_internal_unexpected_cached(self):
        self.api.last_state = {"cached": 1}

        async def _raise():
            raise ValueError("boom")

        with patch.object(self.api, "_try_get_stats", _raise):
            result = await self.api._get_stats_internal()
        assert result == {"cached": 1}

    async def test_get_stats_internal_unexpected_raises(self):
        async def _raise():
            raise ValueError("boom")

        with patch.object(self.api, "_try_get_stats", _raise):
            with pytest.raises(OigCloudApiError):
                await self.api._get_stats_internal()

    async def test_try_get_stats_304_retry_failure(self):
        mock_response = _make_response(status=304, headers={})
        retry_response = _make_response(status=500, headers={})
        session = Mock()
        session.get.side_effect = [
            _make_context_manager(mock_response),
            _make_context_manager(retry_response),
        ]
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            with pytest.raises(aiohttp.ClientResponseError):
                await self.api._try_get_stats()

    async def test_try_get_stats_304_retry_success(self):
        mock_response = _make_response(status=304, headers={})
        retry_response = _make_response(status=200, json_data={"k": "v"}, headers={})
        session = Mock()
        session.get.side_effect = [
            _make_context_manager(mock_response),
            _make_context_manager(retry_response),
        ]
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api._try_get_stats()
        assert result == {"k": "v"}

    async def test_try_get_stats_http_error(self):
        mock_response = _make_response(status=500, headers={})
        session = _make_session(get_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            with pytest.raises(aiohttp.ClientResponseError):
                await self.api._try_get_stats()

    async def test_try_get_stats_timeout(self):
        timeout_ctx = _make_context_manager_raises(asyncio.TimeoutError("boom"))
        session = Mock()
        session.get.return_value = timeout_ctx
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            with pytest.raises(asyncio.TimeoutError):
                await self.api._try_get_stats()

    async def test_try_get_stats_connection_error(self):
        conn_err = aiohttp.ClientConnectorError(Mock(), OSError("conn"))
        conn_ctx = _make_context_manager_raises(conn_err)
        session = Mock()
        session.get.return_value = conn_ctx
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            with pytest.raises(aiohttp.ClientConnectorError):
                await self.api._try_get_stats()

    async def test_set_box_mode(self):
        """Test setting box mode."""
        # Mock the internal method
        with patch.object(
            self.api, "set_box_params_internal", return_value=True
        ) as mock_set_params:
            result = await self.api.set_box_mode("1")
            assert result is True
            mock_set_params.assert_called_once_with("box_prms", "mode", "1")

    async def test_set_grid_delivery_limit(self):
        """Test setting grid delivery limit."""
        # Mock the internal method
        with patch.object(
            self.api, "set_box_params_internal", return_value=True
        ) as mock_set_params:
            result = await self.api.set_grid_delivery_limit(5000)
            assert result is True
            mock_set_params.assert_called_once_with(
                "invertor_prm1", "p_max_feed_grid", "5000"
            )

    async def test_set_boiler_mode(self):
        """Test setting boiler mode."""
        # Mock the internal method
        with patch.object(
            self.api, "set_box_params_internal", return_value=True
        ) as mock_set_params:
            result = await self.api.set_boiler_mode("1")
            assert result is True
            mock_set_params.assert_called_once_with("boiler_prms", "manual", "1")

    async def test_set_box_mode_error(self):
        with patch.object(self.api, "set_box_params_internal", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                await self.api.set_box_mode("1")

    async def test_set_grid_delivery_limit_error(self):
        with patch.object(self.api, "set_box_params_internal", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                await self.api.set_grid_delivery_limit(100)

    async def test_set_boiler_mode_error(self):
        with patch.object(self.api, "set_box_params_internal", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                await self.api.set_boiler_mode("1")

    async def test_set_ssr_rele_errors(self):
        with patch.object(self.api, "set_box_params_internal", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                await self.api.set_ssr_rele_1("1")
            with pytest.raises(RuntimeError):
                await self.api.set_ssr_rele_2("1")
            with pytest.raises(RuntimeError):
                await self.api.set_ssr_rele_3("1")

    @patch("custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.time")
    async def test_set_box_params_internal(self, mock_time):
        """Test setting box parameters."""
        self.api.box_id = "test_box_id"
        mock_time.time.return_value = 1711698897.123
        nonce = int(1711698897.123 * 1000)

        # Configure mock response
        mock_response = _make_response(status=200, text_data='[[0,2,"OK"]]')
        session = _make_session(post_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.set_box_params_internal("table", "column", "value")
        assert result is True

        expected_url = f"https://portal.oigpower.cz/inc/php/scripts/Device.Set.Value.php?_nonce={nonce}"
        expected_data = json.dumps(
            {
                "id_device": "test_box_id",
                "table": "table",
                "column": "column",
                "value": "value",
            }
        )

        session.post.assert_called_once_with(
            expected_url,
            data=expected_data,
            headers={"Content-Type": "application/json"},
        )

    async def test_set_box_params_internal_not_authenticated(self):
        """Test setting box parameters without authentication."""
        self.api._phpsessid = None

        with pytest.raises(OigCloudAuthError):
            await self.api.set_box_params_internal("table", "column", "value")

    @patch("custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.time")
    async def test_set_box_params_internal_failure(self, mock_time):
        """Test setting box parameters failure."""
        self.api.box_id = "test_box_id"
        mock_time.time.return_value = 1711698897.123

        # Configure mock response
        mock_response = _make_response(status=400, text_data="Bad Request")
        session = _make_session(post_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            with pytest.raises(Exception):
                await self.api.set_box_params_internal("table", "column", "value")

    @patch("custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.time")
    async def test_set_grid_delivery(self, mock_time):
        """Test setting grid delivery mode."""
        self.api.box_id = "test_box_id"
        mock_time.time.return_value = 1711698897.123
        nonce = int(1711698897.123 * 1000)

        # Configure mock response
        mock_response = _make_response(status=200, text_data='[[0,2,"OK"]]')
        session = _make_session(post_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.set_grid_delivery(1)
        assert result is True

        expected_url = f"https://portal.oigpower.cz/inc/php/scripts/ToGrid.Toggle.php?_nonce={nonce}"
        expected_data = json.dumps(
            {
                "id_device": "test_box_id",
                "value": 1,
            }
        )

        session.post.assert_called_once_with(
            expected_url,
            data=expected_data,
            headers={"Content-Type": "application/json"},
        )

    async def test_set_grid_delivery_no_telemetry(self):
        """Test setting grid delivery with no telemetry."""
        self.api._no_telemetry = True

        with pytest.raises(OigCloudApiError):
            await self.api.set_grid_delivery(1)

    async def test_set_grid_delivery_no_box_id(self):
        self.api.box_id = None
        with pytest.raises(OigCloudApiError):
            await self.api.set_grid_delivery(1)

    @patch("custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.time")
    async def test_set_grid_delivery_http_error(self, mock_time):
        self.api.box_id = "test_box_id"
        mock_time.time.return_value = 1711698897.123

        mock_response = _make_response(status=500, text_data="Bad Request")
        session = _make_session(post_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            with pytest.raises(OigCloudApiError):
                await self.api.set_grid_delivery(1)

    async def test_set_grid_delivery_exception(self):
        self.api.box_id = "test_box_id"
        with patch.object(self.api, "get_session", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                await self.api.set_grid_delivery(1)

    @patch("custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.time")
    async def test_set_battery_formating_success(self, mock_time):
        self.api.box_id = "test_box_id"
        mock_time.time.return_value = 1711698897.123
        nonce = int(1711698897.123 * 1000)

        mock_response = _make_response(status=200, text_data='[[0,2,"OK"]]')
        session = _make_session(post_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.set_battery_formating("1", 80)
        assert result is True

        expected_url = f"https://portal.oigpower.cz/inc/php/scripts/Battery.Format.Save.php?_nonce={nonce}"
        session.post.assert_called_once()
        assert expected_url in session.post.call_args[0][0]

    @patch("custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.time")
    async def test_set_battery_formating_error(self, mock_time):
        self.api.box_id = "test_box_id"
        mock_time.time.return_value = 1711698897.123

        mock_response = _make_response(status=500, text_data="Bad Request")
        session = _make_session(post_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            with pytest.raises(Exception):
                await self.api.set_battery_formating("1", 80)

    @patch("custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.time")
    async def test_set_formating_mode(self, mock_time):
        """Test setting battery formatting mode."""
        mock_time.time.return_value = 1711698897.123
        nonce = int(1711698897.123 * 1000)

        # Configure mock response
        mock_response = _make_response(status=200, text_data='[[0,2,"OK"]]')
        session = _make_session(post_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.set_formating_mode("1")
        assert result is True

        expected_url = f"https://portal.oigpower.cz/inc/php/scripts/Battery.Format.Save.php?_nonce={nonce}"
        expected_data = json.dumps(
            {
                "bat_ac": "1",
            }
        )

        session.post.assert_called_once_with(
            expected_url,
            data=expected_data,
            headers={"Content-Type": "application/json"},
        )

    @patch("custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api.time")
    async def test_set_formating_mode_http_error(self, mock_time):
        mock_time.time.return_value = 1711698897.123
        mock_response = _make_response(status=500, text_data="Bad Request")
        session = _make_session(post_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            with pytest.raises(OigCloudApiError):
                await self.api.set_formating_mode("1")

    async def test_set_formating_mode_exception(self):
        with patch.object(self.api, "get_session", side_effect=RuntimeError("boom")):
            with pytest.raises(OigCloudApiError):
                await self.api.set_formating_mode("1")

    async def test_get_extended_stats_cached(self):
        self.api._cache["json2.php:foo"] = {"etag": "etag123", "data": {"a": 1}, "ts": 1}
        mock_response = _make_response(status=304, headers={"ETag": "etag123"})
        session = _make_session(post_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.get_extended_stats("foo", "2020-01-01", "2020-01-02")
        assert result == {"a": 1}

    async def test_get_extended_stats_retry_success(self):
        mock_response = _make_response(status=304, headers={})
        retry_response = _make_response(status=200, json_data={"a": 1}, headers={})
        session = Mock()
        session.post.side_effect = [
            _make_context_manager(mock_response),
            _make_context_manager(retry_response),
        ]
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.get_extended_stats("foo", "2020-01-01", "2020-01-02")
        assert result == {"a": 1}

    async def test_get_extended_stats_json_error(self):
        mock_response = _make_response(status=200, json_data=None, headers={})
        mock_response.json.side_effect = ValueError("bad json")
        session = _make_session(post_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.get_extended_stats("foo", "2020-01-01", "2020-01-02")
        assert result == {}

    async def test_get_extended_stats_auth_retry(self):
        response_401 = _make_response(status=401, headers={})
        response_200 = _make_response(status=200, json_data={"a": 1}, headers={})
        session1 = _make_session(post_response=response_401)
        session2 = _make_session(post_response=response_200)

        with (
            patch.object(self.api, "get_session", side_effect=[_make_session_context(session1), _make_session_context(session2)]),
            patch.object(self.api, "authenticate", return_value=True),
        ):
            result = await self.api.get_extended_stats("foo", "2020-01-01", "2020-01-02")
        assert result == {"a": 1}

    async def test_get_extended_stats_auth_retry_failed(self):
        response_401 = _make_response(status=401, headers={})
        session = _make_session(post_response=response_401)
        session_ctx = _make_session_context(session)

        with (
            patch.object(self.api, "get_session", return_value=session_ctx),
            patch.object(self.api, "authenticate", return_value=False),
        ):
            result = await self.api.get_extended_stats("foo", "2020-01-01", "2020-01-02")
        assert result == {}

    async def test_get_extended_stats_http_error(self):
        mock_response = _make_response(status=500, headers={})
        session = _make_session(post_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.get_extended_stats("foo", "2020-01-01", "2020-01-02")
        assert result == {}

    async def test_get_extended_stats_retry_failure(self):
        mock_response = _make_response(status=304, headers={})
        retry_response = _make_response(status=500, headers={})
        session = Mock()
        session.post.side_effect = [
            _make_context_manager(mock_response),
            _make_context_manager(retry_response),
        ]
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.get_extended_stats("foo", "2020-01-01", "2020-01-02")
        assert result == {}

    async def test_get_extended_stats_exception(self):
        with patch.object(self.api, "get_session", side_effect=RuntimeError("boom")):
            result = await self.api.get_extended_stats("foo", "2020-01-01", "2020-01-02")
        assert result == {}

    async def test_get_notifications_no_device(self):
        self.api.box_id = None
        result = await self.api.get_notifications()
        assert result["notifications"] == []

    async def test_get_notifications_empty_content(self):
        content = '<div class="folder-list">  </div>'
        mock_response = _make_response(status=200, text_data=content)
        session = _make_session(get_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.get_notifications("device")
        assert result["notifications"] == []

    async def test_get_notifications_success(self):
        mock_response = _make_response(status=200, text_data="ok")
        session = _make_session(get_response=mock_response)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.get_notifications("device")
        assert result["status"] == "success"

    async def test_get_notifications_auth_retry_success(self):
        response_401 = _make_response(status=401, headers={})
        response_200 = _make_response(status=200, text_data="ok")
        session1 = _make_session(get_response=response_401)
        session2 = _make_session(get_response=response_200)

        with (
            patch.object(self.api, "get_session", side_effect=[_make_session_context(session1), _make_session_context(session2)]),
            patch.object(self.api, "authenticate", return_value=True),
        ):
            result = await self.api.get_notifications("device")
        assert result["status"] == "success"

    async def test_get_notifications_auth_retry_failed(self):
        response_401 = _make_response(status=401, headers={})
        session = _make_session(get_response=response_401)
        session_ctx = _make_session_context(session)

        with (
            patch.object(self.api, "get_session", return_value=session_ctx),
            patch.object(self.api, "authenticate", return_value=False),
        ):
            result = await self.api.get_notifications("device")
        assert result["error"] == "auth_failed"

    async def test_get_notifications_http_error(self):
        response_500 = _make_response(status=500, headers={})
        session = _make_session(get_response=response_500)
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.get_notifications("device")
        assert result["error"] == "http_500"

    async def test_get_notifications_timeout(self):
        timeout_ctx = _make_context_manager_raises(asyncio.TimeoutError("boom"))
        session = Mock()
        session.get.return_value = timeout_ctx
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.get_notifications("device")
        assert result["error"] == "timeout"

    async def test_get_notifications_connection_error(self):
        conn_err = aiohttp.ClientConnectorError(Mock(), OSError("conn"))
        conn_ctx = _make_context_manager_raises(conn_err)
        session = Mock()
        session.get.return_value = conn_ctx
        session_ctx = _make_session_context(session)

        with patch.object(self.api, "get_session", return_value=session_ctx):
            result = await self.api.get_notifications("device")
        assert result["error"] == "connection"

    async def test_get_notifications_exception(self):
        with patch.object(self.api, "get_session", side_effect=RuntimeError("boom")):
            result = await self.api.get_notifications("device")
        assert result["error"] == "boom"
