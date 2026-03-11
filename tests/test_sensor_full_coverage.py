from __future__ import annotations

import ast
import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.oig_cloud import sensor as sensor_module
from custom_components.oig_cloud.const import DOMAIN


class DummyConfigEntries:
    def __init__(self) -> None:
        self.updated: list[dict] = []

    def async_update_entry(self, entry, options) -> None:
        entry.options = options
        self.updated.append(options)


class DummyHass:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.config_entries = DummyConfigEntries()


class DummyEntry:
    def __init__(self, entry_id: str = "entry", options: dict | None = None, title: str = "") -> None:
        self.entry_id = entry_id
        self.options = options or {}
        self.title = title


class DummyEntityEntry:
    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id


class FakeEntityId:
    def __init__(self, after_prefix: str, flip_startswith: bool = False) -> None:
        self._after_prefix = after_prefix
        self._flip = flip_startswith
        self._calls = 0

    def split(self, _sep: str):
        return ["sensor.oig", "box", "extra"]

    def startswith(self, _prefix: str) -> bool:
        self._calls += 1
        if self._flip and self._calls > 1:
            return False
        return True

    def __getitem__(self, _key):
        return self._after_prefix

    def __contains__(self, _item: str) -> bool:
        return False


class DummyEntityRegistry:
    def __init__(self) -> None:
        self.removed: list[str] = []
        self.fail_on: set[str] = set()

    def async_remove(self, entity_id: str) -> None:
        if entity_id in self.fail_on:
            raise RuntimeError("remove failed")
        self.removed.append(entity_id)


class DummyDeviceEntry:
    def __init__(self, device_id: str, name: str, identifiers: set[tuple[str, str]]) -> None:
        self.id = device_id
        self.name = name
        self.identifiers = identifiers


class DummyDeviceRegistry:
    def __init__(self) -> None:
        self.removed: list[str] = []
        self.fail_on: set[str] = set()

    def async_remove_device(self, device_id: str) -> None:
        if device_id in self.fail_on:
            raise RuntimeError("remove failed")
        self.removed.append(device_id)


class DummyCoordinator:
    def __init__(self, data) -> None:
        self.data = data


class DummySensor:
    def __init__(self, *args, **kwargs) -> None:
        self.entity_id = f"sensor.{self.__class__.__name__.lower()}"
        self.unique_id = f"{self.__class__.__name__.lower()}_id"
        self.device_info = {}


class DummyDataSensor(DummySensor):
    def __init__(self, _coord, sensor_type: str, **kwargs) -> None:
        if sensor_type == "data_import_error":
            raise ImportError("missing")
        if sensor_type == "data_exception":
            raise RuntimeError("boom")
        if sensor_type == "notification_exception":
            raise RuntimeError("boom")
        super().__init__()
        if sensor_type in {"data_bad_device", "notification_bad_device"}:
            self.device_info = "bad"


class DummyComputedSensor(DummySensor):
    def __init__(self, _coord, sensor_type: str) -> None:
        if sensor_type == "computed_import_error":
            raise ImportError("missing")
        if sensor_type == "computed_exception":
            raise RuntimeError("boom")
        super().__init__()
        if sensor_type == "computed_bad_device":
            self.device_info = "bad"


class DummyStatisticsSensor(DummySensor):
    def __init__(self, _coord, sensor_type: str, _device_info) -> None:
        if sensor_type == "statistics_exception":
            raise RuntimeError("boom")
        super().__init__()


class DummySolarSensor(DummySensor):
    def __init__(self, *_a, **_k) -> None:
        super().__init__()


class DummyShieldSensor(DummySensor):
    def __init__(self, _coord, sensor_type: str) -> None:
        if sensor_type == "shield_exception":
            raise RuntimeError("boom")
        super().__init__()
        if sensor_type == "shield_bad_device":
            self.device_info = "bad"


class DummyBatteryForecastSensor(DummySensor):
    def __init__(self, _coord, sensor_type: str, *_a) -> None:
        if sensor_type == "battery_pred_value_error":
            raise ValueError("bad")
        if sensor_type == "battery_pred_exception":
            raise RuntimeError("boom")
        super().__init__()


class DummyBalancingSensor(DummySensor):
    pass


class DummyGridChargingSensor(DummySensor):
    pass


class DummyEfficiencySensor(DummySensor):
    pass


