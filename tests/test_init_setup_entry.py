from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import custom_components.oig_cloud as init_module
from custom_components.oig_cloud.const import CONF_PASSWORD, CONF_USERNAME, DOMAIN
from homeassistant.exceptions import ConfigEntryNotReady


class DummyConfigEntries:
    def __init__(self):
        self.updated = []
        self.forwarded = []
        self.unloaded = []

    def async_update_entry(self, entry, options=None):
        entry.options = options or {}
        self.updated.append(entry)

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry, platforms))

    async def async_unload_platforms(self, entry, platforms):
        self.unloaded.append((entry, platforms))
        return True


class DummyHass:
    def __init__(self):
        self.data = {}
        self.states = SimpleNamespace(get=lambda _eid: None)
        self.config_entries = DummyConfigEntries()
        self.loop = None

    def async_create_task(self, coro):
        if hasattr(coro, "close"):
            coro.close()


class DummyEntry:
    def __init__(self, entry_id="entry1", data=None, options=None, title="OIG 123"):
        self.entry_id = entry_id
        self.data = data or {}
        self.options = options or {}
        self.title = title
        self._unload = []
        self._listener = None

    def async_on_unload(self, func):
        self._unload.append(func)
        return func

    def add_update_listener(self, func):
        self._listener = func
        return func


class DummyShield:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.pending = []
        self.queue = []
        self.running = False
        self.telemetry_handler = None

    async def start(self):
        return None

    def get_shield_status(self):
        return {"status": "ok"}

    def get_queue_info(self):
        return {"pending": 0}


class DummyApi:
    def __init__(self, *_args, **_kwargs):
        pass

    async def get_stats(self):
        return {"123": {"actual": {}}}


class DummySessionManager:
    def __init__(self, api):
        self.api = api
        self.ensure_called = False

    async def _ensure_auth(self):
        self.ensure_called = True
        return None

    async def close(self):
        return None


class DummyCoordinator:
    def __init__(self, hass, session_manager, *_args, **_kwargs):
        self.hass = hass
        self.session_manager = session_manager
        self.data = {"123": {}}
        self.api = session_manager

    async def async_config_entry_first_refresh(self):
        return None


class DummyDataSourceController:
    def __init__(self, hass, entry, coordinator, telemetry_store=None):
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.telemetry_store = telemetry_store

    async def async_start(self):
        return None

    async def async_stop(self):
        return None


class DummyNotificationManager:
    def __init__(self, hass, api, base_url):
        self.hass = hass
        self.api = api
        self.base_url = base_url
        self.device_id = None
        self.updated = False

    def set_device_id(self, device_id):
        self.device_id = device_id

    async def update_from_api(self):
        self.updated = True


class DummyModeTracker:
    def __init__(self, hass, box_id):
        self.hass = hass
        self.box_id = box_id
        self.setup_called = False

    async def async_setup(self):
        self.setup_called = True

    async def cleanup(self):
        return None


class RaisingOptions(dict):
    def get(self, key, default=None):
        if key == "box_id":
            raise RuntimeError("boom")
        return super().get(key, default)


@pytest.mark.asyncio
async def test_async_setup_entry_missing_credentials(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )

    hass = DummyHass()
    entry = DummyEntry(data={}, options={})
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is False


