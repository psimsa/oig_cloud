"""Tests for the OIG Cloud API client."""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api import (
    OigCloudApi,
    OigCloudApiError,
    OigCloudAuthError,
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


@pytest.mark.asyncio
class TestOigCloudApi:
    """Test the OIG Cloud API client."""

    def setup_method(self):
        """Set up test fixtures."""
        self.api = OigCloudApi("username", "password", False, None)

        # Sample API response data
        with open("tests/sample-response.json", "r") as f:
            self.sample_data = json.load(f)

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
    async def test_get_session_not_authenticated(self, mock_session):
        """Test get_session when not authenticated."""
        self.api._phpsessid = None

        with pytest.raises(OigCloudAuthError):
            self.api.get_session()

        mock_session.assert_not_called()

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