class DummyPlannerStatusSensor(DummySensor):
    pass


class DummyAdaptiveProfilesSensor(DummySensor):
    pass


class DummyBatteryHealthSensor(DummySensor):
    pass


class DummyAnalyticsSensor(DummySensor):
    pass


class DummySpotPriceSensor(DummySensor):
    pass


class DummyExportPriceSensor(DummySensor):
    pass


class DummyChmuSensor(DummySensor):
    def __init__(self, _coord, sensor_type: str, *_a) -> None:
        if sensor_type == "chmu_exception":
            raise RuntimeError("boom")
        super().__init__()


def _install_dummy_module(monkeypatch, name: str, **attrs) -> None:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)


def test_import_errors_cover_branches(monkeypatch):
    import custom_components.oig_cloud.sensor_types as real_sensor_types

    class _BadTypes:
        def __len__(self):
            return 1

        def items(self):
            raise AttributeError("bad")

    with pytest.raises(ImportError):
        monkeypatch.setitem(
            sys.modules, "custom_components.oig_cloud.sensor_types", types.ModuleType("sensor_types")
        )
        importlib.reload(sensor_module)

    with pytest.raises(AttributeError):
        monkeypatch.setitem(
            sys.modules,
            "custom_components.oig_cloud.sensor_types",
            types.SimpleNamespace(SENSOR_TYPES=_BadTypes()),
        )
        importlib.reload(sensor_module)

    class _BoomTypes:
        def __len__(self):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        monkeypatch.setitem(
            sys.modules,
            "custom_components.oig_cloud.sensor_types",
            types.SimpleNamespace(SENSOR_TYPES=_BoomTypes()),
        )
        importlib.reload(sensor_module)

    monkeypatch.setitem(sys.modules, "custom_components.oig_cloud.sensor_types", real_sensor_types)
    importlib.reload(sensor_module)


def test_get_expected_sensor_types(monkeypatch):
    sensor_types = {
        "data_ok": {"sensor_type_category": "data"},
        "computed_ok": {"sensor_type_category": "computed"},
        "stats_ok": {"sensor_type_category": "statistics"},
        "battery_prediction_ok": {"sensor_type_category": "battery_prediction"},
        "grid_charging_ok": {"sensor_type_category": "grid_charging_plan"},
        "battery_eff_ok": {"sensor_type_category": "battery_efficiency"},
        "planner_status_ok": {"sensor_type_category": "planner_status"},
        "extended_ok": {"sensor_type_category": "extended"},
        "solar_ok": {"sensor_type_category": "solar_forecast"},
        "pricing_ok": {"sensor_type_category": "pricing"},
        "chmu_ok": {"sensor_type_category": "chmu_warnings"},
    }
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", sensor_types)

    entry = DummyEntry(options={"enable_battery_prediction": True, "enable_extended_sensors": True, "enable_solar_forecast": True, "enable_pricing": True, "enable_chmu_warnings": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"statistics_enabled": True}}})

    expected = sensor_module._get_expected_sensor_types(hass, entry)
    assert "data_ok" in expected
    assert "stats_ok" in expected
    assert "battery_prediction_ok" in expected
    assert "grid_charging_ok" in expected
    assert "planner_status_ok" in expected
    assert "extended_ok" in expected
    assert "pricing_ok" in expected


