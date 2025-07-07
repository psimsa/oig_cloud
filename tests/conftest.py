import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from typing import Dict, Any, Optional
import sys
from datetime import datetime, timedelta

# NOVÉ: Mock homeassistant modules before they are imported
mock_modules = [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.components.sensor",
    "homeassistant.util",
    "homeassistant.util.dt",
]

for module in mock_modules:
    if module not in sys.modules:
        sys.modules[module] = MagicMock()

# NOVÉ: Mock specific classes that are commonly used
sys.modules["homeassistant.core"].HomeAssistant = Mock
sys.modules["homeassistant.config_entries"].ConfigEntry = Mock
sys.modules["homeassistant.exceptions"].ConfigEntryNotReady = Exception
sys.modules["homeassistant.exceptions"].ConfigEntryAuthFailed = Exception
sys.modules["homeassistant.helpers.update_coordinator"].UpdateFailed = Exception


# OPRAVA: Mock DataUpdateCoordinator jako skutečnou třídu
class MockDataUpdateCoordinator:
    def __init__(
        self,
        hass: Any,
        logger: Any,
        *,
        name: str,
        update_interval: Any,
        config_entry: Optional[Any] = None,  # NOVÉ: Přidán config_entry parametr
        **kwargs: Any  # NOVÉ: Přidán **kwargs pro další parametry
    ) -> None:
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.config_entry = config_entry  # NOVÉ: Uložení config_entry
        self.data: Optional[Dict[str, Any]] = None

    async def async_config_entry_first_refresh(self) -> None:
        pass

    async def async_request_refresh(self) -> None:
        pass


sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = (
    MockDataUpdateCoordinator
)

# NOVÉ: Mock datetime utilities
sys.modules["homeassistant.util.dt"].now = lambda: datetime.now()
sys.modules["homeassistant.util.dt"].utcnow = lambda: datetime.utcnow()


@pytest.fixture
def mock_api() -> Mock:
    """Create a mock API instance."""
    api: Mock = Mock()  # Bez spec omezení

    # Mock pouze skutečné metody z OigCloudApi s odpovídajícími signaturami
    api.get_stats = AsyncMock(return_value={"device1": {"box_prms": {"mode": 1}}})

    # get_extended_stats očekává 3 parametry: name, from_date, to_date
    async def mock_get_extended_stats(
        name: str, from_date: str, to_date: str
    ) -> Dict[str, Any]:
        return {}

    api.get_extended_stats = AsyncMock(side_effect=mock_get_extended_stats)

    # get_notifications očekává optional device_id
    async def mock_get_notifications(device_id: Optional[str] = None) -> Dict[str, Any]:
        return {"status": "success", "content": ""}

    api.get_notifications = AsyncMock(side_effect=mock_get_notifications)
    api.authenticate = AsyncMock(return_value=True)
    api.get_session = Mock(return_value=Mock())

    # set_box_params_internal očekává 3 parametry: table, column, value
    async def mock_set_box_params_internal(table: str, column: str, value: str) -> bool:
        return True

    api.set_box_params_internal = AsyncMock(side_effect=mock_set_box_params_internal)

    # Přidáme další metody s typovými signaturami
    api.set_box_mode = AsyncMock(return_value=True)
    api.set_grid_delivery_limit = AsyncMock(return_value=True)
    api.set_boiler_mode = AsyncMock(return_value=True)
    api.set_ssr_rele_1 = AsyncMock(return_value=True)
    api.set_ssr_rele_2 = AsyncMock(return_value=True)
    api.set_ssr_rele_3 = AsyncMock(return_value=True)
    api.set_grid_delivery = AsyncMock(return_value=True)
    api.set_battery_formating = AsyncMock(return_value=True)

    # Přidáme atributy API
    api.box_id = "test_device_id"
    api.last_state = None
    api.last_parsed_state = None

    return api
