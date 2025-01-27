import unittest
from unittest.mock import patch, AsyncMock
from custom_components.oig_cloud.api.oig_cloud_api import OigCloudApi

class TestOigCloudApi(unittest.TestCase):
    def setUp(self):
        self.api = OigCloudApi("username", "password", False, None)

    @patch("custom_components.oig_cloud.api.oig_cloud_api.aiohttp.ClientSession")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.datetime")
    @patch("custom_components.oig_cloud.api.oig_cloud_api.tracer")
    async def test_get_stats(self, mock_tracer, mock_datetime, mock_session):
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
        mock_datetime.datetime.now.return_value = mock_datetime.datetime(2025, 1, 27, 8, 34, 57)
        self.api._last_update = mock_datetime.datetime(2025, 1, 27, 8, 34, 30)
        self.api.last_state = {"cached_key": "cached_value"}

        result = await self.api.get_stats()
        self.assertEqual(result, {"cached_key": "cached_value"})

if __name__ == "__main__":
    unittest.main()