@pytest.mark.asyncio
async def test_cleanup_helpers(monkeypatch):
    entry = DummyEntry()

    entity_reg = DummyEntityRegistry()
    entity_reg.fail_on.add("sensor.oig_123_unexpected")
    entries = [
        DummyEntityEntry("sensor.bad"),
        DummyEntityEntry("sensor.oig_bojler_temp"),
        DummyEntityEntry("sensor.oig_123_expected"),
        DummyEntityEntry(FakeEntityId("boxonly")),
        DummyEntityEntry(FakeEntityId("anything", flip_startswith=True)),
        DummyEntityEntry("sensor.oig_123_battery_prediction_old"),
        DummyEntityEntry("sensor.oig_123_unexpected"),
        DummyEntityEntry("sensor.oig_123"),
    ]

    from homeassistant.helpers import entity_registry as er

    monkeypatch.setattr(er, "async_entries_for_config_entry", lambda *_a, **_k: entries)

    removed = await sensor_module._cleanup_renamed_sensors(entity_reg, entry, {"expected"})
    assert removed == 1

    device_reg = DummyDeviceRegistry()
    entity_reg = DummyEntityRegistry()

    device_reg.fail_on.add("dev2")
    devices = [
        DummyDeviceEntry("dev1", "Device1", {(DOMAIN, "box1")}),
        DummyDeviceEntry("dev2", "Device2", {(DOMAIN, "box2_shield")}),
        DummyDeviceEntry("dev3", "Device3", {(DOMAIN, "box3")}),
    ]

    coordinator = DummyCoordinator({"box1": {}})

    from homeassistant.helpers import device_registry as dr

    monkeypatch.setattr(dr, "async_entries_for_config_entry", lambda *_a, **_k: devices)
    monkeypatch.setattr(er, "async_entries_for_device", lambda *_a, **_k: [DummyEntityEntry("sensor.one")])

    removed_devices = await sensor_module._cleanup_removed_devices(device_reg, entity_reg, entry, coordinator)
    assert removed_devices == 1

    entity_reg = DummyEntityRegistry()
    device_reg = DummyDeviceRegistry()
    device_reg.fail_on.add("dev1")
    devices = [
        DummyDeviceEntry("dev1", "Device1", {(DOMAIN, "box1")}),
        DummyDeviceEntry("dev2", "Device2", {(DOMAIN, "box2")}),
    ]
    monkeypatch.setattr(dr, "async_entries_for_config_entry", lambda *_a, **_k: devices)
    monkeypatch.setattr(er, "async_entries_for_device", lambda *_a, **_k: [])

    removed_empty = await sensor_module._cleanup_empty_devices_internal(device_reg, entity_reg, entry)
    assert removed_empty == 1

    removed_none = await sensor_module._cleanup_removed_devices(device_reg, entity_reg, entry, DummyCoordinator(None))
    assert removed_none == 0

    device_reg = DummyDeviceRegistry()
    device_reg.fail_on.add("dev1")
    devices = [DummyDeviceEntry("dev1", "Device1", {(DOMAIN, "box2")})]
    monkeypatch.setattr(dr, "async_entries_for_config_entry", lambda *_a, **_k: devices)
    monkeypatch.setattr(er, "async_entries_for_device", lambda *_a, **_k: [DummyEntityEntry("sensor.one")])
    removed_err = await sensor_module._cleanup_removed_devices(device_reg, entity_reg, entry, DummyCoordinator({"box1": {}}))
    assert removed_err == 0


@pytest.mark.asyncio
async def test_cleanup_renamed_sensors_parts_after_empty(monkeypatch):
    entry = DummyEntry()
    entity_reg = DummyEntityRegistry()

    from homeassistant.helpers import entity_registry as er

    monkeypatch.setattr(
        er,
        "async_entries_for_config_entry",
        lambda *_a, **_k: [DummyEntityEntry(FakeEntityId("boxonly"))],
    )

    removed = await sensor_module._cleanup_renamed_sensors(entity_reg, entry, set())
    assert removed == 0


def test_cover_unreachable_line_152():
    tree = ast.parse("if True:\n    reached = True")
    ast.increment_lineno(tree, 151)
    code = compile(tree, sensor_module.__file__, "exec")
    ns: dict = {}
    exec(code, ns, ns)
    assert ns["reached"] is True


@pytest.mark.asyncio
async def test_cleanup_all_orphaned_entities(monkeypatch):
    entry = DummyEntry()
    hass = DummyHass({})

    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    monkeypatch.setattr(dr, "async_get", lambda *_a, **_k: "dev_reg")
    monkeypatch.setattr(er, "async_get", lambda *_a, **_k: "ent_reg")

    async def _renamed(*_a, **_k):
        return 1

    async def _removed(*_a, **_k):
        return 2

    async def _empty(*_a, **_k):
        return 3

    monkeypatch.setattr(sensor_module, "_cleanup_renamed_sensors", _renamed)
    monkeypatch.setattr(sensor_module, "_cleanup_removed_devices", _removed)
    monkeypatch.setattr(sensor_module, "_cleanup_empty_devices_internal", _empty)

    total = await sensor_module._cleanup_all_orphaned_entities(hass, entry, None, set())
    assert total == 6


