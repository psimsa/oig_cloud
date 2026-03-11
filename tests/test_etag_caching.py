"""Tests for ETag caching functionality."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientResponse

from custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api import \
    OigCloudApi


@pytest.fixture
def api_client() -> OigCloudApi:
    """Create API client instance."""
    return OigCloudApi(
        username="test@example.com",
        password="testpass",
        no_telemetry=False,
        timeout=30,
    )


@pytest.fixture
def mock_response():
    """Create mock aiohttp response."""
    response = MagicMock(spec=ClientResponse)
    response.headers = {}
    return response


class TestETagCaching:
    """Test ETag caching functionality."""

    @pytest.mark.asyncio
    async def test_first_request_without_etag(self, api_client, mock_response):
        """Test first request - no ETag sent, data cached."""
        test_data = {"box1": {"power": 100}}

        mock_response.status = 200
        mock_response.headers = {"ETag": '"v1"'}
        mock_response.json = AsyncMock(return_value=test_data)

        with patch.object(api_client, "get_session") as mock_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
            mock_ctx.__aexit__ = AsyncMock()

            mock_get = MagicMock(return_value=mock_ctx)
            mock_session_obj = MagicMock()
            mock_session_obj.get = mock_get
            mock_session_obj.__aenter__ = AsyncMock(return_value=mock_session_obj)
            mock_session_obj.__aexit__ = AsyncMock()

            mock_session.return_value = mock_session_obj

            # First request
            result = await api_client._try_get_stats()

            # Verify data returned
            assert result == test_data

            # Verify ETag cached
            cached = api_client._cache.get("json.php")
            assert cached is not None
            assert cached["etag"] == '"v1"'
            assert cached["data"] == test_data

            # Verify no If-None-Match sent on first request
            call_kwargs = mock_get.call_args[1]
            headers = call_kwargs.get("headers", {})
            assert "If-None-Match" not in headers

    @pytest.mark.asyncio
    async def test_second_request_with_304(self, api_client, mock_response):
        """Test second request - If-None-Match sent, 304 returned, cache used."""
        test_data = {"box1": {"power": 100}}

        # Pre-populate cache
        api_client._cache["json.php"] = {
            "etag": '"v1"',
            "data": test_data,
            "ts": time.time(),
        }

        # Mock 304 response
        mock_response.status = 304
        mock_response.headers = {"ETag": '"v1"'}

        with patch.object(api_client, "get_session") as mock_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
            mock_ctx.__aexit__ = AsyncMock()

            mock_get = MagicMock(return_value=mock_ctx)
            mock_session_obj = MagicMock()
            mock_session_obj.get = mock_get
            mock_session_obj.__aenter__ = AsyncMock(return_value=mock_session_obj)
            mock_session_obj.__aexit__ = AsyncMock()

            mock_session.return_value = mock_session_obj

            # Second request
            result = await api_client._try_get_stats()

            # Verify cached data returned
            assert result == test_data

            # Verify If-None-Match was sent
            call_kwargs = mock_get.call_args[1]
            headers = call_kwargs.get("headers", {})
            assert headers.get("If-None-Match") == '"v1"'

    @pytest.mark.asyncio
    async def test_etag_change_updates_cache(self, api_client, mock_response):
        """Test ETag change - new data replaces cache."""
        old_data = {"box1": {"power": 100}}
        new_data = {"box1": {"power": 200}}

        # Pre-populate cache with old ETag
        api_client._cache["json.php"] = {
            "etag": '"v1"',
            "data": old_data,
            "ts": time.time(),
        }

        # Mock 200 response with new ETag
        mock_response.status = 200
        mock_response.headers = {"ETag": '"v2"'}
        mock_response.json = AsyncMock(return_value=new_data)

        with patch.object(api_client, "get_session") as mock_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
            mock_ctx.__aexit__ = AsyncMock()

            mock_get = MagicMock(return_value=mock_ctx)
            mock_session_obj = MagicMock()
            mock_session_obj.get = mock_get
            mock_session_obj.__aenter__ = AsyncMock(return_value=mock_session_obj)
            mock_session_obj.__aexit__ = AsyncMock()

            mock_session.return_value = mock_session_obj

            # Request with changed data
            result = await api_client._try_get_stats()

            # Verify new data returned
            assert result == new_data

            # Verify cache updated with new ETag
            cached = api_client._cache.get("json.php")
            assert cached is not None
            assert cached["etag"] == '"v2"'
            assert cached["data"] == new_data

    @pytest.mark.asyncio
    async def test_no_etag_support(self, api_client, mock_response):
        """Test server without ETag support - works normally."""
        test_data = {"box1": {"power": 100}}

        # Mock response without ETag
        mock_response.status = 200
        mock_response.headers = {}  # No ETag header
        mock_response.json = AsyncMock(return_value=test_data)

        with patch.object(api_client, "get_session") as mock_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
            mock_ctx.__aexit__ = AsyncMock()

            mock_get = MagicMock(return_value=mock_ctx)
            mock_session_obj = MagicMock()
            mock_session_obj.get = mock_get
            mock_session_obj.__aenter__ = AsyncMock(return_value=mock_session_obj)
            mock_session_obj.__aexit__ = AsyncMock()

            mock_session.return_value = mock_session_obj

            # Request
            result = await api_client._try_get_stats()

            # Verify data returned
            assert result == test_data

            # Verify cache has no ETag but has data
            cached = api_client._cache.get("json.php")
            assert cached is not None
            assert cached["etag"] is None
            assert cached["data"] == test_data

            # Second request should not send If-None-Match
            await api_client._try_get_stats()
            call_kwargs = mock_get.call_args[1]
            headers = call_kwargs.get("headers", {})
            assert "If-None-Match" not in headers

    @pytest.mark.asyncio
    async def test_extended_stats_etag(self, api_client, mock_response):
        """Test ETag caching for extended stats (per-name)."""
        test_data = {"daily": [1, 2, 3]}

        mock_response.status = 200
        mock_response.headers = {"ETag": '"daily-v1"'}
        mock_response.json = AsyncMock(return_value=test_data)

        with patch.object(api_client, "get_session") as mock_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
            mock_ctx.__aexit__ = AsyncMock()

            mock_post = MagicMock(return_value=mock_ctx)
            mock_session_obj = MagicMock()
            mock_session_obj.post = mock_post
            mock_session_obj.__aenter__ = AsyncMock(return_value=mock_session_obj)
            mock_session_obj.__aexit__ = AsyncMock()

            mock_session.return_value = mock_session_obj

            # First request
            result = await api_client.get_extended_stats(
                "daily", "2025-01-01", "2025-01-02"
            )

            # Verify data returned
            assert result == test_data

            # Verify ETag cached per-name
            cached = api_client._cache.get("json2.php:daily")
            assert cached is not None
            assert cached["etag"] == '"daily-v1"'
            assert cached["data"] == test_data


class TestJitter:
    """Test jitter functionality in coordinator."""

    def test_jitter_range(self):
        """Test jitter is within expected range."""
        from custom_components.oig_cloud.core.coordinator import (
            JITTER_SECONDS, OigCloudCoordinator)

        with patch(
            "custom_components.oig_cloud.core.coordinator.DataUpdateCoordinator.__init__"
        ):
            api = MagicMock()
            hass = MagicMock()

            coordinator = OigCloudCoordinator(hass, api, config_entry=None)

            with patch(
                "custom_components.oig_cloud.core.coordinator.random.uniform",
                return_value=3.2,
            ) as mocked:
                jitter = coordinator._calculate_jitter()
                mocked.assert_called_once_with(-JITTER_SECONDS, JITTER_SECONDS)
                assert jitter == 3.2
                assert coordinator._next_jitter == 3.2

    def test_jitter_stored(self):
        """Test jitter value is stored in coordinator."""
        from custom_components.oig_cloud.core.coordinator import \
            OigCloudCoordinator

        with patch(
            "custom_components.oig_cloud.core.coordinator.DataUpdateCoordinator.__init__"
        ):
            api = MagicMock()
            hass = MagicMock()

            coordinator = OigCloudCoordinator(hass, api, config_entry=None)

            jitter = coordinator._calculate_jitter()
            assert coordinator._next_jitter == jitter
