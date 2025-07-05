import pytest
from unittest.mock import Mock, AsyncMock


@pytest.fixture
def mock_api() -> Mock:
    """Create a mock API instance."""
    api = Mock()  # Bez spec omezení

    # Mock pouze skutečné metody z OigCloudApi
    api.get_stats = AsyncMock(return_value={"device1": {"box_prms": {"mode": 1}}})
    api.get_extended_stats = AsyncMock(return_value={})
    api.get_notifications = AsyncMock(return_value={"status": "success", "content": ""})
    api.authenticate = AsyncMock(return_value=True)
    api.get_session = Mock(return_value=Mock())
    api.set_box_params_internal = AsyncMock(return_value=True)

    return api