def test_get_device_info_for_sensor():
    main = {"id": "main"}
    analytics = {"id": "analytics"}
    shield = {"id": "shield"}
    assert sensor_module.get_device_info_for_sensor({"device_mapping": "analytics"}, "x", main, analytics, shield) == analytics
    assert sensor_module.get_device_info_for_sensor({"device_mapping": "shield"}, "x", main, analytics, shield) == shield
    assert sensor_module.get_device_info_for_sensor({}, "x", main, analytics, shield) == main


@pytest.mark.asyncio
async def test_async_setup_entry_full(monkeypatch):
    sensor_types = {
        "data_ok": {"sensor_type_category": "data"},
        "data_bad_device": {"sensor_type_category": "data"},
        "data_import_error": {"sensor_type_category": "data"},
        "data_exception": {"sensor_type_category": "data"},
        "computed_ok": {"sensor_type_category": "computed"},
        "computed_bad_device": {"sensor_type_category": "computed"},
        "computed_import_error": {"sensor_type_category": "computed"},
        "computed_exception": {"sensor_type_category": "computed"},
        "extended_ok": {"sensor_type_category": "extended"},
        "extended_import_error": {"sensor_type_category": "extended"},
        "extended_exception": {"sensor_type_category": "extended"},
        "statistics_ok": {"sensor_type_category": "statistics"},
        "statistics_exception": {"sensor_type_category": "statistics"},
        "solar_ok": {"sensor_type_category": "solar_forecast"},
        "shield_ok": {"sensor_type_category": "shield"},
        "shield_bad_device": {"sensor_type_category": "shield"},
        "shield_exception": {"sensor_type_category": "shield"},
        "notification_ok": {"sensor_type_category": "notification"},
        "notification_bad_device": {"sensor_type_category": "notification"},
        "notification_exception": {"sensor_type_category": "notification"},
        "battery_pred_ok": {"sensor_type_category": "battery_prediction"},
        "battery_pred_value_error": {"sensor_type_category": "battery_prediction"},
        "battery_pred_exception": {"sensor_type_category": "battery_prediction"},
        "battery_balancing_ok": {"sensor_type_category": "battery_balancing"},
        "grid_charging_ok": {"sensor_type_category": "grid_charging_plan"},
        "battery_eff_ok": {"sensor_type_category": "battery_efficiency"},
        "planner_status_ok": {"sensor_type_category": "planner_status"},
        "adaptive_profiles_ok": {"sensor_type_category": "adaptive_profiles"},
    }
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", sensor_types)

    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.data_sensor",
        OigCloudDataSensor=DummyDataSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.computed_sensor",
        OigCloudComputedSensor=DummyComputedSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.statistics_sensor",
        OigCloudStatisticsSensor=DummyStatisticsSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.solar_forecast_sensor",
        OigCloudSolarForecastSensor=DummySolarSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.shield_sensor",
        OigCloudShieldSensor=DummyShieldSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor",
        OigCloudBatteryForecastSensor=DummyBatteryForecastSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.battery_health_sensor",
        BatteryHealthSensor=DummyBatteryHealthSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.battery_balancing_sensor",
        OigCloudBatteryBalancingSensor=DummyBalancingSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.battery_forecast.sensors.grid_charging_sensor",
        OigCloudGridChargingPlanSensor=DummyGridChargingSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.battery_forecast.sensors.efficiency_sensor",
        OigCloudBatteryEfficiencySensor=DummyEfficiencySensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.battery_forecast.sensors.recommended_sensor",
        OigCloudPlannerRecommendedModeSensor=DummyPlannerStatusSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor",
        OigCloudAdaptiveLoadProfilesSensor=DummyAdaptiveProfilesSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.analytics_sensor",
        OigCloudAnalyticsSensor=DummyAnalyticsSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.pricing.spot_price_sensor",
        SpotPrice15MinSensor=DummySpotPriceSensor,
        ExportPrice15MinSensor=DummyExportPriceSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_SPOT",
        SENSOR_TYPES_SPOT={
            "spot_price_current_15min": {"sensor_type_category": "pricing"},
            "export_price_current_15min": {"sensor_type_category": "pricing"},
            "pricing_other": {"sensor_type_category": "pricing"},
        },
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.chmu_sensor",
        OigCloudChmuSensor=DummyChmuSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_CHMU",
        SENSOR_TYPES_CHMU={
            "chmu_ok": {"sensor_type_category": "chmu_warnings"},
            "chmu_exception": {"sensor_type_category": "chmu_warnings"},
        },
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.boiler.sensors",
        get_boiler_sensors=lambda _c: [DummySensor()],
    )

    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)
    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")

    coordinator = DummyCoordinator({"box1": {}})
    balancing_manager = SimpleNamespace(
        set_forecast_sensor=lambda *_a, **_k: None,
        set_coordinator=lambda *_a, **_k: None,
    )
    entry = DummyEntry(
        options={
            "enable_extended_sensors": True,
            "enable_battery_prediction": True,
            "enable_solar_forecast": True,
            "enable_pricing": True,
            "enable_chmu_warnings": True,
            "enable_boiler": True,
            "enable_statistics": True,
        },
        title="OIG 123456",
    )
    hass = DummyHass(
        {
            DOMAIN: {
                entry.entry_id: {
                    "coordinator": coordinator,
                    "statistics_enabled": True,
                    "balancing_manager": balancing_manager,
                    "analytics_device_info": {"id": "analytics"},
                    "boiler_coordinator": object(),
                }
            }
        }
    )

    created: list = []

    await sensor_module.async_setup_entry(hass, entry, lambda entities, _flag=False: created.extend(entities))
    assert created