@pytest.mark.asyncio
async def test_async_setup_entry_success_local(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={
            "enable_cloud_notifications": False,
            "enable_solar_forecast": False,
            "enable_pricing": False,
            "enable_boiler": False,
            "enable_dashboard": False,
            "balancing_enabled": False,
            "standard_scan_interval": 30,
            "extended_scan_interval": 300,
        },
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    assert "coordinator" in hass.data[DOMAIN][entry.entry_id]
    assert hass.config_entries.forwarded
    assert (
        hass.data[DOMAIN][entry.entry_id]["coordinator"].session_manager.ensure_called
        is False
    )


@pytest.mark.asyncio
async def test_async_setup_entry_success_cloud(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            configured_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            local_available=False,
        ),
    )
    import importlib

    notification_module = importlib.import_module(
        "custom_components.oig_cloud.core.oig_cloud_notification"
    )
    monkeypatch.setattr(
        notification_module,
        "OigNotificationManager",
        DummyNotificationManager,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ModeTransitionTracker",
        DummyModeTracker,
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_call_later",
        lambda *_a, **_k: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={
            "enable_cloud_notifications": True,
            "enable_solar_forecast": False,
            "enable_pricing": False,
            "enable_boiler": False,
            "enable_dashboard": False,
            "balancing_enabled": False,
            "standard_scan_interval": 30,
            "extended_scan_interval": 300,
        },
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    assert "coordinator" in hass.data[DOMAIN][entry.entry_id]
    assert isinstance(
        hass.data[DOMAIN][entry.entry_id]["notification_manager"],
        DummyNotificationManager,
    )
    assert (
        hass.data[DOMAIN][entry.entry_id]["coordinator"].session_manager.ensure_called
        is True
    )


@pytest.mark.asyncio
async def test_async_setup_entry_migrates_spot_prices_flag(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={"enable_spot_prices": True},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    assert hass.config_entries.updated
    assert entry.options.get("enable_pricing") is True
    assert "enable_spot_prices" not in entry.options


@pytest.mark.asyncio
async def test_async_setup_entry_infers_box_id_from_proxy(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    class ProxyState:
        def __init__(self, state):
            self.state = state

    hass = DummyHass()

    def _get_state(entity_id):
        if entity_id == "sensor.oig_local_oig_proxy_proxy_status_box_device_id":
            return ProxyState("456")
        return None

    hass.states = SimpleNamespace(get=_get_state)

    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    assert entry.options.get("box_id") == "456"


@pytest.mark.asyncio
async def test_async_setup_entry_infers_box_id_from_registry(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    class DummyCoordinatorNoData(DummyCoordinator):
        def __init__(self, hass, session_manager, *_args, **_kwargs):
            super().__init__(hass, session_manager, *_args, **_kwargs)
            self.data = {}

    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinatorNoData)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    monkeypatch.setattr(init_module, "_infer_box_id_from_local_entities", lambda *_a: "789")

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    assert entry.options.get("box_id") == "789"


def test_infer_box_id_from_local_entities(monkeypatch):
    class DummyRegistry:
        def __init__(self):
            self.entities = {
                "sensor.oig_local_789_box_prms_mode": SimpleNamespace(
                    entity_id="sensor.oig_local_789_box_prms_mode"
                )
            }

    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_get",
        lambda _hass: DummyRegistry(),
    )

    hass = DummyHass()

    assert init_module._infer_box_id_from_local_entities(hass) is None


@pytest.mark.asyncio
async def test_async_setup_entry_cloud_empty_stats(monkeypatch):
    class DummyApiEmptyStats:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_stats(self):
            return {}

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApiEmptyStats)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            configured_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            local_available=False,
        ),
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_service_shield_failure(monkeypatch):
    def _raise(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", _raise
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    assert hass.data[DOMAIN][entry.entry_id]["service_shield"] is None


@pytest.mark.asyncio
async def test_async_setup_entry_cloud_missing_live_data(monkeypatch):
    class DummyApiMissingActual:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_stats(self):
            return {"123": {"settings": {}}}

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApiMissingActual)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            configured_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            local_available=False,
        ),
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    with pytest.raises(ConfigEntryNotReady):
        await init_module.async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_async_setup_entry_infer_box_id_exception(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()

    def _get_state(_entity_id):
        raise RuntimeError("boom")

    hass.states = SimpleNamespace(get=_get_state)

    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_live_data_check_error(monkeypatch):
    class DummyApiFailStats(DummyApi):
        async def get_stats(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApiFailStats)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            configured_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            local_available=False,
        ),
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={"enable_cloud_notifications": False},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_no_coordinator_data(monkeypatch):
    class DummyCoordinatorNoData(DummyCoordinator):
        def __init__(self, hass, session_manager, *_args, **_kwargs):
            super().__init__(hass, session_manager, *_args, **_kwargs)
            self.data = None

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinatorNoData)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            configured_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            local_available=False,
        ),
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    with pytest.raises(ConfigEntryNotReady):
        await init_module.async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_async_setup_entry_notification_manager_fetch_error(monkeypatch):
    class DummyNotificationManagerFail(DummyNotificationManager):
        async def update_from_api(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            configured_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            local_available=False,
        ),
    )
    import importlib

    notification_module = importlib.import_module(
        "custom_components.oig_cloud.core.oig_cloud_notification"
    )
    monkeypatch.setattr(
        notification_module,
        "OigNotificationManager",
        DummyNotificationManagerFail,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ModeTransitionTracker",
        DummyModeTracker,
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_call_later",
        lambda *_a, **_k: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options=RaisingOptions({"enable_cloud_notifications": True}),
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_pricing_init_error(monkeypatch):
    class DummyOteApi:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    def raising_info(message, *args, **kwargs):
        if "OTE API successfully initialized" in message:
            raise RuntimeError("boom")
        return None

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )
    monkeypatch.setattr("custom_components.oig_cloud.api.ote_api.OteApi", DummyOteApi)
    monkeypatch.setattr(init_module._LOGGER, "info", raising_info)

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={
            "enable_pricing": True,
            "enable_dashboard": False,
            "balancing_enabled": False,
        },
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_optional_modules(monkeypatch):
    class DummyBoilerCoordinator:
        def __init__(self, hass, config):
            self.hass = hass
            self.config = config

        async def async_config_entry_first_refresh(self):
            return None

    class DummyTelemetryStore:
        def __init__(self, hass, box_id):
            self.hass = hass
            self.box_id = box_id

    class DummyBalancingManager:
        def __init__(self, hass, box_id, storage_path, entry):
            self.hass = hass
            self.box_id = box_id
            self.storage_path = storage_path
            self.entry = entry

        async def async_setup(self):
            return None

        async def check_balancing(self):
            return None

    class DummyControllerFail(DummyDataSourceController):
        async def async_start(self):
            raise RuntimeError("boom")

    class DummyShieldWithTelemetry(DummyShield):
        def __init__(self, hass, entry):
            super().__init__(hass, entry)
            self.telemetry_handler = object()

        def _log_telemetry(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShieldWithTelemetry
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyControllerFail)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )
    monkeypatch.setattr(init_module, "BalancingManager", DummyBalancingManager)
    monkeypatch.setattr(
        "custom_components.oig_cloud.boiler.coordinator.BoilerCoordinator",
        DummyBoilerCoordinator,
    )
    import importlib

    telemetry_module = importlib.import_module(
        "custom_components.oig_cloud.core.telemetry_store"
    )
    monkeypatch.setattr(
        telemetry_module,
        "TelemetryStore",
        DummyTelemetryStore,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "123",
    )

    callbacks = {"interval": None}

    def fake_track_interval(_hass, callback, _delta):
        callbacks["interval"] = callback
        return lambda: None

    def fake_call_later(_hass, _delay, callback):
        return callback(None)

    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        fake_track_interval,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_call_later",
        fake_call_later,
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_setup_frontend_panel", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.boiler.api_views.register_boiler_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )

    def raise_api(_hass):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        raise_api,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={
            "enable_solar_forecast": True,
            "enable_pricing": False,
            "enable_boiler": True,
            "enable_dashboard": True,
            "balancing_enabled": True,
        },
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    assert callbacks["interval"] is not None
    await callbacks["interval"](None)


