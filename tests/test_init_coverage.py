"""Tests for custom_components/oig_cloud/__init__.py to improve coverage."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.oig_cloud import (
    ALL_BOX_MODES,
    PLATFORMS,
    async_reload_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.oig_cloud.api.oig_cloud_api import OigCloudApiError, OigCloudAuthError
from custom_components.oig_cloud.const import DOMAIN


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=None)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {
        "username": "test@example.com",
        "password": "secret",
        "no_telemetry": True,
        "update_interval": 120,
        "log_level": "DEBUG",
    }
    entry.options = {}
    entry.add_update_listener = MagicMock(return_value=lambda: None)
    entry.async_on_unload = MagicMock()
    return entry


class TestAsyncSetup:
    async def test_async_setup_creates_domain_key(self, mock_hass):
        mock_hass.data = {}
        result = await async_setup(mock_hass, {})
        assert result is True
        assert DOMAIN in mock_hass.data

    async def test_async_setup_existing_domain_key(self, mock_hass):
        mock_hass.data = {DOMAIN: {"existing": "data"}}
        result = await async_setup(mock_hass, {})
        assert result is True


class TestAsyncSetupEntry:
    @patch("custom_components.oig_cloud.async_setup_entry_services")
    @patch("custom_components.oig_cloud.OigCloudDataUpdateCoordinator")
    @patch("custom_components.oig_cloud.OigCloudApi")
    @patch("custom_components.oig_cloud.asyncio.get_running_loop")
    async def test_async_setup_entry_success_no_telemetry(
        self, mock_get_loop, mock_api_cls, mock_coordinator_cls, mock_setup_services, mock_hass, mock_entry
    ):
        mock_api = MagicMock()
        mock_api.authenticate = AsyncMock(return_value=True)
        mock_api_cls.return_value = mock_api

        mock_coordinator = MagicMock()
        mock_coordinator.last_update_success = True
        mock_coordinator.async_config_entry_first_refresh = AsyncMock(return_value=None)
        mock_coordinator_cls.return_value = mock_coordinator

        mock_loop = MagicMock()
        mock_future = asyncio.Future()
        mock_future.set_result(None)
        mock_loop.run_in_executor = MagicMock(return_value=mock_future)
        mock_get_loop.return_value = mock_loop

        result = await async_setup_entry(mock_hass, mock_entry)

        assert result is True
        mock_api.authenticate.assert_awaited_once()
        mock_coordinator.async_config_entry_first_refresh.assert_awaited_once()
        mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            mock_entry, PLATFORMS
        )
        mock_setup_services.assert_awaited_once_with(mock_hass, mock_entry)
        mock_entry.async_on_unload.assert_called_once()

    @patch("custom_components.oig_cloud.async_setup_entry_services")
    @patch("custom_components.oig_cloud.OigCloudDataUpdateCoordinator")
    @patch("custom_components.oig_cloud.OigCloudApi")
    @patch("custom_components.oig_cloud.asyncio.get_running_loop")
    async def test_async_setup_entry_success_with_telemetry(
        self, mock_get_loop, mock_api_cls, mock_coordinator_cls, mock_setup_services, mock_hass, mock_entry
    ):
        mock_entry.data["no_telemetry"] = False
        mock_entry.options = {}
        mock_hass.data["core.uuid"] = "test-uuid"

        mock_api = MagicMock()
        mock_api.authenticate = AsyncMock(return_value=True)
        mock_api_cls.return_value = mock_api

        mock_coordinator = MagicMock()
        mock_coordinator.last_update_success = True
        mock_coordinator.async_config_entry_first_refresh = AsyncMock(return_value=None)
        mock_coordinator_cls.return_value = mock_coordinator

        mock_loop = MagicMock()
        mock_future = asyncio.Future()
        mock_future.set_result(None)
        mock_loop.run_in_executor = MagicMock(return_value=mock_future)
        mock_get_loop.return_value = mock_loop

        result = await async_setup_entry(mock_hass, mock_entry)
        assert result is True

    @patch("custom_components.oig_cloud.async_setup_entry_services")
    @patch("custom_components.oig_cloud.OigCloudDataUpdateCoordinator")
    @patch("custom_components.oig_cloud.OigCloudApi")
    @patch("custom_components.oig_cloud.asyncio.get_running_loop")
    async def test_async_setup_entry_options_override(
        self, mock_get_loop, mock_api_cls, mock_coordinator_cls, mock_setup_services, mock_hass, mock_entry
    ):
        mock_entry.options = {
            "no_telemetry": True,
            "update_interval": 300,
            "log_level": "WARNING",
        }

        mock_api = MagicMock()
        mock_api.authenticate = AsyncMock(return_value=True)
        mock_api_cls.return_value = mock_api

        mock_coordinator = MagicMock()
        mock_coordinator.last_update_success = True
        mock_coordinator.async_config_entry_first_refresh = AsyncMock(return_value=None)
        mock_coordinator_cls.return_value = mock_coordinator

        mock_loop = MagicMock()
        mock_future = asyncio.Future()
        mock_future.set_result(None)
        mock_loop.run_in_executor = MagicMock(return_value=mock_future)
        mock_get_loop.return_value = mock_loop

        result = await async_setup_entry(mock_hass, mock_entry)
        assert result is True
        call_kwargs = mock_coordinator_cls.call_args.kwargs
        assert call_kwargs["update_interval"] == timedelta(seconds=300)

    @patch("custom_components.oig_cloud.OigCloudApi")
    async def test_async_setup_entry_auth_error(self, mock_api_cls, mock_hass, mock_entry):
        mock_api = MagicMock()
        mock_api.authenticate = AsyncMock(side_effect=OigCloudAuthError("bad creds"))
        mock_api_cls.return_value = mock_api

        with pytest.raises(ConfigEntryNotReady, match="Authentication failed"):
            await async_setup_entry(mock_hass, mock_entry)

    @patch("custom_components.oig_cloud.OigCloudApi")
    async def test_async_setup_entry_auth_unexpected_error(self, mock_api_cls, mock_hass, mock_entry):
        mock_api = MagicMock()
        mock_api.authenticate = AsyncMock(side_effect=RuntimeError("boom"))
        mock_api_cls.return_value = mock_api

        with pytest.raises(ConfigEntryNotReady, match="Unexpected error"):
            await async_setup_entry(mock_hass, mock_entry)

    @patch("custom_components.oig_cloud.async_setup_entry_services")
    @patch("custom_components.oig_cloud.OigCloudDataUpdateCoordinator")
    @patch("custom_components.oig_cloud.OigCloudApi")
    @patch("custom_components.oig_cloud.asyncio.get_running_loop")
    async def test_async_setup_entry_first_refresh_fails(
        self, mock_get_loop, mock_api_cls, mock_coordinator_cls, mock_setup_services, mock_hass, mock_entry
    ):
        mock_api = MagicMock()
        mock_api.authenticate = AsyncMock(return_value=True)
        mock_api_cls.return_value = mock_api

        mock_coordinator = MagicMock()
        mock_coordinator.last_update_success = False
        mock_coordinator.async_config_entry_first_refresh = AsyncMock(return_value=None)
        mock_coordinator_cls.return_value = mock_coordinator

        mock_loop = MagicMock()
        mock_future = asyncio.Future()
        mock_future.set_result(None)
        mock_loop.run_in_executor = MagicMock(return_value=mock_future)
        mock_get_loop.return_value = mock_loop

        with pytest.raises(ConfigEntryNotReady, match="Initial data fetch failed"):
            await async_setup_entry(mock_hass, mock_entry)

    @patch("custom_components.oig_cloud.async_setup_entry_services")
    @patch("custom_components.oig_cloud.OigCloudDataUpdateCoordinator")
    @patch("custom_components.oig_cloud.OigCloudApi")
    @patch("custom_components.oig_cloud.asyncio.get_running_loop")
    async def test_async_setup_entry_api_error(
        self, mock_get_loop, mock_api_cls, mock_coordinator_cls, mock_setup_services, mock_hass, mock_entry
    ):
        mock_api = MagicMock()
        mock_api.authenticate = AsyncMock(side_effect=OigCloudApiError("api down"))
        mock_api_cls.return_value = mock_api

        mock_loop = MagicMock()
        mock_future = asyncio.Future()
        mock_future.set_result(None)
        mock_loop.run_in_executor = MagicMock(return_value=mock_future)
        mock_get_loop.return_value = mock_loop

        with pytest.raises(ConfigEntryNotReady, match="Unexpected error during OIG Cloud setup"):
            await async_setup_entry(mock_hass, mock_entry)

    @patch("custom_components.oig_cloud.async_setup_entry_services")
    @patch("custom_components.oig_cloud.OigCloudDataUpdateCoordinator")
    @patch("custom_components.oig_cloud.OigCloudApi")
    @patch("custom_components.oig_cloud.asyncio.get_running_loop")
    async def test_async_setup_entry_unexpected_error(
        self, mock_get_loop, mock_api_cls, mock_coordinator_cls, mock_setup_services, mock_hass, mock_entry
    ):
        mock_api = MagicMock()
        mock_api.authenticate = AsyncMock(side_effect=ValueError("unexpected"))
        mock_api_cls.return_value = mock_api

        mock_loop = MagicMock()
        mock_future = asyncio.Future()
        mock_future.set_result(None)
        mock_loop.run_in_executor = MagicMock(return_value=mock_future)
        mock_get_loop.return_value = mock_loop

        with pytest.raises(ConfigEntryNotReady, match="Unexpected error"):
            await async_setup_entry(mock_hass, mock_entry)

    @patch("custom_components.oig_cloud.async_setup_entry_services")
    @patch("custom_components.oig_cloud.OigCloudDataUpdateCoordinator")
    @patch("custom_components.oig_cloud.OigCloudApi")
    @patch("custom_components.oig_cloud.asyncio.get_running_loop")
    async def test_async_setup_entry_default_log_level(
        self, mock_get_loop, mock_api_cls, mock_coordinator_cls, mock_setup_services, mock_hass, mock_entry
    ):
        mock_entry.data = {
            "username": "test@example.com",
            "password": "secret",
            "no_telemetry": True,
        }
        mock_entry.options = {}

        mock_api = MagicMock()
        mock_api.authenticate = AsyncMock(return_value=True)
        mock_api_cls.return_value = mock_api

        mock_coordinator = MagicMock()
        mock_coordinator.last_update_success = True
        mock_coordinator.async_config_entry_first_refresh = AsyncMock(return_value=None)
        mock_coordinator_cls.return_value = mock_coordinator

        mock_loop = MagicMock()
        mock_future = asyncio.Future()
        mock_future.set_result(None)
        mock_loop.run_in_executor = MagicMock(return_value=mock_future)
        mock_get_loop.return_value = mock_loop

        result = await async_setup_entry(mock_hass, mock_entry)
        assert result is True


class TestAsyncUnloadEntry:
    async def test_async_unload_entry_success(self, mock_hass, mock_entry):
        mock_hass.data[DOMAIN][mock_entry.entry_id] = {"coordinator": MagicMock()}
        result = await async_unload_entry(mock_hass, mock_entry)
        assert result is True
        assert mock_entry.entry_id not in mock_hass.data[DOMAIN]

    async def test_async_unload_entry_failure(self, mock_hass, mock_entry):
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
        mock_hass.data[DOMAIN][mock_entry.entry_id] = {"coordinator": MagicMock()}
        result = async_unload_entry(mock_hass, mock_entry)
        if asyncio.iscoroutine(result):
            result = await result
        assert result is False
        assert mock_entry.entry_id in mock_hass.data[DOMAIN]


class TestAsyncReloadEntry:
    @patch("custom_components.oig_cloud.async_unload_entry")
    @patch("custom_components.oig_cloud.async_setup_entry")
    async def test_async_reload_entry(self, mock_setup, mock_unload, mock_hass, mock_entry):
        mock_unload.return_value = True
        mock_setup.return_value = True

        await async_reload_entry(mock_hass, mock_entry)

        mock_unload.assert_awaited_once_with(mock_hass, mock_entry)
        mock_setup.assert_awaited_once_with(mock_hass, mock_entry)


class TestConstants:
    def test_platforms(self):
        assert PLATFORMS == ["sensor", "binary_sensor"]

    def test_all_box_modes(self):
        assert ALL_BOX_MODES == ["Home 1", "Home 2", "Home 3", "Home UPS"]
