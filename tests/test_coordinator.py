"""Tests for the OIG Cloud Data Update Coordinator."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from typing import Dict, Any

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.oig_cloud.api.oig_cloud_api import OigCloudApi, OigCloudApiError
from custom_components.oig_cloud.const import DEFAULT_UPDATE_INTERVAL
from custom_components.oig_cloud.coordinator import OigCloudDataUpdateCoordinator
from homeassistant.config_entries import ConfigEntry


@pytest.fixture
def mock_config_entry() -> Mock:
    """Create a mock config entry."""
    mock_entry: Mock = Mock(spec=ConfigEntry)
    # Používáme DEFAULT_UPDATE_INTERVAL místo pevné hodnoty
    mock_entry.data = {
        "update_interval": DEFAULT_UPDATE_INTERVAL,
        "inverter_sn": "test_sn_123",
        "extended_data_enabled": False,
        "extended_update_interval": 300,
    }
    mock_entry.options = {}
    return mock_entry


@pytest.fixture
def mock_hass() -> Mock:
    """Create a mock Home Assistant instance."""
    return Mock()


@pytest.fixture
def coordinator(
    mock_hass: Mock, mock_api: Mock, mock_config_entry: Mock
) -> OigCloudDataUpdateCoordinator:
    """Create a coordinator with mock dependencies."""
    return OigCloudDataUpdateCoordinator(mock_hass, mock_api, mock_config_entry)


@pytest.mark.asyncio
async def test_coordinator_initialization(
    mock_hass: Mock, mock_api: Mock, mock_config_entry: Mock
) -> None:
    """Test coordinator initialization."""
    coordinator: OigCloudDataUpdateCoordinator = OigCloudDataUpdateCoordinator(
        mock_hass, mock_api, mock_config_entry
    )

    assert coordinator.api == mock_api
    assert coordinator.name == "oig_cloud"
    assert coordinator.update_interval == timedelta(seconds=DEFAULT_UPDATE_INTERVAL)

    # Test with custom update interval
    custom_interval: timedelta = timedelta(seconds=60)
    coordinator = OigCloudDataUpdateCoordinator(
        mock_hass, mock_api, mock_config_entry, update_interval=custom_interval
    )
    assert coordinator.update_interval == custom_interval


@pytest.mark.asyncio
async def test_async_update_data_success(
    coordinator: OigCloudDataUpdateCoordinator, mock_api: Mock
) -> None:
    """Test data update success."""
    # Mock API metoda get_stats vrací data
    mock_api.get_stats.return_value = {"device1": {"box_prms": {"mode": 1}}}

    result: Dict[str, Any] = await coordinator._async_update_data()

    # Coordinator wraps data in {"basic": data}
    expected_result: Dict[str, Any] = {"basic": {"device1": {"box_prms": {"mode": 1}}}}
    assert result == expected_result
    mock_api.get_stats.assert_called_once()


@pytest.mark.asyncio
async def test_async_update_data_empty_response(
    coordinator: OigCloudDataUpdateCoordinator, mock_api: Mock
) -> None:
    """Test handling of empty data response."""
    mock_api.get_stats.return_value = None

    result: Dict[str, Any] = await coordinator._async_update_data()

    # Coordinator should handle None response gracefully
    expected_result: Dict[str, Any] = {"basic": {}}
    assert result == expected_result


@pytest.mark.asyncio
async def test_async_update_data_api_error(
    coordinator: OigCloudDataUpdateCoordinator, mock_api: Mock
) -> None:
    """Test handling of API errors."""
    mock_api.get_stats.side_effect = OigCloudApiError("API connection failed")

    with pytest.raises(
        UpdateFailed, match="Failed to fetch basic data: API connection failed"
    ):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_update_data_timeout(
    coordinator: OigCloudDataUpdateCoordinator, mock_api: Mock
) -> None:
    """Test handling of timeout errors."""
    mock_api.get_stats.side_effect = asyncio.TimeoutError()

    with pytest.raises(UpdateFailed, match="Error communicating with API"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_update_data_unexpected_error(
    coordinator: OigCloudDataUpdateCoordinator, mock_api: Mock
) -> None:
    """Test handling of unexpected errors."""
    mock_api.get_stats.side_effect = Exception("Unexpected error")

    with pytest.raises(
        UpdateFailed, match="Error communicating with API: Unexpected error"
    ):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_extended_data_enabled(mock_hass: Mock, mock_api: Mock) -> None:
    """Test coordinator with extended data enabled."""
    mock_config_entry: Mock = Mock(spec=ConfigEntry)
    mock_config_entry.data = {
        "update_interval": DEFAULT_UPDATE_INTERVAL,  # Použij DEFAULT_UPDATE_INTERVAL
        "extended_data_enabled": True,
        "extended_update_interval": 300,
    }
    mock_config_entry.options = {}

    coordinator: OigCloudDataUpdateCoordinator = OigCloudDataUpdateCoordinator(
        mock_hass, mock_api, mock_config_entry
    )

    # Mock API responses
    mock_api.get_stats.return_value = {"device1": {"box_prms": {"mode": 1}}}
    mock_api.get_extended_stats.return_value = {"daily": {"energy": 100}}

    # Patch datetime to control time
    with patch("custom_components.oig_cloud.coordinator.datetime") as mock_datetime:
        mock_datetime.now.return_value.strftime.side_effect = lambda fmt: (
            "2024-01-01" if fmt == "%Y-%m-%d" else "2024-01-01"
        )
        mock_datetime.now.return_value.replace.return_value.strftime.return_value = (
            "2024-01-01"
        )

        result: Dict[str, Any] = await coordinator._async_update_data()

    # Should include both basic and extended data
    assert "basic" in result
    assert "extended" in result
    mock_api.get_stats.assert_called_once()
    # get_extended_stats should be called twice (daily and monthly)
    assert mock_api.get_extended_stats.call_count == 2


@pytest.mark.asyncio
async def test_fetch_basic_data_success(
    coordinator: OigCloudDataUpdateCoordinator, mock_api: Mock
) -> None:
    """Test _fetch_basic_data method success."""
    mock_api.get_stats.return_value = {"device1": {"box_prms": {"mode": 1}}}

    result: Dict[str, Any] = await coordinator._fetch_basic_data()

    expected_result: Dict[str, Any] = {"basic": {"device1": {"box_prms": {"mode": 1}}}}
    assert result == expected_result


@pytest.mark.asyncio
async def test_fetch_basic_data_none_response(
    coordinator: OigCloudDataUpdateCoordinator, mock_api: Mock
) -> None:
    """Test _fetch_basic_data method with None response."""
    mock_api.get_stats.return_value = None

    result: Dict[str, Any] = await coordinator._fetch_basic_data()

    expected_result: Dict[str, Any] = {"basic": {}}
    assert result == expected_result