@pytest.mark.asyncio
async def test_async_setup_entry_balancing_disabled_and_missing_manager(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )
    monkeypatch.setattr(init_module, "BalancingManager", None)

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={"balancing_enabled": False},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_boiler_error(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.boiler.coordinator.BoilerCoordinator",
        _raise,
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={"enable_boiler": True},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_telemetry_store_error(monkeypatch):
    class DummyTelemetryStore:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )
    import importlib

    telemetry_module = importlib.import_module(
        "custom_components.oig_cloud.core.telemetry_store"
    )
    monkeypatch.setattr(
        telemetry_module,
        "TelemetryStore",
        DummyTelemetryStore,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda *_coord: "123",
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={"box_id": "123"},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_shield_device_info_resolve_error(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda *_coord: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={"box_id": "abc"},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_notification_manager_no_device(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )

    class DummyCoordinatorNoDigits(DummyCoordinator):
        def __init__(self, hass, session_manager, *_args, **_kwargs):
            super().__init__(hass, session_manager, *_args, **_kwargs)
            self.data = {"abc": {}}

    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinatorNoDigits)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            configured_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            local_available=False,
        ),
    )
    import importlib

    notification_module = importlib.import_module(
        "custom_components.oig_cloud.core.oig_cloud_notification"
    )
    monkeypatch.setattr(
        notification_module,
        "OigNotificationManager",
        DummyNotificationManager,
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={"enable_cloud_notifications": True},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_notification_manager_init_error(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            configured_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            local_available=False,
        ),
    )
    import importlib

    notification_module = importlib.import_module(
        "custom_components.oig_cloud.core.oig_cloud_notification"
    )
    monkeypatch.setattr(
        notification_module,
        "OigNotificationManager",
        _raise,
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={"enable_cloud_notifications": True},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_notification_manager_box_id_error(monkeypatch):
    class Options(dict):
        def get(self, key, default=None):
            if key == "box_id":
                raise RuntimeError("boom")
            return super().get(key, default)

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            configured_mode=init_module.DATA_SOURCE_CLOUD_ONLY,
            local_available=False,
        ),
    )
    import importlib

    notification_module = importlib.import_module(
        "custom_components.oig_cloud.core.oig_cloud_notification"
    )
    monkeypatch.setattr(
        notification_module,
        "OigNotificationManager",
        DummyNotificationManager,
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_call_later",
        lambda *_a, **_k: None,
    )

    hass = DummyHass()
    hass.config_entries.async_update_entry = lambda *_a, **_k: None
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options=Options({"enable_cloud_notifications": True}),
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_persist_box_id_error(monkeypatch):
    class DummyCoordinatorData(DummyCoordinator):
        def __init__(self, hass, session_manager, *_args, **_kwargs):
            super().__init__(hass, session_manager, *_args, **_kwargs)
            self.data = {"123": {}}

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinatorData)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    def raising_update(_entry, options=None):
        if options and "box_id" in options:
            raise RuntimeError("boom")
        _entry.options = options or {}

    hass.config_entries.async_update_entry = raising_update

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_solar_forecast_error(monkeypatch):
    def debug_raise(message, *args, **kwargs):
        if "Initializing solar forecast functionality" in message:
            raise RuntimeError("boom")
        return None

    monkeypatch.setattr(init_module._LOGGER, "debug", debug_raise)
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={"enable_solar_forecast": True},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_balancing_manager_paths(monkeypatch):
    class DummyBalancingManager:
        def __init__(self, hass, box_id, storage_path, entry):
            self.hass = hass
            self.box_id = box_id
            self.storage_path = storage_path
            self.entry = entry
            self.calls = 0

        async def async_setup(self):
            return None

        async def check_balancing(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return None

    class RaisingOptions(dict):
        def get(self, key, default=None):
            if key == "box_id":
                raise RuntimeError("boom")
            return super().get(key, default)

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )
    monkeypatch.setattr(init_module, "BalancingManager", DummyBalancingManager)

    callbacks = {"interval": None, "later": None}

    def fake_track_interval(_hass, callback, _delta):
        callbacks["interval"] = callback
        return lambda: None

    def fake_call_later(_hass, _delay, callback):
        callbacks["later"] = callback
        return callback(None)

    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        fake_track_interval,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_call_later",
        fake_call_later,
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options=RaisingOptions({"balancing_enabled": True}),
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    await callbacks["interval"](None)


