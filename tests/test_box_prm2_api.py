"""Tests for set_box_prm2_app API and session manager methods."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from custom_components.oig_cloud.api.oig_cloud_api import OigCloudApi, OigCloudApiError
from custom_components.oig_cloud.api.oig_cloud_session_manager import OigCloudSessionManager


class TestOigCloudApiSetBoxPrm2App:
    """Test set_box_prm2_app method in OigCloudApi."""

    @pytest.fixture
    def api(self):
        """Create API instance with mocked dependencies."""
        mock_hass = MagicMock()
        api = OigCloudApi("test_user", "test_pass", False, mock_hass)
        api._logger = MagicMock()
        return api

    async def test_set_box_prm2_app_success(self, api):
        """Test setting box_prm2.app value successfully."""
        with patch.object(
            api, "set_box_params_internal", return_value=True
        ) as mock_set_params:
            result = await api.set_box_prm2_app(1)
            assert result is True
            mock_set_params.assert_called_once_with("box_prm2", "app", "1")

    async def test_set_box_prm2_app_value_zero(self, api):
        """Test setting box_prm2.app to 0."""
        with patch.object(
            api, "set_box_params_internal", return_value=True
        ) as mock_set_params:
            result = await api.set_box_prm2_app(0)
            assert result is True
            mock_set_params.assert_called_once_with("box_prm2", "app", "0")

    async def test_set_box_prm2_app_value_max(self, api):
        """Test setting box_prm2.app to max value 3."""
        with patch.object(
            api, "set_box_params_internal", return_value=True
        ) as mock_set_params:
            result = await api.set_box_prm2_app(3)
            assert result is True
            mock_set_params.assert_called_once_with("box_prm2", "app", "3")

    async def test_set_box_prm2_app_error(self, api):
        """Test set_box_prm2_app raises OigCloudApiError on error."""
        with patch.object(
            api, "set_box_params_internal", side_effect=RuntimeError("boom")
        ):
            with pytest.raises(OigCloudApiError):
                await api.set_box_prm2_app(1)


class TestOigCloudSessionManagerSetBoxPrm2App:
    """Test set_box_prm2_app method in OigCloudSessionManager."""

    @pytest.fixture
    def mock_api(self):
        """Create mock API."""
        api = MagicMock()
        api.set_box_prm2_app = AsyncMock(return_value={"ok": True})
        api.authenticate = AsyncMock(return_value=True)
        api.get_session = MagicMock(
            return_value=MagicMock(close=AsyncMock())
        )
        return api

    @pytest.fixture
    def manager(self, mock_api):
        """Create session manager with mock API."""
        return OigCloudSessionManager(mock_api)

    async def test_set_box_prm2_app_delegates_to_api(self, manager, mock_api):
        """Test session manager delegates to API via _call_with_retry."""
        result = await manager.set_box_prm2_app(2)
        assert result == {"ok": True}
        mock_api.set_box_prm2_app.assert_called_once_with(2)

    async def test_set_box_prm2_app_calls_api_with_correct_value(self, manager, mock_api):
        """Test set_box_prm2_app passes correct value to API."""
        await manager.set_box_prm2_app(1)
        mock_api.set_box_prm2_app.assert_called_with(1)