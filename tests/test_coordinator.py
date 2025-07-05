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
def mock_config_entry():
    """Create a mock config entry."""
    mock_entry = Mock(spec=ConfigEntry)
    # Přidáme potřebné atributy
    mock_entry.data = {"refresh_interval": 30, "inverter_sn": "test_sn_123"}
    mock_entry.options = {}
    return mock_entry


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return Mock()


@pytest.fixture
def coordinator(mock_hass, mock_api, mock_config_entry):
    """Create a coordinator with mock dependencies."""
    # Přidáme metody které koordinátor očekává přímo do tohoto testu
    mock_api.get_basic_data = AsyncMock(
        return_value={"device1": {"box_prms": {"mode": 1}}}
    )
    mock_api.get_extended_data = AsyncMock(return_value={})

    return OigCloudDataUpdateCoordinator(mock_hass, mock_api, mock_config_entry)


@pytest.mark.asyncio
async def test_coordinator_initialization(mock_hass, mock_api, mock_config_entry):
    """Test coordinator initialization."""
    # Přidáme metody i pro tento test
    mock_api.get_basic_data = AsyncMock(
        return_value={"device1": {"box_prms": {"mode": 1}}}
    )
    mock_api.get_extended_data = AsyncMock(return_value={})

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
async def test_async_update_data_success(
    coordinator: OigCloudDataUpdateCoordinator, mock_api: Mock
) -> None:
    """Test data update success."""
    # Test již má potřebné metody z coordinator fixture
    result = await coordinator._async_update_data()

    # Coordinator wraps data in {"basic": data}
    expected_result = {"basic": {"device1": {"box_prms": {"mode": 1}}}}
    assert result == expected_result
    mock_api.get_basic_data.assert_called_once()


@pytest.mark.asyncio
async def test_async_update_data_empty_response(
    coordinator: OigCloudDataUpdateCoordinator, mock_api: Mock
) -> None:
    """Test handling of empty data response."""
    mock_api.get_basic_data.return_value = None

    with pytest.raises(UpdateFailed, match="Failed to fetch basic data"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_update_data_api_error(
    coordinator: OigCloudDataUpdateCoordinator, mock_api: Mock
) -> None:
    """Test handling of API errors."""
    mock_api.get_basic_data.side_effect = OigCloudApiError("API connection failed")

    with pytest.raises(
        UpdateFailed, match="Failed to fetch basic data: API connection failed"
    ):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_update_data_timeout(
    coordinator: OigCloudDataUpdateCoordinator, mock_api: Mock
) -> None:
    """Test handling of timeout errors."""
    mock_api.get_basic_data.side_effect = asyncio.TimeoutError()

    with pytest.raises(UpdateFailed, match="Error communicating with API"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_update_data_unexpected_error(
    coordinator: OigCloudDataUpdateCoordinator, mock_api: Mock
) -> None:
    """Test handling of unexpected errors."""
    mock_api.get_basic_data.side_effect = Exception("Unexpected error")

    with pytest.raises(
        UpdateFailed, match="Error communicating with API: Unexpected error"
    ):
        await coordinator._async_update_data()
