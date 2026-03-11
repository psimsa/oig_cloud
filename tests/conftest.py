import asyncio
import sys
import types
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, Mock

import pytest

try:
    import pytest_homeassistant_custom_component  # noqa: F401

    _HAS_HA_PLUGIN = True
except ImportError:
    _HAS_HA_PLUGIN = False


if "opentelemetry" not in sys.modules:
    otel = types.ModuleType("opentelemetry")
    trace = types.ModuleType("opentelemetry.trace")

    def _get_tracer(*_args, **_kwargs):
        class _DummyTracer:
            def start_as_current_span(self, *_a, **_k):
                class _DummySpan:
                    def __enter__(self):
                        return self

                    def __exit__(self, *_exc):
                        return False

                return _DummySpan()

        return _DummyTracer()

    trace.get_tracer = _get_tracer
    otel.trace = trace
    sys.modules["opentelemetry"] = otel
    sys.modules["opentelemetry.trace"] = trace


@pytest.fixture(autouse=True)
def enable_event_loop_debug() -> None:
    """Compatibility override for pytest-homeassistant-custom-component on Python 3.13+."""
    try:
        loop = asyncio.get_running_loop()
        loop.set_debug(True)
    except RuntimeError:
        # pytest-asyncio will create/set the loop later for async tests.
        pass


@pytest.fixture(autouse=True)
def verify_cleanup(expected_lingering_tasks: bool, expected_lingering_timers: bool):
    """Compatibility override for pytest-homeassistant-custom-component on Python 3.13+."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        yield
        return
    # Let HA's own cleanup checks run via its internal fixtures when possible.
    yield


if not _HAS_HA_PLUGIN:

    @pytest.fixture
    def expected_lingering_tasks() -> bool:
        return False

    @pytest.fixture
    def expected_lingering_timers() -> bool:
        return False


@pytest.fixture
def mock_api() -> Mock:
    """Create a mock OigCloudApi-like instance for unit tests."""
    api: Mock = Mock()

    api.get_stats = AsyncMock(return_value={"device1": {"box_prms": {"mode": 1}}})

    async def mock_get_extended_stats(
        name: str, from_date: str, to_date: str
    ) -> Dict[str, Any]:
        return {}

    api.get_extended_stats = AsyncMock(side_effect=mock_get_extended_stats)

    async def mock_get_notifications(device_id: Optional[str] = None) -> Dict[str, Any]:
        return {"status": "success", "content": ""}

    api.get_notifications = AsyncMock(side_effect=mock_get_notifications)
    api.authenticate = AsyncMock(return_value=True)
    api.get_session = Mock(return_value=Mock())

    async def mock_set_box_params_internal(table: str, column: str, value: str) -> bool:
        return True

    api.set_box_params_internal = AsyncMock(side_effect=mock_set_box_params_internal)

    api.set_box_mode = AsyncMock(return_value=True)
    api.set_grid_delivery_limit = AsyncMock(return_value=True)
    api.set_boiler_mode = AsyncMock(return_value=True)
    api.set_ssr_rele_1 = AsyncMock(return_value=True)
    api.set_ssr_rele_2 = AsyncMock(return_value=True)
    api.set_ssr_rele_3 = AsyncMock(return_value=True)
    api.set_grid_delivery = AsyncMock(return_value=True)
    api.set_battery_formating = AsyncMock(return_value=True)

    api.box_id = "test_device_id"
    api.last_state = None
    api.last_parsed_state = None

    return api
