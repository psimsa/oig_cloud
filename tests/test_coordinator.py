"""Tests for the OIG Cloud Data Update Coordinator."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import frame as frame_helper
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.const import DEFAULT_UPDATE_INTERVAL, DOMAIN
from custom_components.oig_cloud.core.coordinator import (
    COORDINATOR_CACHE_MAX_LIST_ITEMS,
    COORDINATOR_CACHE_MAX_STR_LEN,
    OigCloudCoordinator,
)
from custom_components.oig_cloud.core.data_source import (
    DATA_SOURCE_CLOUD_ONLY,
    DATA_SOURCE_LOCAL_ONLY,
    DataSourceState,
)
from custom_components.oig_cloud.lib.oig_cloud_client.api.oig_cloud_api import \
    OigCloudApiError


@pytest.fixture
def mock_config_entry() -> Mock:
    """Create a mock config entry."""
    mock_entry: Mock = Mock(spec=ConfigEntry)
    mock_entry.entry_id = "test_entry"
    mock_entry.data = {"inverter_sn": "test_sn_123"}
    mock_entry.options = {
        "enable_pricing": False,
        "enable_extended_sensors": False,
        "enable_cloud_notifications": False,
    }
    return mock_entry


@pytest.fixture
def mock_hass(hass, mock_config_entry):
    """Create a Home Assistant instance with frame helper set."""
    if hasattr(frame_helper, "async_setup"):
        frame_helper.async_setup(hass)
    elif hasattr(frame_helper, "setup"):
        frame_helper.setup(hass)
    elif hasattr(frame_helper, "async_setup_frame"):
        frame_helper.async_setup_frame(hass)

    hass.data.setdefault(DOMAIN, {})[mock_config_entry.entry_id] = {}
    return hass


@pytest.fixture
def coordinator(
    mock_hass: Mock, mock_api: Mock, mock_config_entry: Mock
) -> OigCloudCoordinator:
    """Create a coordinator with mock dependencies."""
    return OigCloudCoordinator(
        mock_hass,
        mock_api,
        standard_interval_seconds=DEFAULT_UPDATE_INTERVAL,
        config_entry=mock_config_entry,
    )


@pytest.mark.asyncio
async def test_coordinator_init_pricing_enables_ote(monkeypatch):
    class DummyOteApi:
        def __init__(self, cache_path=None):
            self.cache_path = cache_path
            self._last_data = {"hours_count": 2, "prices_czk_kwh": {"t": 1.0}}

        async def async_load_cached_spot_prices(self):
            return None

    tasks = []

    def _async_create_task(coro):
        tasks.append(coro)
        return coro

    hass = SimpleNamespace(
        config=SimpleNamespace(path=lambda *_a: "/tmp/ote_cache.json"),
        async_create_task=_async_create_task,
        loop=SimpleNamespace(call_later=lambda *_a, **_k: None),
    )

    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": True, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ote_api.OteApi", DummyOteApi
    )
    monkeypatch.setattr(
        OigCloudCoordinator, "_schedule_hourly_fallback", lambda self: None
    )
    monkeypatch.setattr(
        OigCloudCoordinator, "_schedule_spot_price_update", lambda self: None
    )
    async def _update_spot_prices(_self):
        return None

    monkeypatch.setattr(
        OigCloudCoordinator, "_update_spot_prices", _update_spot_prices
    )

    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    assert coordinator.ote_api is not None
    await tasks[0]
    for task in tasks[1:]:
        task.close()
    assert coordinator._spot_prices_cache == coordinator.ote_api._last_data


@pytest.mark.asyncio
async def test_coordinator_init_chmu_enabled(monkeypatch):
    class DummyChmuApi:
        pass

    hass = SimpleNamespace(
        config=SimpleNamespace(path=lambda *_a: "/tmp/ote_cache.json"),
        async_create_task=lambda coro: coro,
        loop=SimpleNamespace(call_later=lambda *_a, **_k: None),
    )

    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": True}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.api_chmu.ChmuApi", DummyChmuApi
    )

    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    assert coordinator.chmu_api is not None


@pytest.mark.asyncio
async def test_coordinator_initialization(
    mock_hass: Mock, mock_api: Mock, mock_config_entry: Mock
) -> None:
    """Test coordinator initialization."""
    coordinator = OigCloudCoordinator(
        mock_hass,
        mock_api,
        standard_interval_seconds=DEFAULT_UPDATE_INTERVAL,
        config_entry=mock_config_entry,
    )

    assert coordinator.api == mock_api
    assert coordinator.update_interval == timedelta(seconds=DEFAULT_UPDATE_INTERVAL)


@pytest.mark.asyncio
async def test_async_update_data_success(
    coordinator: OigCloudCoordinator, mock_api: Mock
) -> None:
    """Test data update success."""
    mock_api.get_stats = AsyncMock(return_value={"device1": {"box_prms": {"mode": 1}}})

    coordinator._startup_grace_seconds = 0
    with patch(
        "custom_components.oig_cloud.core.coordinator.random.uniform", return_value=-1
    ):
        result: Dict[str, Any] = await coordinator._async_update_data()

    assert result == {"device1": {"box_prms": {"mode": 1}}}
    mock_api.get_stats.assert_called_once()


@pytest.mark.asyncio
async def test_async_update_data_empty_response(
    coordinator: OigCloudCoordinator, mock_api: Mock
) -> None:
    """Test handling of empty data response."""
    mock_api.get_stats = AsyncMock(return_value=None)

    coordinator._startup_grace_seconds = 0
    with patch(
        "custom_components.oig_cloud.core.coordinator.random.uniform", return_value=-1
    ):
        result: Dict[str, Any] = await coordinator._async_update_data()

    assert result == {}


@pytest.mark.asyncio
async def test_async_update_data_api_error(
    coordinator: OigCloudCoordinator, mock_api: Mock
) -> None:
    """Test handling of API errors."""
    mock_api.get_stats = AsyncMock(
        side_effect=OigCloudApiError("API connection failed")
    )

    coordinator._startup_grace_seconds = 0
    with patch(
        "custom_components.oig_cloud.core.coordinator.random.uniform", return_value=-1
    ):
        with pytest.raises(
            UpdateFailed, match="Error communicating with OIG API: API connection failed"
        ):
            await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_update_data_jitter_positive(monkeypatch, coordinator, mock_api):
    mock_api.get_stats = AsyncMock(return_value={})
    coordinator._startup_grace_seconds = 0

    async def _sleep(_seconds):
        return None

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: 2.0,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.asyncio.sleep", _sleep
    )

    await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_update_data_data_source_state_exception(monkeypatch, coordinator):
    coordinator._startup_grace_seconds = 0
    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.get_data_source_state",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    result = await coordinator._async_update_data()

    assert result == {}


@pytest.mark.asyncio
async def test_async_update_data_telemetry_snapshot_exception(monkeypatch, coordinator):
    class DummyStore:
        def get_snapshot(self):
            raise RuntimeError("boom")

    coordinator.telemetry_store = DummyStore()
    coordinator.data = {"k": 1}
    coordinator._startup_grace_seconds = 0
    coordinator.config_entry.options["enable_battery_prediction"] = False

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.get_data_source_state",
        lambda *_a, **_k: DataSourceState(
            configured_mode=DATA_SOURCE_LOCAL_ONLY,
            effective_mode=DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=None,
            reason="local_ok",
        ),
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    result = await coordinator._async_update_data()

    assert result["k"] == 1


@pytest.mark.asyncio
async def test_async_update_data_local_mode_no_telemetry_store(
    monkeypatch, coordinator
):
    coordinator.telemetry_store = None
    coordinator.data = {"k": 2}
    coordinator._startup_grace_seconds = 0
    coordinator.config_entry.options["enable_battery_prediction"] = False

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.get_data_source_state",
        lambda *_a, **_k: DataSourceState(
            configured_mode=DATA_SOURCE_LOCAL_ONLY,
            effective_mode=DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=None,
            reason="local_ok",
        ),
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    result = await coordinator._async_update_data()

    assert result["k"] == 2


@pytest.mark.asyncio
async def test_async_update_data_fill_config_nodes_exception(
    monkeypatch, coordinator
):
    coordinator.telemetry_store = None
    coordinator.data = {"k": 3}
    coordinator._startup_grace_seconds = 0
    coordinator.config_entry.options["enable_battery_prediction"] = False

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.get_data_source_state",
        lambda *_a, **_k: DataSourceState(
            configured_mode=DATA_SOURCE_LOCAL_ONLY,
            effective_mode=DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=None,
            reason="local_ok",
        ),
    )
    monkeypatch.setattr(
        coordinator,
        "_maybe_fill_config_nodes_from_cloud",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    result = await coordinator._async_update_data()

    assert result["k"] == 3
@pytest.mark.asyncio
async def test_extended_data_enabled(
    coordinator: OigCloudCoordinator, mock_api: Mock, mock_config_entry: Mock
) -> None:
    """Test that extended stats are included when enabled."""
    mock_config_entry.options["enable_extended_sensors"] = True
    mock_api.get_stats = AsyncMock(return_value={"device1": {"box_prms": {"mode": 1}}})

    coordinator._startup_grace_seconds = 0
    with patch(
        "custom_components.oig_cloud.core.coordinator.random.uniform", return_value=-1
    ):
        result: Dict[str, Any] = await coordinator._async_update_data()

    assert result.get("extended_batt") == {}
    assert result.get("extended_fve") == {}
    assert result.get("extended_grid") == {}
    assert result.get("extended_load") == {}


@pytest.mark.asyncio
async def test_async_update_data_startup_grace_includes_cache(
    coordinator: OigCloudCoordinator, mock_api: Mock
) -> None:
    mock_api.get_stats = AsyncMock(return_value={"device1": {"box_prms": {"mode": 1}}})
    coordinator._startup_grace_start = datetime.now(timezone.utc)
    coordinator._startup_grace_seconds = 60
    coordinator._spot_prices_cache = {"prices_czk_kwh": {"t": 1.0}}

    with patch(
        "custom_components.oig_cloud.core.coordinator.random.uniform", return_value=-1
    ):
        result = await coordinator._async_update_data()

    assert result.get("spot_prices") == coordinator._spot_prices_cache


@pytest.mark.asyncio
async def test_async_update_data_initial_spot_fetch(
    coordinator: OigCloudCoordinator, mock_api: Mock
) -> None:
    class DummyOteApi:
        async def get_spot_prices(self):
            return {"hours_count": 2, "prices_czk_kwh": {"t": 1.0}}

    mock_api.get_stats = AsyncMock(return_value={"device1": {"box_prms": {"mode": 1}}})
    coordinator._startup_grace_seconds = 0
    coordinator._spot_prices_cache = None
    coordinator.ote_api = DummyOteApi()

    with patch(
        "custom_components.oig_cloud.core.coordinator.random.uniform", return_value=-1
    ):
        result = await coordinator._async_update_data()

    assert result.get("spot_prices") is not None
    assert coordinator._spot_prices_cache is not None


def _make_simple_hass():
    def _async_create_task(coro):
        if hasattr(coro, "close"):
            coro.close()
        return coro

    return SimpleNamespace(
        config=SimpleNamespace(path=lambda *_a: "/tmp/ote_cache.json"),
        async_create_task=_async_create_task,
        loop=SimpleNamespace(call_later=lambda *_a, **_k: None),
        data={},
    )


def test_schedule_spot_price_update_before_13(monkeypatch):
    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    captured = {}

    def _track(_hass, _cb, when):
        captured["when"] = when

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.async_track_point_in_time",
        _track,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    coordinator._schedule_spot_price_update()

    assert captured["when"].hour == 13
    assert captured["when"].minute == 5
    assert captured["when"].day == 1


def test_schedule_spot_price_update_after_13(monkeypatch):
    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    captured = {}

    def _track(_hass, _cb, when):
        captured["when"] = when

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.async_track_point_in_time",
        _track,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: datetime(2025, 1, 1, 14, 0, tzinfo=timezone.utc),
    )

    coordinator._schedule_spot_price_update()

    assert captured["when"].day == 2
    assert captured["when"].hour == 13
    assert captured["when"].minute == 5


@pytest.mark.asyncio
async def test_schedule_spot_price_update_callback(monkeypatch):
    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    coordinator._update_spot_prices = AsyncMock()

    captured = {}

    def _track(_hass, cb, _when):
        captured["cb"] = cb

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.async_track_point_in_time",
        _track,
    )

    coordinator._schedule_spot_price_update()

    await captured["cb"](datetime(2025, 1, 1, 13, 5, tzinfo=timezone.utc))

    assert coordinator._update_spot_prices.called


def test_schedule_hourly_fallback_schedules(monkeypatch):
    created = {"count": 0}

    def _async_create_task(coro):
        created["count"] += 1
        if hasattr(coro, "close"):
            coro.close()
        return coro

    loop = SimpleNamespace()
    captured = {}

    def _call_later(delay, cb):
        captured["delay"] = delay
        captured["cb"] = cb

    loop.call_later = _call_later

    hass = SimpleNamespace(
        config=SimpleNamespace(path=lambda *_a: "/tmp/ote_cache.json"),
        async_create_task=_async_create_task,
        loop=loop,
    )

    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    coordinator._schedule_hourly_fallback()

    assert captured["delay"] == 3600
    captured["cb"]()
    assert created["count"] == 1


@pytest.mark.asyncio
async def test_hourly_fallback_updates_cache(monkeypatch):
    class DummyOteApi:
        async def get_spot_prices(self):
            return {"prices_czk_kwh": {"2025-01-01T00:00:00": 1.0}, "hours_count": 1}

    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    coordinator.ote_api = DummyOteApi()
    coordinator.data = {"spot_prices": {"prices_czk_kwh": {}}}

    called = {"scheduled": 0}

    def _schedule():
        called["scheduled"] += 1

    monkeypatch.setattr(coordinator, "_schedule_hourly_fallback", _schedule)
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    await coordinator._hourly_fallback_check()

    assert coordinator._spot_prices_cache
    assert coordinator.data["spot_prices"]["prices_czk_kwh"]
    assert called["scheduled"] == 1


@pytest.mark.asyncio
async def test_hourly_fallback_no_data_and_exception(monkeypatch):
    class DummyOteApi:
        async def get_spot_prices(self):
            raise RuntimeError("boom")

    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    coordinator.ote_api = DummyOteApi()
    coordinator.data = None

    called = {"scheduled": 0}

    def _schedule():
        called["scheduled"] += 1

    monkeypatch.setattr(coordinator, "_schedule_hourly_fallback", _schedule)
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: datetime(2025, 1, 1, 14, 0, tzinfo=timezone.utc),
    )

    await coordinator._hourly_fallback_check()

    assert called["scheduled"] == 1
    assert coordinator._hourly_fallback_active is False


@pytest.mark.asyncio
async def test_hourly_fallback_no_need(monkeypatch):
    class DummyOteApi:
        async def get_spot_prices(self):
            return {"prices_czk_kwh": {"2025-01-02T00:00:00": 1.0}, "hours_count": 1}

    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    coordinator.ote_api = DummyOteApi()
    coordinator.data = {
        "spot_prices": {"prices_czk_kwh": {"2025-01-02T00:00:00": 1.0}}
    }

    called = {"scheduled": 0}

    def _schedule():
        called["scheduled"] += 1

    monkeypatch.setattr(coordinator, "_schedule_hourly_fallback", _schedule)
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: datetime(2025, 1, 1, 14, 0, tzinfo=timezone.utc),
    )

    await coordinator._hourly_fallback_check()

    assert called["scheduled"] == 1
    assert coordinator._hourly_fallback_active is False


@pytest.mark.asyncio
async def test_hourly_fallback_no_ote_api(monkeypatch):
    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    coordinator.ote_api = None

    await coordinator._hourly_fallback_check()


@pytest.mark.asyncio
async def test_hourly_fallback_after_13_missing_tomorrow(monkeypatch):
    class DummyOteApi:
        async def get_spot_prices(self):
            return {"prices_czk_kwh": {"2025-01-01T00:00:00": 1.0}, "hours_count": 1}

    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    coordinator.ote_api = DummyOteApi()
    coordinator.data = {
        "spot_prices": {"prices_czk_kwh": {"2025-01-01T00:00:00": 1.0}}
    }

    monkeypatch.setattr(coordinator, "_schedule_hourly_fallback", lambda: None)
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: datetime(2025, 1, 1, 14, 0, tzinfo=timezone.utc),
    )

    await coordinator._hourly_fallback_check()

    assert coordinator._spot_prices_cache is not None


@pytest.mark.asyncio
async def test_hourly_fallback_warning_on_empty(monkeypatch):
    class DummyOteApi:
        async def get_spot_prices(self):
            return {"prices_czk_kwh": {}, "hours_count": 0}

    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    coordinator.ote_api = DummyOteApi()
    coordinator.data = {"spot_prices": {"prices_czk_kwh": {}}}

    monkeypatch.setattr(coordinator, "_schedule_hourly_fallback", lambda: None)
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
    )

    await coordinator._hourly_fallback_check()


@pytest.mark.asyncio
async def test_update_spot_prices_success(monkeypatch):
    class DummyOteApi:
        async def get_spot_prices(self):
            return {"prices_czk_kwh": {"2025-01-01T00:00:00": 2.0}, "hours_count": 1}

    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    coordinator.ote_api = DummyOteApi()
    coordinator.data = {}
    coordinator._spot_retry_count = 2
    coordinator._hourly_fallback_active = True

    scheduled = {"count": 0}

    def _schedule():
        scheduled["count"] += 1

    monkeypatch.setattr(coordinator, "_schedule_spot_price_update", _schedule)

    await coordinator._update_spot_prices()

    assert coordinator._spot_prices_cache
    assert coordinator._spot_retry_count == 0
    assert coordinator._hourly_fallback_active is False
    assert scheduled["count"] == 1


@pytest.mark.asyncio
async def test_update_spot_prices_updates_listeners(monkeypatch):
    class DummyOteApi:
        async def get_spot_prices(self):
            return {"prices_czk_kwh": {"2025-01-01T00:00:00": 2.0}, "hours_count": 1}

    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    coordinator.ote_api = DummyOteApi()
    coordinator.data = {"spot_prices": {"prices_czk_kwh": {}}}
    coordinator.async_update_listeners = Mock()
    monkeypatch.setattr(coordinator, "_schedule_spot_price_update", lambda: None)

    await coordinator._update_spot_prices()

    assert coordinator.async_update_listeners.called


@pytest.mark.asyncio
async def test_update_spot_prices_no_ote_api(monkeypatch):
    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    coordinator.ote_api = None

    await coordinator._update_spot_prices()


@pytest.mark.asyncio
async def test_update_spot_prices_exception_calls_retry(monkeypatch):
    class DummyOteApi:
        async def get_spot_prices(self):
            raise RuntimeError("boom")

    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    coordinator.ote_api = DummyOteApi()

    called = {"retry": 0}

    def _handle_retry():
        called["retry"] += 1

    monkeypatch.setattr(coordinator, "_handle_spot_retry", _handle_retry)

    await coordinator._update_spot_prices()

    assert called["retry"] == 1


@pytest.mark.asyncio
async def test_update_spot_prices_failure_calls_retry(monkeypatch):
    class DummyOteApi:
        async def get_spot_prices(self):
            return {}

    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    coordinator.ote_api = DummyOteApi()

    called = {"retry": 0}

    def _handle_retry():
        called["retry"] += 1

    monkeypatch.setattr(coordinator, "_handle_spot_retry", _handle_retry)

    await coordinator._update_spot_prices()

    assert called["retry"] == 1


def test_handle_spot_retry_outside_important(monkeypatch):
    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    scheduled = {"count": 0}

    def _schedule():
        scheduled["count"] += 1

    monkeypatch.setattr(coordinator, "_schedule_spot_price_update", _schedule)
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
    )

    coordinator._spot_retry_count = 0
    coordinator._handle_spot_retry()

    assert coordinator._spot_retry_count == 0
    assert scheduled["count"] == 1


def test_handle_spot_retry_inside_important(monkeypatch):
    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    created = {"count": 0}

    def _create_task(coro):
        created["count"] += 1
        if hasattr(coro, "close"):
            coro.close()
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.asyncio.create_task",
        _create_task,
    )

    coordinator._spot_retry_count = 0
    coordinator._handle_spot_retry()

    assert created["count"] == 1


def test_handle_spot_retry_cancels_existing(monkeypatch):
    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    existing = Mock()
    existing.done.return_value = False
    coordinator._spot_retry_task = existing

    created = {"count": 0}

    def _create_task(coro):
        created["count"] += 1
        if hasattr(coro, "close"):
            coro.close()
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.asyncio.create_task",
        _create_task,
    )

    coordinator._spot_retry_count = 0
    coordinator._handle_spot_retry()

    assert existing.cancel.called
    assert created["count"] == 1


def test_handle_spot_retry_resets_after_max(monkeypatch):
    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    existing = Mock()
    existing.done.return_value = False
    coordinator._spot_retry_task = existing

    scheduled = {"count": 0}

    def _schedule():
        scheduled["count"] += 1

    monkeypatch.setattr(coordinator, "_schedule_spot_price_update", _schedule)
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: datetime(2025, 1, 1, 13, 30, tzinfo=timezone.utc),
    )

    coordinator._spot_retry_count = 3
    coordinator._handle_spot_retry()

    assert coordinator._spot_retry_count == 0
    assert existing.cancel.called
    assert coordinator._spot_retry_task is None
    assert scheduled["count"] == 1


@pytest.mark.asyncio
async def test_handle_spot_retry_executes_retry_callback(monkeypatch):
    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    async def _sleep(_seconds):
        return None

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.asyncio.sleep", _sleep
    )
    coordinator._update_spot_prices = AsyncMock()

    def _create_task(coro):
        return coro

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.asyncio.create_task",
        _create_task,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc),
    )

    coordinator._spot_retry_count = 0
    coordinator._handle_spot_retry()

    await coordinator._spot_retry_task

    assert coordinator._update_spot_prices.called


def test_prune_for_cache_limits_payload(monkeypatch):
    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    oversized = "x" * (COORDINATOR_CACHE_MAX_STR_LEN + 10)
    data = {
        "timeline_data": [1, 2, 3],
        "str": oversized,
        "list": list(range(COORDINATOR_CACHE_MAX_LIST_ITEMS + 5)),
        "tuple": tuple(range(COORDINATOR_CACHE_MAX_LIST_ITEMS + 2)),
        "when": datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
        "nested": {"deep": {"deeper": {"leaf": "ok"}}},
    }

    pruned = coordinator._prune_for_cache(data)

    assert "timeline_data" not in pruned
    assert len(pruned["str"]) == COORDINATOR_CACHE_MAX_STR_LEN
    assert len(pruned["list"]) == COORDINATOR_CACHE_MAX_LIST_ITEMS
    assert len(pruned["tuple"]) == COORDINATOR_CACHE_MAX_LIST_ITEMS
    assert pruned["when"] == "2025-01-01T10:00:00+00:00"


def test_prune_for_cache_fallback_str_failure(monkeypatch):
    class BadStr:
        def __str__(self):
            raise RuntimeError("nope")

    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    assert coordinator._prune_for_cache(BadStr()) is None


def test_prune_for_cache_depth_limit(monkeypatch):
    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    assert coordinator._prune_for_cache("x", _depth=7) is None


def test_prune_for_cache_datetime_isoformat_error(monkeypatch):
    class BadDatetime(datetime):
        def isoformat(self, *_a, **_k):
            raise RuntimeError("bad iso")

        def __str__(self):
            return "bad"

    hass = _make_simple_hass()
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    bad_dt = BadDatetime(2025, 1, 1, tzinfo=timezone.utc)
    assert coordinator._prune_for_cache(bad_dt) == "bad"


@pytest.mark.asyncio
async def test_maybe_schedule_cache_save(monkeypatch, coordinator):
    saved = []
    tasks = []

    async def _async_save(snapshot):
        saved.append(snapshot)

    class DummyStore:
        async_save = AsyncMock(side_effect=_async_save)

    def _create_task(coro):
        tasks.append(coro)
        return coro

    monkeypatch.setattr(coordinator, "_cache_store", DummyStore())
    monkeypatch.setattr(coordinator.hass, "async_create_task", _create_task)

    coordinator._maybe_schedule_cache_save({"device": {"value": 1}})

    assert tasks
    await tasks[0]
    assert saved
    assert saved[0]["data"]["device"]["value"] == 1

    coordinator._last_cache_save_ts = coordinator._utcnow()
    coordinator._maybe_schedule_cache_save({"device": {"value": 2}})
    assert len(tasks) == 1


def test_maybe_schedule_cache_save_no_store(monkeypatch, coordinator):
    monkeypatch.setattr(coordinator, "_cache_store", None)
    coordinator._maybe_schedule_cache_save({"device": {"value": 1}})


@pytest.mark.asyncio
async def test_maybe_schedule_cache_save_errors(monkeypatch, coordinator):
    async def _async_save(_snapshot):
        raise RuntimeError("boom")

    class DummyStore:
        async_save = AsyncMock(side_effect=_async_save)

    monkeypatch.setattr(coordinator, "_cache_store", DummyStore())

    def _create_task(_coro):
        if hasattr(_coro, "close"):
            _coro.close()
        raise RuntimeError("no task")

    monkeypatch.setattr(coordinator.hass, "async_create_task", _create_task)

    coordinator._maybe_schedule_cache_save({"device": {"value": 1}})

    class DummyHass:
        def async_create_task(self, coro):
            return coro

    coordinator.hass = DummyHass()
    coordinator._maybe_schedule_cache_save({"device": {"value": 2}})


@pytest.mark.asyncio
async def test_maybe_schedule_cache_save_async_save_error(monkeypatch, coordinator):
    tasks = []

    class DummyStore:
        async def async_save(self, _snapshot):
            raise RuntimeError("boom")

    def _create_task(coro):
        tasks.append(coro)
        return coro

    monkeypatch.setattr(coordinator, "_cache_store", DummyStore())
    monkeypatch.setattr(coordinator.hass, "async_create_task", _create_task)

    coordinator._maybe_schedule_cache_save({"device": {"value": 1}})

    await tasks[0]


def test_update_intervals_triggers_refresh(monkeypatch, coordinator):
    created = []

    def _create_task(coro):
        created.append(coro)
        return coro

    monkeypatch.setattr(coordinator.hass, "async_create_task", _create_task)
    monkeypatch.setattr(coordinator, "async_request_refresh", AsyncMock())

    coordinator.update_intervals(10, 20)

    assert coordinator.update_interval == timedelta(seconds=10)
    assert coordinator.extended_interval == 20
    assert created
    if hasattr(created[0], "close"):
        created[0].close()


@pytest.mark.asyncio
async def test_fill_config_nodes_from_cloud(monkeypatch, coordinator):
    coordinator.config_entry.options["box_id"] = "123"
    stats = {"123": {"box_prms": {}, "batt_prms": {}}}
    cloud = {
        "123": {
            "box_prms": {"mode": 2},
            "invertor_prms": {"param": 1},
            "boiler_prms": {"limit": 10},
        }
    }
    coordinator.api.get_stats = AsyncMock(return_value=cloud)

    await coordinator._maybe_fill_config_nodes_from_cloud(stats)

    assert stats["123"]["box_prms"]["mode"] == 2
    assert stats["123"]["invertor_prms"]["param"] == 1
    assert stats["123"]["boiler_prms"]["limit"] == 10


@pytest.mark.asyncio
async def test_fill_config_nodes_from_cloud_missing_box(monkeypatch, coordinator):
    coordinator.config_entry.options["box_id"] = "not_a_number"
    stats = {"foo": {"box_prms": {}}}

    coordinator.api.get_stats = AsyncMock(return_value={"foo": {"box_prms": {}}})

    await coordinator._maybe_fill_config_nodes_from_cloud(stats)

    assert "box_prms" in stats["foo"]


def test_should_update_extended_handles_timezone(monkeypatch, coordinator):
    fixed_now = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    coordinator.extended_interval = 60

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: fixed_now,
    )

    coordinator._last_extended_update = fixed_now - timedelta(seconds=120)
    assert coordinator._should_update_extended() is True

    coordinator._last_extended_update = fixed_now - timedelta(seconds=30)
    assert coordinator._should_update_extended() is False


@pytest.mark.asyncio
async def test_async_update_data_local_mode_uses_snapshot(monkeypatch, coordinator):
    class DummyStore:
        def get_snapshot(self):
            return SimpleNamespace(payload={"123": {"box_prms": {"mode": 1}}})

    coordinator.telemetry_store = DummyStore()
    coordinator.data = {}
    coordinator.config_entry.options.update(
        {
            "enable_extended_sensors": False,
            "enable_battery_prediction": False,
        }
    )
    coordinator._startup_grace_seconds = 0

    def _fake_state(_hass, _entry_id):
        return DataSourceState(
            configured_mode=DATA_SOURCE_LOCAL_ONLY,
            effective_mode=DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=None,
            reason="local_ok",
        )

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.get_data_source_state",
        _fake_state,
    )
    monkeypatch.setattr(coordinator, "_maybe_fill_config_nodes_from_cloud", AsyncMock())
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    result = await coordinator._async_update_data()

    assert result["123"]["box_prms"]["mode"] == 1


@pytest.mark.asyncio
async def test_async_update_data_standalone_notifications(monkeypatch, coordinator):
    class DummyNotification:
        def __init__(self):
            self._device_id = "dev"
            self.update_from_api = AsyncMock()

    coordinator.notification_manager = DummyNotification()
    coordinator.config_entry.options.update(
        {
            "enable_cloud_notifications": True,
            "enable_extended_sensors": False,
            "enable_battery_prediction": False,
        }
    )
    coordinator._startup_grace_seconds = 0

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.get_data_source_state",
        lambda *_a, **_k: DataSourceState(
            configured_mode=DATA_SOURCE_CLOUD_ONLY,
            effective_mode=DATA_SOURCE_CLOUD_ONLY,
            local_available=False,
            last_local_data=None,
            reason="cloud_only",
        ),
    )
    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    await coordinator._async_update_data()

    assert coordinator.notification_manager.update_from_api.called


@pytest.mark.asyncio
async def test_async_update_data_notification_init_failure(monkeypatch, coordinator):
    coordinator.config_entry.options.update(
        {
            "enable_cloud_notifications": True,
            "enable_extended_sensors": False,
            "enable_battery_prediction": False,
        }
    )
    coordinator._startup_grace_seconds = 0
    coordinator.notification_manager = None

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.get_data_source_state",
        lambda *_a, **_k: DataSourceState(
            configured_mode=DATA_SOURCE_CLOUD_ONLY,
            effective_mode=DATA_SOURCE_CLOUD_ONLY,
            local_available=False,
            last_local_data=None,
            reason="cloud_only",
        ),
    )

    def _raise_init(*_a, **_k):
        raise RuntimeError("fail")

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.oig_cloud_notification.OigNotificationManager",
        _raise_init,
    )

    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    result = await coordinator._async_update_data()

    assert result == {}
    assert coordinator.notification_manager is None


@pytest.mark.asyncio
async def test_async_update_data_notification_init_success(monkeypatch, coordinator):
    class DummyNotification:
        def __init__(self, *_a, **_k):
            self._device_id = "dev"

    coordinator.config_entry.options.update(
        {
            "enable_cloud_notifications": True,
            "enable_extended_sensors": False,
            "enable_battery_prediction": False,
        }
    )
    coordinator._startup_grace_seconds = 0
    coordinator.notification_manager = None

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.oig_cloud_notification.OigNotificationManager",
        DummyNotification,
    )
    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    await coordinator._async_update_data()

    assert coordinator.notification_manager is not None


@pytest.mark.asyncio
async def test_async_update_data_notification_status_no_attr(
    monkeypatch, coordinator
):
    coordinator.config_entry.options.update(
        {
            "enable_cloud_notifications": False,
            "enable_extended_sensors": False,
            "enable_battery_prediction": False,
        }
    )
    coordinator._startup_grace_seconds = 0
    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    import builtins

    real_hasattr = builtins.hasattr

    def _fake_hasattr(obj, name):
        if obj is coordinator and name == "notification_manager":
            return False
        return real_hasattr(obj, name)

    monkeypatch.setattr(builtins, "hasattr", _fake_hasattr)

    await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_update_data_config_entry_options_exception(
    monkeypatch, coordinator
):
    class BadOptions:
        def get(self, key, default=None):
            return default

        def keys(self):
            raise RuntimeError("bad keys")

    coordinator.config_entry.options = BadOptions()
    coordinator._startup_grace_seconds = 0
    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    result = await coordinator._async_update_data()

    assert result == {}


@pytest.mark.asyncio
async def test_async_update_data_no_config_entry(monkeypatch, mock_hass):
    coordinator = OigCloudCoordinator(mock_hass, Mock(), config_entry=None)
    coordinator._startup_grace_seconds = 0
    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    result = await coordinator._async_update_data()

    assert result == {}


@pytest.mark.asyncio
async def test_async_update_data_extended_notifications_success(
    monkeypatch, coordinator
):
    class DummyNotification:
        def __init__(self):
            self._device_id = "dev"
            self.update_from_api = AsyncMock()

    coordinator.notification_manager = DummyNotification()
    coordinator.config_entry.options.update(
        {
            "enable_cloud_notifications": True,
            "enable_extended_sensors": True,
            "enable_battery_prediction": False,
        }
    )
    coordinator._startup_grace_seconds = 0

    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    coordinator.api.get_extended_stats = AsyncMock(return_value={})
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    await coordinator._async_update_data()

    assert coordinator.notification_manager.update_from_api.called


@pytest.mark.asyncio
async def test_async_update_data_extended_notifications_no_device(
    monkeypatch, coordinator
):
    class DummyNotification:
        def __init__(self):
            self._device_id = None
            self.update_from_api = AsyncMock()

    coordinator.notification_manager = DummyNotification()
    coordinator.config_entry.options.update(
        {
            "enable_cloud_notifications": True,
            "enable_extended_sensors": True,
            "enable_battery_prediction": False,
        }
    )
    coordinator._startup_grace_seconds = 0

    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    coordinator.api.get_extended_stats = AsyncMock(return_value={})
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    await coordinator._async_update_data()

    assert not coordinator.notification_manager.update_from_api.called


@pytest.mark.asyncio
async def test_async_update_data_extended_notifications_failure(
    monkeypatch, coordinator
):
    class DummyNotification:
        def __init__(self):
            self._device_id = "dev"
            self.update_from_api = AsyncMock(side_effect=RuntimeError("boom"))

    coordinator.notification_manager = DummyNotification()
    coordinator.config_entry.options.update(
        {
            "enable_cloud_notifications": True,
            "enable_extended_sensors": True,
            "enable_battery_prediction": False,
        }
    )
    coordinator._startup_grace_seconds = 0

    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    coordinator.api.get_extended_stats = AsyncMock(return_value={})
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_update_data_extended_stats_failure(monkeypatch, coordinator):
    coordinator.config_entry.options.update(
        {
            "enable_cloud_notifications": False,
            "enable_extended_sensors": True,
            "enable_battery_prediction": False,
        }
    )
    coordinator._startup_grace_seconds = 0

    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    coordinator.api.get_extended_stats = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    await coordinator._async_update_data()

    assert coordinator.extended_data == {}


@pytest.mark.asyncio
async def test_async_update_data_standalone_notification_failure(
    monkeypatch, coordinator
):
    class DummyNotification:
        def __init__(self):
            self._device_id = "dev"
            self.update_from_api = AsyncMock(side_effect=RuntimeError("boom"))

    coordinator.notification_manager = DummyNotification()
    coordinator.config_entry.options.update(
        {
            "enable_cloud_notifications": True,
            "enable_extended_sensors": False,
            "enable_battery_prediction": False,
        }
    )
    coordinator._startup_grace_seconds = 0
    coordinator._last_notification_update = dt_util.now() - timedelta(minutes=10)

    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_update_data_battery_forecast_task_running(
    monkeypatch, coordinator
):
    class DummyTask:
        def done(self):
            return False

    coordinator._battery_forecast_task = DummyTask()
    coordinator.config_entry.options["enable_battery_prediction"] = True
    coordinator._startup_grace_seconds = 0
    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    await coordinator._async_update_data()

    assert coordinator._battery_forecast_task is not None


@pytest.mark.asyncio
async def test_async_update_data_includes_spot_prices_cache(
    monkeypatch, coordinator
):
    coordinator._spot_prices_cache = {"prices_czk_kwh": {"t": 1.0}}
    coordinator._startup_grace_seconds = 0
    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    result = await coordinator._async_update_data()

    assert result["spot_prices"]["prices_czk_kwh"]["t"] == 1.0


@pytest.mark.asyncio
async def test_async_update_data_includes_battery_forecast_data(
    monkeypatch, coordinator
):
    coordinator.battery_forecast_data = {"timeline_data": [1]}
    coordinator._startup_grace_seconds = 0
    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    result = await coordinator._async_update_data()

    assert result["battery_forecast"]["timeline_data"] == [1]
@pytest.mark.asyncio
async def test_async_update_data_initial_spot_fetch_empty(monkeypatch, coordinator):
    class DummyOteApi:
        async def get_spot_prices(self):
            return {}

    coordinator.ote_api = DummyOteApi()
    coordinator._spot_prices_cache = None
    coordinator._startup_grace_seconds = 0
    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    result = await coordinator._async_update_data()

    assert result == {}
    assert coordinator._spot_prices_cache is None


@pytest.mark.asyncio
async def test_async_update_data_initial_spot_fetch_exception(monkeypatch, coordinator):
    class DummyOteApi:
        async def get_spot_prices(self):
            raise RuntimeError("boom")

    coordinator.ote_api = DummyOteApi()
    coordinator._spot_prices_cache = None
    coordinator._startup_grace_seconds = 0
    monkeypatch.setattr(coordinator, "_try_get_stats", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.random.uniform",
        lambda *_a, **_k: -1,
    )

    result = await coordinator._async_update_data()

    assert result == {}
    assert coordinator._spot_prices_cache is None


@pytest.mark.asyncio
async def test_update_battery_forecast_skips_without_data(monkeypatch, coordinator):
    coordinator.data = None
    await coordinator._update_battery_forecast()
    assert coordinator.battery_forecast_data is None


@pytest.mark.asyncio
async def test_update_battery_forecast_no_inverter(monkeypatch, coordinator):
    coordinator.data = {"not_numeric": {"batt_bat_c": 10}}
    await coordinator._update_battery_forecast()
    assert coordinator.battery_forecast_data is None


@pytest.mark.asyncio
async def test_update_battery_forecast_with_timeline(monkeypatch, coordinator):
    class DummySensor:
        def __init__(self, *_a, **_k):
            self._timeline_data = [{"battery_capacity_kwh": 3}]
            self._last_update = datetime(2025, 1, 1, tzinfo=timezone.utc)
            self._mode_recommendations = ["eco"]
            self._hass = _k.get("hass")

        async def async_update(self):
            return None

    coordinator.data = {"123": {"batt_bat_c": 10}}
    coordinator.config_entry.options["box_id"] = "123"

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.OigCloudBatteryForecastSensor",
        DummySensor,
    )

    await coordinator._update_battery_forecast()

    assert coordinator.battery_forecast_data["mode_recommendations"] == ["eco"]


@pytest.mark.asyncio
async def test_update_battery_forecast_no_timeline(monkeypatch, coordinator):
    class DummySensor:
        def __init__(self, *_a, **_k):
            self._timeline_data = None
            self._last_update = None
            self._mode_recommendations = []
            self._hass = _k.get("hass")

        async def async_update(self):
            return None

    coordinator.data = {"123": {"batt_bat_c": 10}}
    coordinator.config_entry.options["box_id"] = "123"

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.OigCloudBatteryForecastSensor",
        DummySensor,
    )

    await coordinator._update_battery_forecast()

    assert coordinator.battery_forecast_data is None


def test_create_simple_battery_forecast_no_data(monkeypatch, coordinator):
    coordinator.data = None
    forecast = coordinator._create_simple_battery_forecast()
    assert forecast["forecast_available"] is False


def test_create_simple_battery_forecast_with_data(monkeypatch, coordinator):
    coordinator.data = {"123": {"batt_bat_c": 42}}
    forecast = coordinator._create_simple_battery_forecast()
    assert forecast["current_battery_level"] == 42


@pytest.mark.asyncio
async def test_maybe_fill_config_nodes_throttled(monkeypatch, coordinator):
    now = coordinator._utcnow()
    coordinator._last_cloud_config_fill_ts = now
    stats = {"123": {"box_prms": {}}}
    coordinator.config_entry.options["box_id"] = "123"

    await coordinator._maybe_fill_config_nodes_from_cloud(stats)


@pytest.mark.asyncio
async def test_maybe_fill_config_nodes_option_error(monkeypatch, coordinator):
    class BadOptions:
        def get(self, _key, _default=None):
            raise RuntimeError("bad opt")

    coordinator.config_entry.options = BadOptions()
    stats = {"123": {"box_prms": {}}}

    await coordinator._maybe_fill_config_nodes_from_cloud(stats)


@pytest.mark.asyncio
async def test_maybe_fill_config_nodes_stats_keys_error(monkeypatch, coordinator):
    class BadStats(dict):
        def keys(self):
            raise RuntimeError("bad keys")

    coordinator.config_entry.options["box_id"] = "not_a_number"
    stats = BadStats({"foo": {"box_prms": {}}})

    await coordinator._maybe_fill_config_nodes_from_cloud(stats)


@pytest.mark.asyncio
async def test_maybe_fill_config_nodes_box_not_dict(monkeypatch, coordinator):
    coordinator.config_entry.options["box_id"] = "123"
    stats = {"123": "bad"}

    await coordinator._maybe_fill_config_nodes_from_cloud(stats)


@pytest.mark.asyncio
async def test_maybe_fill_config_nodes_no_missing_nodes(monkeypatch, coordinator):
    coordinator.config_entry.options["box_id"] = "123"
    stats = {
        "123": {
            "box_prms": {"mode": 1},
            "batt_prms": {"x": 1},
            "invertor_prm1": {"x": 1},
            "invertor_prms": {"x": 1},
            "boiler_prms": {"x": 1},
        }
    }

    await coordinator._maybe_fill_config_nodes_from_cloud(stats)


@pytest.mark.asyncio
async def test_maybe_fill_config_nodes_cloud_fetch_error(monkeypatch, coordinator):
    coordinator.config_entry.options["box_id"] = "123"
    stats = {"123": {"box_prms": {}, "batt_prms": {}}}
    coordinator.api.get_stats = AsyncMock(side_effect=RuntimeError("boom"))

    await coordinator._maybe_fill_config_nodes_from_cloud(stats)


@pytest.mark.asyncio
async def test_maybe_fill_config_nodes_cloud_invalid(monkeypatch, coordinator):
    coordinator.config_entry.options["box_id"] = "123"
    stats = {"123": {"box_prms": {}, "batt_prms": {}}}
    coordinator.api.get_stats = AsyncMock(return_value="bad")

    await coordinator._maybe_fill_config_nodes_from_cloud(stats)


def test_should_update_extended_naive_last_update(monkeypatch, coordinator):
    fixed_now = datetime(2025, 1, 1, 10, 0)
    coordinator.extended_interval = 60
    coordinator._last_extended_update = datetime(2025, 1, 1, 9, 58)

    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.now",
        lambda: fixed_now,
    )

    assert coordinator._should_update_extended() is True


@pytest.mark.asyncio
async def test_update_battery_forecast_config_entry_options_error(
    monkeypatch, coordinator
):
    class BadOptions:
        def get(self, _key, _default=None):
            raise RuntimeError("bad opt")

    coordinator.config_entry.options = BadOptions()
    coordinator.data = {"123": {"batt_bat_c": 10}}

    await coordinator._update_battery_forecast()

    assert coordinator.battery_forecast_data is None


@pytest.mark.asyncio
async def test_update_battery_forecast_exception(monkeypatch, coordinator):
    class DummySensor:
        def __init__(self, *_a, **_k):
            raise RuntimeError("boom")

    coordinator.data = {"123": {"batt_bat_c": 10}}
    coordinator.config_entry.options["box_id"] = "123"

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.OigCloudBatteryForecastSensor",
        DummySensor,
    )

    await coordinator._update_battery_forecast()

    assert coordinator.battery_forecast_data is None


def test_utcnow_fallback(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.dt_util.utcnow",
        None,
        raising=False,
    )
    now = OigCloudCoordinator._utcnow()
    assert now.tzinfo is not None


@pytest.mark.asyncio
async def test_init_pricing_cache_load_error_next_day(monkeypatch):
    class DummyOteApi:
        def __init__(self, cache_path=None):
            self.cache_path = cache_path
            self._last_data = None

        async def async_load_cached_spot_prices(self):
            raise RuntimeError("boom")

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 1, 15, 0, tzinfo=tz)

    tasks = []

    def _async_create_task(coro):
        tasks.append(coro)
        return coro

    hass = SimpleNamespace(
        config=SimpleNamespace(path=lambda *_a: "/tmp/ote_cache.json"),
        async_create_task=_async_create_task,
        loop=SimpleNamespace(call_later=lambda *_a, **_k: None),
    )

    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": True, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ote_api.OteApi", DummyOteApi
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.core.coordinator.datetime", FakeDatetime
    )
    monkeypatch.setattr(
        OigCloudCoordinator, "_schedule_hourly_fallback", lambda self: None
    )
    monkeypatch.setattr(
        OigCloudCoordinator, "_schedule_spot_price_update", lambda self: None
    )
    monkeypatch.setattr(
        OigCloudCoordinator, "_update_spot_prices", AsyncMock()
    )

    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)
    assert coordinator.ote_api is not None
    await tasks[0]
    for task in tasks:
        if hasattr(task, "close"):
            task.close()


def test_init_pricing_ote_api_error(monkeypatch):
    class DummyOteApi:
        def __init__(self, *_a, **_k):
            raise RuntimeError("fail")

    hass = SimpleNamespace(
        config=SimpleNamespace(path=lambda *_a: "/tmp/ote_cache.json"),
        async_create_task=lambda coro: coro,
        loop=SimpleNamespace(call_later=lambda *_a, **_k: None),
    )
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": True, "enable_chmu_warnings": False}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ote_api.OteApi", DummyOteApi
    )

    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    assert coordinator.ote_api is None


def test_init_chmu_api_error(monkeypatch):
    class DummyChmuApi:
        def __init__(self):
            raise RuntimeError("fail")

    hass = SimpleNamespace(
        config=SimpleNamespace(path=lambda *_a: "/tmp/ote_cache.json"),
        async_create_task=lambda coro: coro,
        loop=SimpleNamespace(call_later=lambda *_a, **_k: None),
    )
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "entry"
    entry.options = {"enable_pricing": False, "enable_chmu_warnings": True}

    monkeypatch.setattr(
        "homeassistant.helpers.frame.report_usage", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.api_chmu.ChmuApi", DummyChmuApi
    )

    coordinator = OigCloudCoordinator(hass, Mock(), config_entry=entry)

    assert coordinator.chmu_api is None


@pytest.mark.asyncio
async def test_async_config_entry_first_refresh_cache_load(monkeypatch, coordinator):
    class DummyStore:
        async def async_load(self):
            return {"data": {"foo": {"bar": 1}}}

    monkeypatch.setattr(coordinator, "_cache_store", DummyStore())
    monkeypatch.setattr(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.async_config_entry_first_refresh",
        AsyncMock(),
    )

    await coordinator.async_config_entry_first_refresh()

    assert coordinator.data["foo"]["bar"] == 1


@pytest.mark.asyncio
async def test_async_config_entry_first_refresh_cache_load_error(monkeypatch, coordinator):
    class DummyStore:
        async def async_load(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(coordinator, "_cache_store", DummyStore())
    monkeypatch.setattr(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.async_config_entry_first_refresh",
        AsyncMock(),
    )

    await coordinator.async_config_entry_first_refresh()


@pytest.mark.asyncio
async def test_async_config_entry_first_refresh_failure_with_cache(
    monkeypatch, coordinator
):
    class DummyStore:
        async def async_load(self):
            return {"data": {"foo": {"bar": 1}}}

    async def _raise(*_a, **_k):
        raise RuntimeError("fail")

    monkeypatch.setattr(coordinator, "_cache_store", DummyStore())
    monkeypatch.setattr(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.async_config_entry_first_refresh",
        _raise,
    )

    await coordinator.async_config_entry_first_refresh()

    assert coordinator.last_update_success is True


@pytest.mark.asyncio
async def test_async_config_entry_first_refresh_failure_no_cache(
    monkeypatch, coordinator
):
    async def _raise(*_a, **_k):
        raise RuntimeError("fail")

    monkeypatch.setattr(coordinator, "_cache_store", None)
    monkeypatch.setattr(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.async_config_entry_first_refresh",
        _raise,
    )

    with pytest.raises(RuntimeError):
        await coordinator.async_config_entry_first_refresh()