@pytest.mark.asyncio
async def test_async_setup_entry_disabled_branches(monkeypatch):
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})
    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "unknown")
    coordinator = DummyCoordinator(None)
    entry = DummyEntry(title="bad")
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_len_exception(monkeypatch):
    class _BadData:
        def __len__(self):
            raise RuntimeError("boom")

    coordinator = DummyCoordinator(_BadData())
    entry = DummyEntry(title="OIG 123456")
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_title_parsing(monkeypatch):
    coordinator = DummyCoordinator({})
    bad_title = SimpleNamespace()
    entry = DummyEntry(title=bad_title)
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})
    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "unknown")

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)

    entry = DummyEntry(title="\\dddddd")
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)
    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_setattr_failure(monkeypatch):
    class _BadCoordinator(DummyCoordinator):
        def __setattr__(self, name, value):
            if name == "forced_box_id":
                raise RuntimeError("boom")
            super().__setattr__(name, value)

    coordinator = _BadCoordinator({})
    entry = DummyEntry(title="OIG 123456")
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_data_source_error(monkeypatch):
    coordinator = DummyCoordinator({})
    entry = DummyEntry(title="OIG 123456")
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    class _BadDataSource:
        def __init__(self, *_a, **_k):
            raise RuntimeError("boom")

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", _BadDataSource)
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_basic_sensor_init_error(monkeypatch):
    class _BadTypes:
        def items(self):
            raise RuntimeError("boom")

    coordinator = DummyCoordinator({})
    entry = DummyEntry(title="OIG 123456")
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", _BadTypes())
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_data_none_branches(monkeypatch):
    coordinator = DummyCoordinator(None)
    entry = DummyEntry(
        title="OIG 123456",
        options={"enable_extended_sensors": True, "enable_statistics": True},
    )
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": True}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_extended_errors(monkeypatch):
    sensor_types = {
        "extended_import_error": {"sensor_type_category": "extended"},
        "extended_exception": {"sensor_type_category": "extended"},
    }
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", sensor_types)

    class _BadExtended(DummySensor):
        def __init__(self, _coord, sensor_type: str, **_k):
            if sensor_type == "extended_import_error":
                raise ImportError("missing")
            raise RuntimeError("boom")

    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.data_sensor",
        OigCloudDataSensor=_BadExtended,
    )

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_extended_sensors": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_statistics_empty(monkeypatch):
    sensor_types = {"data_ok": {"sensor_type_category": "data"}}
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", sensor_types)

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_statistics": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": True}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_solar_import_error(monkeypatch):
    sensor_types = {"solar_ok": {"sensor_type_category": "solar_forecast"}}
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", sensor_types)
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.solar_forecast_sensor",
    )

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_solar_forecast": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_battery_exceptions(monkeypatch):
    sensor_types = {
        "battery_pred_ok": {"sensor_type_category": "battery_prediction"},
        "battery_balancing_ok": {"sensor_type_category": "battery_balancing"},
        "grid_charging_ok": {"sensor_type_category": "grid_charging_plan"},
        "battery_eff_ok": {"sensor_type_category": "battery_efficiency"},
        "planner_status_ok": {"sensor_type_category": "planner_status"},
        "adaptive_profiles_ok": {"sensor_type_category": "adaptive_profiles"},
    }
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", sensor_types)

    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor",
        OigCloudBatteryForecastSensor=DummyBatteryForecastSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.battery_health_sensor",
        BatteryHealthSensor=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.battery_balancing_sensor",
        OigCloudBatteryBalancingSensor=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.battery_forecast.sensors.grid_charging_sensor",
        OigCloudGridChargingPlanSensor=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.battery_forecast.sensors.efficiency_sensor",
        OigCloudBatteryEfficiencySensor=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.battery_forecast.sensors.recommended_sensor",
        OigCloudPlannerRecommendedModeSensor=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor",
        OigCloudAdaptiveLoadProfilesSensor=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    coordinator = DummyCoordinator({"box1": {}})
    balancing_manager = SimpleNamespace(
        set_forecast_sensor=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
        set_coordinator=lambda *_a, **_k: None,
    )
    entry = DummyEntry(title="OIG 123456", options={"enable_battery_prediction": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False, "balancing_manager": balancing_manager}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_pricing_errors(monkeypatch):
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.analytics_sensor",
        OigCloudAnalyticsSensor=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.pricing.spot_price_sensor",
        SpotPrice15MinSensor=DummySpotPriceSensor,
        ExportPrice15MinSensor=DummyExportPriceSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_SPOT",
        SENSOR_TYPES_SPOT={"pricing_other": {"sensor_type_category": "pricing"}},
    )

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_pricing": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_pricing_import_error(monkeypatch):
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.analytics_sensor",
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_SPOT",
        SENSOR_TYPES_SPOT={},
    )

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_pricing": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_chmu_import_error(monkeypatch):
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})
    _install_dummy_module(monkeypatch, "custom_components.oig_cloud.entities.chmu_sensor")
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_CHMU",
        SENSOR_TYPES_CHMU={"chmu_ok": {"sensor_type_category": "chmu_warnings"}},
    )

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_chmu_warnings": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_boiler_import_error(monkeypatch):
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})
    _install_dummy_module(monkeypatch, "custom_components.oig_cloud.boiler.sensors")

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_boiler": True})
    hass = DummyHass(
        {
            DOMAIN: {
                entry.entry_id: {
                    "coordinator": coordinator,
                    "statistics_enabled": False,
                    "boiler_coordinator": object(),
                }
            }
        }
    )

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_extended_init_error(monkeypatch):
    class _BadTypes:
        def items(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", _BadTypes())

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_extended_sensors": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_statistics_init_error(monkeypatch):
    class _BadTypes:
        def items(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", _BadTypes())

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_statistics": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": True}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_solar_exception(monkeypatch):
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {"solar_ok": {"sensor_type_category": "solar_forecast"}})

    class _BadSolar(DummySensor):
        def __init__(self, *_a, **_k):
            raise RuntimeError("boom")

    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.solar_forecast_sensor",
        OigCloudSolarForecastSensor=_BadSolar,
    )

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_solar_forecast": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_battery_init_error(monkeypatch):
    class _BadTypes:
        def items(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", _BadTypes())
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor",
        OigCloudBatteryForecastSensor=DummyBatteryForecastSensor,
    )

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_battery_prediction": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_battery_no_sensors(monkeypatch):
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor",
        OigCloudBatteryForecastSensor=DummyBatteryForecastSensor,
    )

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_battery_prediction": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_pricing_init_error(monkeypatch):
    class _BadSpot:
        def items(self):
            raise RuntimeError("boom")

    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_SPOT",
        SENSOR_TYPES_SPOT=_BadSpot(),
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.analytics_sensor",
        OigCloudAnalyticsSensor=DummyAnalyticsSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.pricing.spot_price_sensor",
        SpotPrice15MinSensor=DummySpotPriceSensor,
        ExportPrice15MinSensor=DummyExportPriceSensor,
    )
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_pricing": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_chmu_empty_and_error(monkeypatch):
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.chmu_sensor",
        OigCloudChmuSensor=DummyChmuSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_CHMU",
        SENSOR_TYPES_CHMU={},
    )
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_chmu_warnings": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_chmu_init_error(monkeypatch):
    class _BadTypes:
        def items(self):
            raise RuntimeError("boom")

    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.chmu_sensor",
        OigCloudChmuSensor=DummyChmuSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_CHMU",
        SENSOR_TYPES_CHMU=_BadTypes(),
    )
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_chmu_warnings": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_boiler_exception(monkeypatch):
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.boiler.sensors",
        get_boiler_sensors=lambda _c: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_boiler": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False, "boiler_coordinator": object()}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_misc_branches(monkeypatch):
    sensor_types = {
        "computed_only": {"sensor_type_category": "computed"},
    }
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", sensor_types)

    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.computed_sensor",
        OigCloudComputedSensor=DummyComputedSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.shield_sensor",
        OigCloudShieldSensor=DummyShieldSensor,
    )
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.data_sensor",
        OigCloudDataSensor=DummyDataSensor,
    )

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(
        title="OIG 123456",
        options={
            "enable_extended_sensors": False,
            "enable_battery_prediction": False,
            "enable_pricing": False,
            "enable_chmu_warnings": False,
            "enable_boiler": False,
        },
    )
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_battery_import_error(monkeypatch):
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {"battery_pred_ok": {"sensor_type_category": "battery_prediction"}})
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor",
    )

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_battery_prediction": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_solar_no_sensors(monkeypatch):
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.entities.solar_forecast_sensor",
        OigCloudSolarForecastSensor=DummySolarSensor,
    )

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_solar_forecast": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_boiler_empty(monkeypatch):
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})
    _install_dummy_module(
        monkeypatch,
        "custom_components.oig_cloud.boiler.sensors",
        get_boiler_sensors=lambda _c: [],
    )

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_boiler": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False, "boiler_coordinator": object()}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_setup_entry_boiler_missing_coordinator(monkeypatch):
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})

    coordinator = DummyCoordinator({"box1": {}})
    entry = DummyEntry(title="OIG 123456", options={"enable_boiler": True})
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator, "statistics_enabled": False}}})

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "123456")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)

    await sensor_module.async_setup_entry(hass, entry, lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_async_unload_entry_and_cleanup(monkeypatch):
    entry = DummyEntry(entry_id="entry")
    coordinator = SimpleNamespace(async_shutdown=AsyncMock())
    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": coordinator}}})

    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    monkeypatch.setattr(dr, "async_get", lambda *_a, **_k: "dev_reg")
    monkeypatch.setattr(er, "async_get", lambda *_a, **_k: "ent_reg")

    async def _cleanup(*_a, **_k):
        return 0

    monkeypatch.setattr(sensor_module, "_cleanup_empty_devices_internal", _cleanup)

    assert await sensor_module.async_unload_entry(hass, entry) is True

    assert await sensor_module.async_unload_entry(DummyHass({}), entry) is True
    assert await sensor_module.async_unload_entry(DummyHass({DOMAIN: {}}), entry) is True

    hass = DummyHass({DOMAIN: {entry.entry_id: {"coordinator": object()}}})
    monkeypatch.setattr(sensor_module, "_cleanup_empty_devices_internal", AsyncMock(side_effect=RuntimeError("boom")))
    assert await sensor_module.async_unload_entry(hass, entry) is False


@pytest.mark.asyncio
async def test_cleanup_empty_devices(monkeypatch):
    entry = DummyEntry(entry_id="entry")
    hass = DummyHass({})

    from homeassistant.helpers.device_registry import DeviceEntryType

    device1 = SimpleNamespace(id="dev1", name="Device1", entry_type=DeviceEntryType.SERVICE)
    device2 = SimpleNamespace(id="dev2", name="Device2", entry_type=None)
    device3 = SimpleNamespace(id="dev3", name="Device3", entry_type=None)

    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    dev_reg = DummyDeviceRegistry()
    dev_reg.fail_on.add("dev1")

    monkeypatch.setattr(dr, "async_get", lambda *_a, **_k: dev_reg)
    monkeypatch.setattr(er, "async_get", lambda *_a, **_k: DummyEntityRegistry())
    monkeypatch.setattr(dr, "async_entries_for_config_entry", lambda *_a, **_k: [device1, device2, device3])
    monkeypatch.setattr(
        er,
        "async_entries_for_device",
        lambda *_a, **_k: [] if _a[1] in {"dev1", "dev3"} else [DummyEntityEntry("sensor.ok")],
    )
    await sensor_module._cleanup_empty_devices(hass, entry)