@pytest.mark.asyncio
async def test_async_setup_entry_balancing_manager_no_box_id(monkeypatch):
    class DummyCoordinatorNoDigits(DummyCoordinator):
        def __init__(self, hass, session_manager, *_args, **_kwargs):
            super().__init__(hass, session_manager, *_args, **_kwargs)
            self.data = {"abc": {}}

    class DummyBalancingManager:
        def __init__(self, hass, box_id, storage_path, entry):
            self.hass = hass
            self.box_id = box_id
            self.storage_path = storage_path
            self.entry = entry

        async def async_setup(self):
            return None

        async def check_balancing(self):
            return None

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinatorNoDigits)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )
    monkeypatch.setattr(init_module, "BalancingManager", DummyBalancingManager)

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    hass = DummyHass()
    hass.config = SimpleNamespace(path=lambda *_a, **_k: "/tmp")
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={"balancing_enabled": True},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_setup_entry_balancing_manager_executes(monkeypatch):
    class DummyBalancingManager:
        def __init__(self, hass, box_id, storage_path, entry):
            self.hass = hass
            self.box_id = box_id
            self.storage_path = storage_path
            self.entry = entry
            self.calls = 0
            self.setup_called = False

        async def async_setup(self):
            self.setup_called = True

        async def check_balancing(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")

            class DummyResult:
                class DummyMode:
                    name = "Home 1"

                mode = DummyMode()

            return DummyResult()

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )
    monkeypatch.setattr(init_module, "BalancingManager", DummyBalancingManager)

    callbacks = {"interval": None, "later": None}

    def fake_track_interval(_hass, callback, _delta):
        callbacks["interval"] = callback
        return lambda: None

    def fake_call_later(_hass, _delay, callback):
        callbacks["later"] = callback
        return lambda: None

    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        fake_track_interval,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_call_later",
        fake_call_later,
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )

    hass = DummyHass()
    hass.config = SimpleNamespace(path=lambda *_a, **_k: "/tmp")
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={"balancing_enabled": True},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    await callbacks["interval"](None)
    await callbacks["later"](None)


