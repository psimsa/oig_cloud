import pytest
from unittest.mock import Mock, AsyncMock


@pytest.fixture
def mock_api() -> Mock:
    """Create a mock API instance."""
    api = Mock()  # Odstranili jsme spec=OigCloudApi

    # Mock existující metody z OigCloudApi
    api.get_stats = AsyncMock(return_value={"device1": {"box_prms": {"mode": 1}}})
    api.get_extended_stats = AsyncMock(return_value={})
    api.get_notifications = AsyncMock(return_value={"status": "success", "content": ""})
    api.authenticate = AsyncMock(return_value=True)
    api.get_session = Mock(return_value=Mock())
    api.set_box_params_internal = AsyncMock(return_value=True)

    # Alias metody pro kompatibilitu s koordinátorem
    api.get_data = api.get_stats  # Alias pro get_stats
    api.get_basic_data = api.get_stats  # Alias pro get_stats
    api.get_extended_data = api.get_extended_stats  # Alias pro get_extended_stats

    return api
