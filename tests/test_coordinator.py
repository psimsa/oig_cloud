"""Tests for the OIG Cloud Data Update Coordinator."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.oig_cloud.api.oig_cloud_api import OigCloudApi, OigCloudApiError
from custom_components.oig_cloud.const import DEFAULT_UPDATE_INTERVAL
from custom_components.oig_cloud.coordinator import OigCloudDataUpdateCoordinator
from homeassistant.config_entries import ConfigEntry


@pytest.fixture
def mock_api():
    """Create a mock OIG Cloud API."""
    api = Mock(spec=OigCloudApi)
    api.get_data = AsyncMock()
    return api

@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return Mock(spec=ConfigEntry)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return Mock()


@pytest.fixture
def coordinator(mock_hass, mock_api, mock_config_entry):
    """Create a coordinator with mock dependencies."""
    return OigCloudDataUpdateCoordinator(mock_hass, mock_api, mock_config_entry)


@pytest.mark.asyncio
async def test_coordinator_initialization(mock_hass, mock_api, mock_config_entry):
    """Test coordinator initialization."""
    coordinator = OigCloudDataUpdateCoordinator(mock_hass, mock_api, mock_config_entry)
    
    assert coordinator.api == mock_api
    assert coordinator.name == "oig_cloud"
    assert coordinator.update_interval == timedelta(seconds=DEFAULT_UPDATE_INTERVAL)
    
    # Test with custom update interval
    custom_interval = timedelta(seconds=60)
    coordinator = OigCloudDataUpdateCoordinator(
        mock_hass, mock_api, mock_config_entry, update_interval=custom_interval
    )
    assert coordinator.update_interval == custom_interval


@pytest.mark.asyncio
async def test_async_update_data_success(coordinator, mock_api):
    """Test data update success."""
    mock_data = {"device1": {"box_prms": {"mode": 1}}}
    mock_api.get_data.return_value = mock_data
    
    result = await coordinator._async_update_data()
    
    mock_api.get_data.assert_called_once()
    assert result == mock_data


@pytest.mark.asyncio
async def test_async_update_data_empty_response(coordinator, mock_api):
    """Test handling of empty data response."""
    mock_api.get_data.return_value = None
    
    with pytest.raises(UpdateFailed, match="No data received from OIG Cloud API"):
        await coordinator._async_update_data()
    
    mock_api.get_data.assert_called_once()


@pytest.mark.asyncio
async def test_async_update_data_api_error(coordinator, mock_api):
    """Test handling of API errors."""
    mock_api.get_data.side_effect = OigCloudApiError("API connection failed")
    
    with pytest.raises(UpdateFailed, match="Error fetching OIG Cloud data: API connection failed"):
        await coordinator._async_update_data()
    
    mock_api.get_data.assert_called_once()


@pytest.mark.asyncio
async def test_async_update_data_timeout(coordinator, mock_api):
    """Test handling of timeout errors."""
    mock_api.get_data.side_effect = asyncio.TimeoutError()
    
    with pytest.raises(UpdateFailed, match="Timeout error fetching OIG Cloud data"):
        await coordinator._async_update_data()
    
    mock_api.get_data.assert_called_once()


@pytest.mark.asyncio
async def test_async_update_data_unexpected_error(coordinator, mock_api):
    """Test handling of unexpected errors."""
    mock_api.get_data.side_effect = Exception("Unexpected error")
    
    with pytest.raises(UpdateFailed, match="Unexpected error fetching OIG Cloud data: Unexpected error"):
        await coordinator._async_update_data()
    
    mock_api.get_data.assert_called_once()