@pytest.mark.asyncio
async def test_async_setup_entry_balancing_manager_callbacks(monkeypatch):
    class Options(dict):
        def get(self, key, default=None):
            if key == "box_id":
                raise RuntimeError("boom")
            return super().get(key, default)

    class DummyBalancingManager:
        def __init__(self, hass, box_id, storage_path, entry):
            self.hass = hass
            self.box_id = box_id
            self.storage_path = storage_path
            self.entry = entry
            self.calls = 0

        async def async_setup(self):
            return None

        async def check_balancing(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return None

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )
    monkeypatch.setattr(init_module, "BalancingManager", DummyBalancingManager)

    tasks = []

    def fake_track_interval(_hass, callback, _delta):
        tasks.append(asyncio.create_task(callback(None)))
        return lambda: None

    def fake_call_later(_hass, _delay, callback):
        tasks.append(asyncio.create_task(callback(None)))
        return lambda: None

    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        fake_track_interval,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_call_later",
        fake_call_later,
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )

    hass = DummyHass()
    hass.config = SimpleNamespace(path=lambda *_a, **_k: "/tmp")
    hass.config_entries.async_update_entry = lambda *_a, **_k: None
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options=Options({"balancing_enabled": True}),
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    for task in tasks:
        await task


@pytest.mark.asyncio
async def test_async_setup_entry_balancing_manager_initial_plan(monkeypatch):
    class DummyBalancingManager:
        def __init__(self, hass, box_id, storage_path, entry):
            self.hass = hass
            self.box_id = box_id
            self.storage_path = storage_path
            self.entry = entry

        async def async_setup(self):
            return None

        async def check_balancing(self):
            class DummyResult:
                class DummyMode:
                    name = "Home 2"

                mode = DummyMode()

            return DummyResult()

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShield
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )
    monkeypatch.setattr(init_module, "BalancingManager", DummyBalancingManager)

    tasks = []

    def fake_track_interval(_hass, callback, _delta):
        return lambda: None

    def fake_call_later(_hass, _delay, callback):
        tasks.append(asyncio.create_task(callback(None)))
        return lambda: None

    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        fake_track_interval,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_call_later",
        fake_call_later,
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )

    hass = DummyHass()
    hass.config = SimpleNamespace(path=lambda *_a, **_k: "/tmp")
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={"balancing_enabled": True},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    for task in tasks:
        await task


@pytest.mark.asyncio
async def test_async_setup_entry_shield_monitoring_no_telemetry(monkeypatch):
    class DummyShieldNoTelemetry(DummyShield):
        def __init__(self, hass, entry):
            super().__init__(hass, entry)
            self.telemetry_handler = None

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.ServiceShield", DummyShieldNoTelemetry
    )
    monkeypatch.setattr(init_module, "OigCloudApi", DummyApi)
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.oig_cloud_session_manager.OigCloudSessionManager",
        DummySessionManager,
    )
    monkeypatch.setattr(init_module, "OigCloudCoordinator", DummyCoordinator)
    monkeypatch.setattr(init_module, "DataSourceController", DummyDataSourceController)
    monkeypatch.setattr(init_module, "init_data_source_state", lambda *_a, **_k: None)
    monkeypatch.setattr(
        init_module,
        "get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            effective_mode="local_only",
            configured_mode="local_only",
            local_available=True,
        ),
    )

    callbacks = {"interval": None}

    def fake_track_interval(_hass, callback, _delta):
        callbacks["interval"] = callback
        return lambda: None

    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_interval",
        fake_track_interval,
    )

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(init_module, "_cleanup_invalid_empty_devices", _noop)
    monkeypatch.setattr(init_module, "_remove_frontend_panel", _noop)
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_services", _noop
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.services.async_setup_entry_services_with_shield",
        _noop,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.planning_api.setup_planning_api_views",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.api.ha_rest_api.setup_api_endpoints",
        lambda *_a, **_k: None,
    )

    hass = DummyHass()
    entry = DummyEntry(
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        options={},
    )
    hass.data[DOMAIN] = {entry.entry_id: {}}

    result = await init_module.async_setup_entry(hass, entry)

    assert result is True
    await callbacks["interval"](None)
