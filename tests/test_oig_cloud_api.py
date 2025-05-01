"""Tests for the OIG Cloud API client."""
import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import aiohttp
import pytest
from aiohttp import ClientResponseError

from custom_components.oig_cloud.api.oig_cloud_api import (
    OigCloudApi,
    OigCloudApiError,
    OigCloudAuthError,
)


class TestOigCloudApi(unittest.TestCase):
    """Test the OIG Cloud API client."""

    def setUp(self):
        """Set up test fixtures."""
        self.api = OigCloudApi("username", "password", False, None)
        
        # Sample API response data
        with open("tests/sample-response.json", "r") as f:
            self.sample_data = json.load(f)
        
    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.datetime")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats(self, mock_tracer, mock_datetime, mock_session):
        """Test getting stats from API."""
        mock_datetime.datetime.now.return_value = mock_datetime.datetime(2025, 1, 27, 8, 34, 57)
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"key": "value"}
        mock_session.return_value.__aenter__.return_value.get.return_value = mock_response

        result = await self.api.get_stats()
        self.assertEqual(result, {"key": "value"})
        self.assertEqual(self.api.last_state, {"key": "value"})
        self.assertEqual(self.api.box_id, "key")

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.datetime")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats_cache(self, mock_tracer, mock_datetime, mock_session):
        """Test caching behavior for stats."""
        mock_datetime.datetime.now.return_value = mock_datetime.datetime(2025, 1, 27, 8, 34, 57)
        self.api._last_update = mock_datetime.datetime(2025, 1, 27, 8, 34, 30)
        self.api.last_state = {"cached_key": "cached_value"}

        result = await self.api.get_stats()
        self.assertEqual(result, {"cached_key": "cached_value"})
        
        # Verify the session was not created (no API call made)
        mock_session.assert_not_called()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_authenticate_success(self, mock_tracer, mock_session):
        """Test successful authentication."""
        # Configure mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '[[2,"",false]]'
        
        # Setup cookie
        mock_cookie = Mock()
        mock_cookie.value = "test_session_id"
        mock_cookie_jar = Mock()
        mock_cookie_jar.filter_cookies.return_value = {"PHPSESSID": mock_cookie}
        
        # Configure session
        mock_session.return_value.__aenter__.return_value.post.return_value = mock_response
        mock_session.return_value.__aenter__.return_value.cookie_jar = mock_cookie_jar
        
        result = await self.api.authenticate()
        self.assertTrue(result)
        self.assertEqual(self.api._phpsessid, "test_session_id")
        mock_session.return_value.__aenter__.return_value.post.assert_called_once()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_authenticate_failure_wrong_response(self, mock_tracer, mock_session):
        """Test authentication failure with wrong response."""
        # Configure mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '{"error": "Invalid credentials"}'
        
        # Configure session
        mock_session.return_value.__aenter__.return_value.post.return_value = mock_response
        
        with self.assertRaises(OigCloudAuthError):
            await self.api.authenticate()
            
        mock_session.return_value.__aenter__.return_value.post.assert_called_once()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_authenticate_failure_http_error(self, mock_tracer, mock_session):
        """Test authentication failure with HTTP error."""
        # Configure mock response
        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.text.return_value = 'Unauthorized'
        
        # Configure session
        mock_session.return_value.__aenter__.return_value.post.return_value = mock_response
        
        with self.assertRaises(OigCloudAuthError):
            await self.api.authenticate()
            
        mock_session.return_value.__aenter__.return_value.post.assert_called_once()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_session_not_authenticated(self, mock_tracer, mock_session):
        """Test get_session when not authenticated."""
        self.api._phpsessid = None
        
        with self.assertRaises(OigCloudAuthError):
            self.api.get_session()
            
        mock_session.assert_not_called()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats_internal_auth_retry(self, mock_tracer, mock_session):
        """Test get_stats_internal with authentication retry."""
        self.api._phpsessid = "test_session_id"
        
        # First response fails
        mock_response1 = AsyncMock()
        mock_response1.status = 200
        mock_response1.json.return_value = "Not a dict"
        
        # Second response succeeds
        mock_response2 = AsyncMock()
        mock_response2.status = 200
        mock_response2.json.return_value = {"key": "value"}
        
        # Configure first session response
        mock_session_instance1 = AsyncMock()
        mock_session_instance1.get.return_value = mock_response1
        
        # Configure second session response
        mock_session_instance2 = AsyncMock()
        mock_session_instance2.get.return_value = mock_response2
        
        mock_session.return_value.__aenter__.side_effect = [mock_session_instance1, mock_session_instance2]
        
        # Mock authenticate to return True
        with patch.object(self.api, "authenticate", return_value=True) as mock_auth:
            result = await self.api.get_stats_internal()
            self.assertEqual(result, {"key": "value"})
            self.assertEqual(self.api.last_state, {"key": "value"})
            mock_auth.assert_called_once()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_box_mode(self, mock_tracer):
        """Test setting box mode."""
        # Mock the internal method
        with patch.object(self.api, "set_box_params_internal", return_value=True) as mock_set_params:
            result = await self.api.set_box_mode("1")
            self.assertTrue(result)
            mock_set_params.assert_called_once_with("box_prms", "mode", "1")

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_grid_delivery_limit(self, mock_tracer):
        """Test setting grid delivery limit."""
        # Mock the internal method
        with patch.object(self.api, "set_box_params_internal", return_value=True) as mock_set_params:
            result = await self.api.set_grid_delivery_limit(5000)
            self.assertTrue(result)
            mock_set_params.assert_called_once_with("invertor_prm1", "p_max_feed_grid", 5000)

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_boiler_mode(self, mock_tracer):
        """Test setting boiler mode."""
        # Mock the internal method
        with patch.object(self.api, "set_box_params_internal", return_value=True) as mock_set_params:
            result = await self.api.set_boiler_mode("1")
            self.assertTrue(result)
            mock_set_params.assert_called_once_with("boiler_prms", "manual", "1")

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.time")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_box_params_internal(self, mock_tracer, mock_time, mock_session):
        """Test setting box parameters."""
        self.api._phpsessid = "test_session_id"
        self.api.box_id = "test_box_id"
        mock_time.time.return_value = 1711698897.123
        nonce = int(1711698897.123 * 1000)
        
        # Configure mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '[[0,2,"OK"]]'
        
        # Configure session
        mock_session.return_value.__aenter__.return_value.post.return_value = mock_response
        
        result = await self.api.set_box_params_internal("table", "column", "value")
        self.assertTrue(result)
        
        expected_url = f"https://www.oigpower.cz/cez/inc/php/scripts/Device.Set.Value.php?_nonce={nonce}"
        expected_data = json.dumps({
            "id_device": "test_box_id",
            "table": "table",
            "column": "column",
            "value": "value",
        })
        
        mock_session.return_value.__aenter__.return_value.post.assert_called_once_with(
            expected_url,
            data=expected_data,
            headers={"Content-Type": "application/json"},
        )

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_box_params_internal_no_box_id(self, mock_tracer):
        """Test setting box parameters without box ID."""
        self.api.box_id = None
        
        with self.assertRaises(OigCloudApiError):
            await self.api.set_box_params_internal("table", "column", "value")

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.time")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_box_params_internal_failure(self, mock_tracer, mock_time, mock_session):
        """Test setting box parameters failure."""
        self.api._phpsessid = "test_session_id"
        self.api.box_id = "test_box_id"
        mock_time.time.return_value = 1711698897.123
        
        # Configure mock response
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text.return_value = 'Bad Request'
        
        # Configure session
        mock_session.return_value.__aenter__.return_value.post.return_value = mock_response
        
        with self.assertRaises(OigCloudApiError):
            await self.api.set_box_params_internal("table", "column", "value")

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.time")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_grid_delivery(self, mock_tracer, mock_time, mock_session):
        """Test setting grid delivery mode."""
        self.api._phpsessid = "test_session_id"
        self.api.box_id = "test_box_id"
        mock_time.time.return_value = 1711698897.123
        nonce = int(1711698897.123 * 1000)
        
        # Configure mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '[[0,2,"OK"]]'
        
        # Configure session
        mock_session.return_value.__aenter__.return_value.post.return_value = mock_response
        
        result = await self.api.set_grid_delivery(1)
        self.assertTrue(result)
        
        expected_url = f"https://www.oigpower.cz/cez/inc/php/scripts/ToGrid.Toggle.php?_nonce={nonce}"
        expected_data = json.dumps({
            "id_device": "test_box_id",
            "value": 1,
        })
        
        mock_session.return_value.__aenter__.return_value.post.assert_called_once_with(
            expected_url,
            data=expected_data,
            headers={"Content-Type": "application/json"},
        )

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_grid_delivery_no_telemetry(self, mock_tracer):
        """Test setting grid delivery with no telemetry."""
        self.api._no_telemetry = True
        
        with self.assertRaises(OigCloudApiError):
            await self.api.set_grid_delivery(1)

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.time")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_set_formating_mode(self, mock_tracer, mock_time, mock_session):
        """Test setting battery formatting mode."""
        self.api._phpsessid = "test_session_id"
        mock_time.time.return_value = 1711698897.123
        nonce = int(1711698897.123 * 1000)
        
        # Configure mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = '[[0,2,"OK"]]'
        
        # Configure session
        mock_session.return_value.__aenter__.return_value.post.return_value = mock_response
        
        result = await self.api.set_formating_mode("1")
        self.assertTrue(result)
        
        expected_url = f"https://www.oigpower.cz/cez/inc/php/scripts/Battery.Format.Save.php?_nonce={nonce}"
        expected_data = json.dumps({
            "bat_ac": "1",
        })
        
        mock_session.return_value.__aenter__.return_value.post.assert_called_once_with(
            expected_url,
            data=expected_data,
            headers={"Content-Type": "application/json"},
        )

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_data(self, mock_tracer):
        """Test get_data method."""
        # Mock the get_stats method
        with patch.object(self.api, "get_stats", return_value=self.sample_data) as mock_get_stats:
            result = await self.api.get_data()
            self.assertEqual(result, self.sample_data)
            mock_get_stats.assert_called_once()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_typed_data(self, mock_tracer):
        """Test get_typed_data method."""
        # Mock the get_stats method
        with patch.object(self.api, "get_stats", return_value=self.sample_data) as mock_get_stats:
            result = await self.api.get_typed_data()
            self.assertIsNotNone(result)
            self.assertEqual(len(result.devices), len(self.sample_data))
            mock_get_stats.assert_called_once()

    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_typed_data_empty(self, mock_tracer):
        """Test get_typed_data method with empty data."""
        # Mock the get_stats method
        with patch.object(self.api, "get_stats", return_value=None) as mock_get_stats:
            result = await self.api.get_typed_data()
            self.assertIsNone(result)
            mock_get_stats.assert_called_once()


if __name__ == "__main__":
    unittest.main()
