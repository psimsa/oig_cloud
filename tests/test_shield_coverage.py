from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from custom_components.oig_cloud.shield import dispatch as dispatch_module
from custom_components.oig_cloud.shield import queue as queue_module
from custom_components.oig_cloud.shield import validation as validation_module


class DummyState:
    def __init__(self, entity_id: str, state: str) -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes: dict[str, Any] = {}
        self.last_changed = datetime.now()
        self.last_updated = self.last_changed


class DummyStates:
    def __init__(self, states: Optional[list[DummyState]] = None) -> None:
        self._states = {state.entity_id: state for state in (states or [])}

    def get(self, entity_id: str) -> Optional[DummyState]:
        return self._states.get(entity_id)

    def async_all(self, domain: Optional[str] = None) -> list[DummyState]:
        if domain is None:
            return list(self._states.values())
        prefix = f"{domain}."
        return [st for st in self._states.values() if st.entity_id.startswith(prefix)]

    def async_entity_ids(self, domain: Optional[str] = None) -> list[str]:
        entities = list(self._states.keys())
        if domain:
            prefix = f"{domain}."
            entities = [e for e in entities if e.startswith(prefix)]
        return entities


class DummyBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any, Any]] = []

    def async_fire(
        self, event_type: str, data: Any = None, context: Any = None
    ) -> None:
        self.events.append((event_type, data, context))


class DummyHass:
    def __init__(self, states: Optional[DummyStates] = None) -> None:
        self.states = states or DummyStates()
        self.data: dict[str, Any] = {"oig_cloud": {}}
        self.bus = DummyBus()
        self.services: Any = SimpleNamespace(async_call=AsyncMock())

    def async_create_task(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        return task

    async def services_async_call(
        self, domain: str, service: str, service_data: dict[str, Any]
    ) -> None:
        pass


class DummyEntry:
    def __init__(self, box_id: str = "123", entry_id: str = "test_entry") -> None:
        self.entry_id = entry_id
        self.options = {"box_id": box_id}
        self.data: dict[str, Any] = {}


class DummyShield:
    def __init__(
        self, hass: Optional[DummyHass] = None, entry: Optional[DummyEntry] = None
    ) -> None:
        self.hass = hass or DummyHass()
        self.entry = entry or DummyEntry()
        self.last_checked_entity_id: Optional[str] = None
        self.queue: list[Any] = []
        self.pending: dict[str, dict[str, Any]] = {}
        self.running: Optional[str] = None
        self.queue_metadata: dict[Any, Any] = {}
        self._is_checking = False
        self._state_listener_unsub: Optional[Callable[[], None]] = None
        self._active_tasks: dict[str, dict[str, Any]] = {}
        self.check_task: Any = None
        self.mode_tracker = None
        self._expected_entity_missing = False
        self._logger: Any = MagicMock()

    def _normalize_value(self, val: Any) -> str:
        return validation_module.normalize_value(val)

    def _notify_state_change(self) -> None:
        pass

    def _log_security_event(self, *args: Any, **kwargs: Any) -> None:
        pass

    def _get_entity_state(self, entity_id: str) -> Optional[str]:
        state = self.hass.states.get(entity_id)
        return state.state if state else None

    def _values_match(self, current: Any, expected: Any) -> bool:
        return validation_module.values_match(current, expected)

    def _check_entity_state_change(self, entity_id: str, expected_value: Any) -> bool:
        current = self._get_entity_state(entity_id)
        return validation_module.values_match(current, expected_value)

    async def _log_event(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def _log_telemetry(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def _start_call(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def _check_loop(self, _now: datetime) -> None:
        pass

    def _setup_state_listener(self) -> None:
        pass

    def extract_expected_entities(
        self, service_name: str, params: dict[str, Any]
    ) -> dict[str, str]:
        return validation_module.extract_expected_entities(self, service_name, params)

    def _extract_api_info(
        self, service_name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        return validation_module.extract_api_info(service_name, params)

class TestSplitGridDeliveryParams:
    def test_split_both_mode_and_limit(self):
        params = {"mode": "limited", "limit": 500}
        result = dispatch_module._split_grid_delivery_params(params)
        assert result is not None
        assert len(result) == 2
        assert result[0]["_grid_delivery_step"] == "mode"
        assert "limit" not in result[0]
        assert result[1]["_grid_delivery_step"] == "limit"
        assert "mode" not in result[1]

    def test_no_split_when_only_mode(self):
        assert dispatch_module._split_grid_delivery_params({"mode": "limited"}) is None

    def test_no_split_when_only_limit(self):
        assert dispatch_module._split_grid_delivery_params({"limit": 500}) is None

    def test_no_split_empty(self):
        assert dispatch_module._split_grid_delivery_params({}) is None


class TestIsDuplicate:
    def test_duplicate_in_queue(self):
        shield = DummyShield()
        shield.queue.append(("svc", {"p": 1}, {"e": "v"}))
        result = dispatch_module._is_duplicate(shield, "svc", {"p": 1}, {"e": "v"})
        assert result == "queue"

    def test_duplicate_in_pending(self):
        shield = DummyShield()
        shield.pending["svc"] = {"entities": {"e": "v"}}
        result = dispatch_module._is_duplicate(shield, "svc", {"p": 1}, {"e": "v"})
        assert result == "pending"

    def test_no_duplicate(self):
        shield = DummyShield()
        result = dispatch_module._is_duplicate(shield, "svc", {"p": 1}, {"e": "v"})
        assert result is None

    def test_params_mismatch_not_duplicate(self):
        shield = DummyShield()
        shield.queue.append(("svc", {"p": 2}, {"e": "v"}))
        result = dispatch_module._is_duplicate(shield, "svc", {"p": 1}, {"e": "v"})
        assert result is None

    def test_none_params(self):
        shield = DummyShield()
        shield.queue.append(("svc", None, {"e": "v"}))
        result = dispatch_module._is_duplicate(shield, "svc", {}, {"e": "v"})
        assert result == "queue"


class TestEntitiesAlreadyMatch:
    def test_grid_limit_step_always_proceeds(self):
        shield = DummyShield()
        result = dispatch_module._entities_already_match(
            shield, {"e": "v"}, {"_grid_delivery_step": "limit"}
        )
        assert result is False

    def test_entities_match(self):
        state = DummyState("sensor.e", "on")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        result = dispatch_module._entities_already_match(shield, {"sensor.e": "zapnuto"})
        assert result is True

    def test_entities_mismatch(self):
        state = DummyState("sensor.e", "off")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        result = dispatch_module._entities_already_match(shield, {"sensor.e": "zapnuto"})
        assert result is False

    def test_missing_state(self):
        shield = DummyShield()
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        result = dispatch_module._entities_already_match(shield, {"sensor.e": "v"})
        assert result is False


class TestHandleDuplicate:
    def test_handle_duplicate_queue(self):
        shield = DummyShield()
        shield._log_event = AsyncMock()
        shield._log_telemetry = AsyncMock()
        asyncio.run(
            dispatch_module._handle_duplicate(
                shield, "queue", "svc", {"p": 1}, {"e": "v"}, None
            )
        )
        shield._log_event.assert_called_once()
        shield._log_telemetry.assert_called_once()

    def test_handle_duplicate_pending(self):
        shield = DummyShield()
        shield._log_event = AsyncMock()
        shield._log_telemetry = AsyncMock()
        asyncio.run(
            dispatch_module._handle_duplicate(
                shield, "pending", "svc", {"p": 1}, {"e": "v"}, None
            )
        )
        shield._log_event.assert_called_once()
        args = shield._log_event.call_args
        assert "spuštěna" in args[1]["reason"]


class TestLogDedupState:
    def test_logs_state(self, caplog):
        shield = DummyShield()
        shield.queue.append(("svc", {"p": 1}, {"e": "v"}))
        shield.pending["svc"] = {"entities": {"e": "v"}}
        with caplog.at_level(logging.DEBUG, logger="custom_components.oig_cloud.shield.dispatch"):
            dispatch_module._log_dedup_state(shield, "svc", {"p": 1}, {"e": "v"})
        assert "Dedup: checking for duplicates" in caplog.text
        assert "queue length=1" in caplog.text
        assert "pending length=1" in caplog.text


class TestEnqueueOrRun:
    def test_enqueue_when_running(self):
        shield = DummyShield()
        shield.running = "other_svc"
        shield._log_event = AsyncMock()
        asyncio.run(
            dispatch_module._enqueue_or_run(
                shield, "svc", {"p": 1}, {"e": "v"}, AsyncMock(),
                "domain", "service", False, None, "trace1"
            )
        )
        assert len(shield.queue) == 1
        shield._log_event.assert_called_once()

    def test_run_when_idle(self):
        shield = DummyShield()
        shield.running = None
        original_call = AsyncMock()
        asyncio.run(
            dispatch_module._enqueue_or_run(
                shield, "svc", {"p": 1}, {"e": "v"}, original_call,
                "domain", "service", False, None, "trace1"
            )
        )
        assert len(shield.queue) == 0


class TestInterceptServiceCall:
    def test_calls_original_when_no_expected_entities_and_missing_flag(self):
        shield = DummyShield()
        shield._expected_entity_missing = True
        shield.extract_expected_entities = lambda service_name, params: {}
        original_call = AsyncMock()
        asyncio.run(
            dispatch_module.intercept_service_call(
                shield, "oig_cloud", "other_svc",
                {"params": {"x": 1}}, original_call, False, None
            )
        )
        original_call.assert_called_once()

    def test_skips_when_entities_already_match(self):
        state = DummyState("sensor.e", "on")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        shield.extract_expected_entities = (
            lambda service_name, params: {"sensor.e": "zapnuto"}
        )
        shield._log_telemetry = AsyncMock()
        shield._log_event = AsyncMock()
        asyncio.run(
            dispatch_module.intercept_service_call(
                shield, "oig_cloud", "other_svc",
                {"params": {"x": 1}}, AsyncMock(), False, None
            )
        )
        shield._log_telemetry.assert_called_once()

    def test_duplicate_ignored(self):
        shield = DummyShield()
        shield.pending["oig_cloud.svc"] = {"entities": {"e": "v"}}
        shield.extract_expected_entities = lambda service_name, params: {"e": "v"}
        shield._log_event = AsyncMock()
        shield._log_telemetry = AsyncMock()
        asyncio.run(
            dispatch_module.intercept_service_call(
                shield, "oig_cloud", "svc",
                {"params": {}}, AsyncMock(), False, None
            )
        )
        shield._log_event.assert_called_once()

    def test_grid_delivery_split_direct(self, monkeypatch):
        shield = DummyShield()
        calls = []
        async def fake_intercept(*args):
            calls.append(args[3]["params"])
        monkeypatch.setattr(dispatch_module, "intercept_service_call", fake_intercept)
        result = asyncio.run(
            dispatch_module._handle_split_grid_delivery(
                shield, "oig_cloud", "set_grid_delivery",
                {"mode": "limited", "limit": 500}, AsyncMock(), False, None
            )
        )
        assert result is True
        assert len(calls) == 2
        assert calls[0].get("_grid_delivery_step") == "mode"
        assert calls[1].get("_grid_delivery_step") == "limit"

    def test_box_mode_split_direct(self, monkeypatch):
        shield = DummyShield()
        calls = []
        async def fake_intercept(*args):
            calls.append(args[3]["params"])
        monkeypatch.setattr(dispatch_module, "intercept_service_call", fake_intercept)
        result = asyncio.run(
            dispatch_module._handle_split_box_mode(
                shield, "oig_cloud", "set_box_mode",
                {"mode": "home_1", "home_grid_v": True}, AsyncMock(), False, None
            )
        )
        assert result is True
        assert len(calls) == 2
        assert calls[0].get("_box_mode_step") == "mode"
        assert calls[1].get("_box_mode_step") == "app"


class TestStartCall:
    def test_successful_call(self):
        state = DummyState("sensor.e", "old")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        shield._log_event = AsyncMock()
        original_call = AsyncMock()
        asyncio.run(
            dispatch_module.start_call(
                shield, "svc", {"params": {"x": 1}}, {"sensor.e": "new"},
                original_call, "domain", "service", False, None
            )
        )
        assert shield.running == "svc"
        assert "svc" in shield.pending
        original_call.assert_called_once()

    def test_failed_call_clears_pending(self):
        state = DummyState("sensor.e", "old")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        shield._log_event = AsyncMock()
        original_call = AsyncMock(side_effect=Exception("boom"))
        shield._notify_state_change = lambda: None
        asyncio.run(
            dispatch_module.start_call(
                shield, "svc", {"params": {"x": 1}}, {"sensor.e": "new"},
                original_call, "domain", "service", False, None
            )
        )
        assert "svc" not in shield.pending
        assert shield.running is None


class TestSafeCallService:
    def test_no_entity_id_returns_true(self):
        shield = DummyShield()
        shield.hass.services = MagicMock()
        shield.hass.services.async_call = AsyncMock()
        result = asyncio.run(
            dispatch_module.safe_call_service(shield, "set_boiler_mode", {})
        )
        assert result is True

    def test_boiler_mode_manual(self):
        state = DummyState("sensor.oig_123_boiler_manual_mode", "Manual")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        shield._check_entity_state_change = lambda entity_id, expected_value: True
        shield.hass.services.async_call = AsyncMock()
        result = asyncio.run(
            dispatch_module.safe_call_service(
                shield, "set_boiler_mode", {"entity_id": "sensor.oig_123_boiler_manual_mode", "mode": "Manual"}
            )
        )
        assert result is True

    def test_mode_change(self):
        state = DummyState("sensor.e", "Home 1")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        shield._check_entity_state_change = lambda entity_id, expected_value: True
        shield.hass.services.async_call = AsyncMock()
        result = asyncio.run(
            dispatch_module.safe_call_service(
                shield, "set_box_mode", {"entity_id": "sensor.e", "mode": "Home 2"}
            )
        )
        assert result is True

    def test_exception_returns_false(self):
        shield = DummyShield()
        shield.hass.services.async_call = AsyncMock(side_effect=Exception("fail"))
        result = asyncio.run(
            dispatch_module.safe_call_service(shield, "svc", {})
        )
        assert result is False


class TestLogEvent:
    def test_logs_events(self):
        state = DummyState("sensor.e", "old")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        asyncio.run(
            dispatch_module.log_event(
                shield, "queued", "svc",
                {"params": {"x": 1}, "entities": {"sensor.e": "new"}},
                "reason", None
            )
        )
        assert len(hass.bus.events) == 2

    def test_empty_entities(self):
        hass = DummyHass()
        shield = DummyShield(hass)
        asyncio.run(
            dispatch_module.log_event(
                shield, "started", "svc", {"params": {}, "entities": {}}, None, None
            )
        )
        assert len(hass.bus.events) == 2


class TestCaptureOriginalStates:
    def test_captures_states(self):
        state = DummyState("sensor.e", "old")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        result = dispatch_module._capture_original_states(shield, {"sensor.e": "new"})
        assert result == {"sensor.e": "old"}

    def test_missing_state(self):
        shield = DummyShield()
        result = dispatch_module._capture_original_states(shield, {"sensor.e": "new"})
        assert result == {"sensor.e": None}


class TestInitPowerMonitor:
    def test_not_box_mode_returns_none(self):
        shield = DummyShield()
        result = dispatch_module._init_power_monitor(shield, "other_svc", {})
        assert result is None

    def test_no_box_id_returns_none(self):
        shield = DummyShield()
        result = dispatch_module._init_power_monitor(shield, "oig_cloud.set_box_mode", {})
        assert result is None

    def test_no_power_entity_returns_none(self):
        state = DummyState("sensor.oig_123_box_prms_mode", "Home 1")
        hass = DummyHass(DummyStates([state]))
        entry = DummyEntry(box_id="123")
        shield = DummyShield(hass, entry)
        result = dispatch_module._init_power_monitor(
            shield, "oig_cloud.set_box_mode", {"value": "Home UPS"}
        )
        assert result is None

    def test_power_entity_unknown_returns_none(self):
        state = DummyState("sensor.oig_123_actual_aci_wtotal", "unknown")
        hass = DummyHass(DummyStates([state]))
        entry = DummyEntry(box_id="123")
        shield = DummyShield(hass, entry)
        result = dispatch_module._init_power_monitor(
            shield, "oig_cloud.set_box_mode", {"value": "Home UPS"}
        )
        assert result is None

    def test_valid_power_monitor(self, monkeypatch):
        state = DummyState("sensor.oig_123_actual_aci_wtotal", "1500.5")
        hass = DummyHass(DummyStates([state]))
        entry = DummyEntry(box_id="123")
        shield = DummyShield(hass, entry)
        monkeypatch.setattr(dispatch_module, "_resolve_box_id_for_power_monitor", lambda s: "123")
        result = dispatch_module._init_power_monitor(
            shield, "oig_cloud.set_box_mode", {"value": "Home UPS"}
        )
        assert result is not None
        assert result["baseline_power"] == 1500.5
        assert result["is_going_to_home_ups"] is True

    def test_invalid_power_value(self):
        state = DummyState("sensor.oig_123_actual_aci_wtotal", "invalid")
        hass = DummyHass(DummyStates([state]))
        entry = DummyEntry(box_id="123")
        shield = DummyShield(hass, entry)
        result = dispatch_module._init_power_monitor(
            shield, "oig_cloud.set_box_mode", {"value": "Home UPS"}
        )
        assert result is None

    def test_non_string_target_mode(self):
        state = DummyState("sensor.oig_123_actual_aci_wtotal", "1000")
        hass = DummyHass(DummyStates([state]))
        entry = DummyEntry(box_id="123")
        shield = DummyShield(hass, entry)
        result = dispatch_module._init_power_monitor(
            shield, "oig_cloud.set_box_mode", {"value": 123}
        )
        assert result is None


class TestBuildPowerEntity:
    def test_build(self):
        assert dispatch_module._build_power_entity("abc") == "sensor.oig_abc_actual_aci_wtotal"


class TestReadPowerState:
    def test_missing_entity(self):
        shield = DummyShield()
        assert dispatch_module._read_power_state(shield, "sensor.missing") is None

    def test_unknown_state(self):
        state = DummyState("sensor.e", "unknown")
        shield = DummyShield(DummyHass(DummyStates([state])))
        assert dispatch_module._read_power_state(shield, "sensor.e") is None

    def test_unavailable_state(self):
        state = DummyState("sensor.e", "unavailable")
        shield = DummyShield(DummyHass(DummyStates([state])))
        assert dispatch_module._read_power_state(shield, "sensor.e") is None

    def test_valid_state(self):
        state = DummyState("sensor.e", "1234.5")
        shield = DummyShield(DummyHass(DummyStates([state])))
        assert dispatch_module._read_power_state(shield, "sensor.e") == 1234.5

    def test_invalid_state(self):
        state = DummyState("sensor.e", "abc")
        shield = DummyShield(DummyHass(DummyStates([state])))
        assert dispatch_module._read_power_state(shield, "sensor.e") is None


class TestNormalizeTargetMode:
    def test_string_value(self):
        assert dispatch_module._normalize_target_mode({"value": "home ups"}) == "HOME UPS"

    def test_empty_string(self):
        assert dispatch_module._normalize_target_mode({"value": ""}) == ""

    def test_non_string(self):
        assert dispatch_module._normalize_target_mode({"value": 123}) is None


class TestBuildPowerMonitor:
    def test_structure(self):
        result = dispatch_module._build_power_monitor("sensor.e", 1000.0, "HOME UPS")
        assert result["entity_id"] == "sensor.e"
        assert result["baseline_power"] == 1000.0
        assert result["target_mode"] == "HOME UPS"
        assert result["is_going_to_home_ups"] is True
        assert result["threshold_kw"] == 2.5


class TestResolveBoxIdForPowerMonitor:
    def test_no_data(self):
        shield = DummyShield()
        assert dispatch_module._resolve_box_id_for_power_monitor(shield) is None

    def test_found_in_data(self):
        shield = DummyShield()
        shield.hass.data["oig_cloud"] = {
            "entry1": {"service_shield": shield, "coordinator": None}
        }
        assert dispatch_module._resolve_box_id_for_power_monitor(shield) is None


class TestFireQueueInfoEvent:
    def test_fires_event(self):
        shield = DummyShield()
        shield.running = "svc"
        shield.queue.append(("svc2", {}, {}))
        dispatch_module._fire_queue_info_event(shield)
        assert len(shield.hass.bus.events) == 1
        event_type, data, _ = shield.hass.bus.events[0]
        assert event_type == "oig_cloud_shield_queue_info"
        assert data["running"] == "svc"
        assert data["queue_length"] == 1


class TestLogStartEvents:
    def test_logs(self):
        shield = DummyShield()
        shield._log_event = AsyncMock()
        asyncio.run(
            dispatch_module._log_start_events(
                shield, "svc", data={"p": 1}, expected_entities={"e": "v"},
                original_states={"e": "old"}, context=None
            )
        )
        assert shield._log_event.call_count == 2


class TestRefreshCoordinatorAfterCall:
    def test_refreshes(self):
        coordinator = MagicMock()
        coordinator.async_request_refresh = AsyncMock()
        shield = DummyShield()
        shield.hass.data["oig_cloud"] = {
            shield.entry.entry_id: {"coordinator": coordinator}
        }
        asyncio.run(dispatch_module._refresh_coordinator_after_call(shield, "svc"))
        coordinator.async_request_refresh.assert_called_once()

    def test_no_coordinator(self):
        shield = DummyShield()
        asyncio.run(dispatch_module._refresh_coordinator_after_call(shield, "svc"))

    def test_exception_handled(self):
        coordinator = MagicMock()
        coordinator.async_request_refresh = AsyncMock(side_effect=Exception("fail"))
        shield = DummyShield()
        shield.hass.data["oig_cloud"] = {
            shield.entry.entry_id: {"coordinator": coordinator}
        }
        asyncio.run(dispatch_module._refresh_coordinator_after_call(shield, "svc"))


class TestBuildLogMessage:
    def test_queued(self):
        msg = dispatch_module._build_log_message("queued", "svc", "Ent", "v", "old", False)
        assert "Zařazeno do fronty" in msg

    def test_started(self):
        msg = dispatch_module._build_log_message("started", "svc", "Ent", "v", "old", False)
        assert "Spuštěno" in msg

    def test_completed_limit(self):
        msg = dispatch_module._build_log_message("completed", "svc", "Ent", "500", "old", True)
        assert "limit nastaven na 500W" in msg

    def test_completed_non_limit(self):
        msg = dispatch_module._build_log_message("completed", "svc", "Ent", "v", "old", False)
        assert "změna na 'v'" in msg

    def test_timeout_limit(self):
        msg = dispatch_module._build_log_message("timeout", "svc", "Ent", "500", "old", True)
        assert "limit stále není 500W" in msg

    def test_timeout_non_limit(self):
        msg = dispatch_module._build_log_message("timeout", "svc", "Ent", "v", "curr", False)
        assert "vypršel" in msg

    def test_released(self):
        msg = dispatch_module._build_log_message("released", "svc", "Ent", "v", "old", False)
        assert "Semafor uvolněn" in msg

    def test_cancelled(self):
        msg = dispatch_module._build_log_message("cancelled", "svc", "Ent", "v", "old", False)
        assert "Zrušeno uživatelem" in msg

    def test_unknown(self):
        msg = dispatch_module._build_log_message("unknown", "svc", "Ent", "v", "old", False)
        assert "unknown – svc" in msg


class TestHandleShieldStatus:
    def test_status_running(self):
        shield = DummyShield()
        shield.running = "svc"
        asyncio.run(queue_module.handle_shield_status(shield, None))
        assert len(shield.hass.bus.events) == 1
        assert shield.hass.bus.events[0][1]["status"] == "Běží: svc"

    def test_status_queued(self):
        shield = DummyShield()
        shield.queue.append(("svc", {}, {}))
        asyncio.run(queue_module.handle_shield_status(shield, None))
        assert "Ve frontě" in shield.hass.bus.events[0][1]["status"]

    def test_status_idle(self):
        shield = DummyShield()
        asyncio.run(queue_module.handle_shield_status(shield, None))
        assert shield.hass.bus.events[0][1]["status"] == "Neaktivní"


class TestHandleQueueInfo:
    def test_info(self):
        shield = DummyShield()
        shield.queue.append(("svc", {}, {}))
        asyncio.run(queue_module.handle_queue_info(shield, None))
        data = shield.hass.bus.events[0][1]
        assert data["queue_length"] == 1


class TestHandleRemoveFromQueue:
    def test_invalid_position_too_low(self, caplog):
        shield = DummyShield()
        with caplog.at_level(logging.ERROR):
            asyncio.run(queue_module.handle_remove_from_queue(shield, SimpleNamespace(data={"position": 0})))
        assert "Neplatná pozice" in caplog.text

    def test_invalid_position_too_high(self, caplog):
        shield = DummyShield()
        with caplog.at_level(logging.ERROR):
            asyncio.run(queue_module.handle_remove_from_queue(shield, SimpleNamespace(data={"position": 5})))
        assert "Neplatná pozice" in caplog.text

    def test_cannot_remove_running(self, caplog):
        shield = DummyShield()
        shield.running = "svc"
        shield.pending["svc"] = {}
        with caplog.at_level(logging.WARNING):
            asyncio.run(queue_module.handle_remove_from_queue(shield, SimpleNamespace(data={"position": 1})))
        assert "Nelze smazat běžící službu" in caplog.text

    def test_valid_remove(self):
        shield = DummyShield()
        shield.queue.append(("svc", {"p": 1}, {"e": "v"}))
        shield._log_event = AsyncMock()
        call = SimpleNamespace(data={"position": 1}, context=None)
        asyncio.run(queue_module.handle_remove_from_queue(shield, call))
        assert len(shield.queue) == 0
        shield._log_event.assert_called_once()

    def test_index_error(self, caplog):
        shield = DummyShield()
        shield.pending["svc1"] = {}
        shield.pending["svc2"] = {}
        shield.queue.append(("svc3", {}, {}))
        call = SimpleNamespace(data={"position": 2}, context=None)
        with caplog.at_level(logging.ERROR):
            asyncio.run(queue_module.handle_remove_from_queue(shield, call))
        assert "Chyba výpočtu indexu" in caplog.text


class TestClearStateListener:
    def test_clears(self):
        shield = DummyShield()
        unsub = MagicMock()
        shield._state_listener_unsub = unsub
        queue_module._clear_state_listener(shield)
        unsub.assert_called_once()
        assert shield._state_listener_unsub is None

    def test_none_unsub(self):
        shield = DummyShield()
        queue_module._clear_state_listener(shield)
        assert shield._state_listener_unsub is None


class TestGetTimeoutMinutes:
    def test_formating_mode(self):
        assert queue_module._get_timeout_minutes("oig_cloud.set_formating_mode") == 2

    def test_other(self):
        assert queue_module._get_timeout_minutes("oig_cloud.set_box_mode") == 15


class TestHandleTimeout:
    def test_formating_mode(self):
        shield = DummyShield()
        shield._log_event = AsyncMock()
        shield._log_telemetry = AsyncMock()
        asyncio.run(queue_module._handle_timeout(
            shield, "oig_cloud.set_formating_mode",
            {"params": {}, "entities": {}, "original_states": {}}
        ))
        shield._log_event.assert_called()

    def test_regular_timeout(self):
        shield = DummyShield()
        shield._log_event = AsyncMock()
        shield._log_telemetry = AsyncMock()
        asyncio.run(queue_module._handle_timeout(
            shield, "oig_cloud.set_box_mode",
            {"params": {}, "entities": {}}
        ))
        shield._log_event.assert_called()


class TestGetPowerMonitorState:
    def test_missing_entity(self):
        shield = DummyShield()
        result = queue_module._get_power_monitor_state(shield, {"entity_id": "sensor.missing"})
        assert result is None

    def test_unknown_state(self):
        state = DummyState("sensor.e", "unknown")
        shield = DummyShield(DummyHass(DummyStates([state])))
        result = queue_module._get_power_monitor_state(shield, {"entity_id": "sensor.e"})
        assert result is None

    def test_valid_state(self):
        state = DummyState("sensor.e", "1234")
        shield = DummyShield(DummyHass(DummyStates([state])))
        result = queue_module._get_power_monitor_state(shield, {"entity_id": "sensor.e"})
        assert result == 1234.0

    def test_invalid_state(self):
        state = DummyState("sensor.e", "abc")
        shield = DummyShield(DummyHass(DummyStates([state])))
        result = queue_module._get_power_monitor_state(shield, {"entity_id": "sensor.e"})
        assert result is None


class TestGetShieldStatus:
    def test_running(self):
        shield = DummyShield()
        shield.running = "svc"
        assert queue_module.get_shield_status(shield) == "Běží: svc"

    def test_queued(self):
        shield = DummyShield()
        shield.queue.append(("svc", {}, {}))
        assert "Ve frontě" in queue_module.get_shield_status(shield)

    def test_idle(self):
        shield = DummyShield()
        assert queue_module.get_shield_status(shield) == "Neaktivní"


class TestGetQueueInfo:
    def test_info(self):
        shield = DummyShield()
        shield.queue.append(("svc", {}, {}))
        info = queue_module.get_queue_info(shield)
        assert info["queue_length"] == 1
        assert info["queue_services"] == ["svc"]


class TestHasPendingModeChange:
    def test_pending_has_mode(self):
        shield = DummyShield()
        shield.pending["oig_cloud.set_box_mode"] = {"entities": {"e": "Home 1"}}
        assert queue_module.has_pending_mode_change(shield) is True

    def test_queue_has_mode(self):
        shield = DummyShield()
        shield.queue.append(("oig_cloud.set_box_mode", {}, {"e": "Home 1"}))
        assert queue_module.has_pending_mode_change(shield) is True

    def test_running_is_mode(self):
        shield = DummyShield()
        shield.running = "oig_cloud.set_box_mode"
        assert queue_module.has_pending_mode_change(shield) is True

    def test_no_pending(self):
        shield = DummyShield()
        assert queue_module.has_pending_mode_change(shield) is False

    def test_target_mode_filter(self):
        shield = DummyShield()
        shield.pending["oig_cloud.set_box_mode"] = {"entities": {"e": "Home 1"}}
        assert queue_module.has_pending_mode_change(shield, "Home 2") is False
        assert queue_module.has_pending_mode_change(shield, "Home 1") is True


class TestMatchesTargetMode:
    def test_no_entities(self):
        shield = DummyShield()
        assert queue_module._matches_target_mode(shield, {}, "Home 1") is False

    def test_no_target(self):
        shield = DummyShield()
        assert queue_module._matches_target_mode(shield, {"e": "Home 1"}, None) is True

    def test_match(self):
        shield = DummyShield()
        assert queue_module._matches_target_mode(shield, {"e": "Home 1"}, "Home 1") is True

    def test_mismatch(self):
        shield = DummyShield()
        assert queue_module._matches_target_mode(shield, {"e": "Home 1"}, "Home 2") is False


class TestCheckLoop:
    def test_already_checking(self, caplog):
        shield = DummyShield()
        shield._is_checking = True
        with caplog.at_level(logging.DEBUG, logger="custom_components.oig_cloud.shield.queue"):
            asyncio.run(queue_module.check_loop(shield, datetime.now()))
        assert "již běží" in caplog.text

    def test_idle(self, caplog):
        shield = DummyShield()
        with caplog.at_level(logging.DEBUG, logger="custom_components.oig_cloud.shield.queue"):
            asyncio.run(queue_module.check_loop(shield, datetime.now()))
        assert "vše prázdné" in caplog.text

    def test_finished_pending(self):
        shield = DummyShield()
        state = DummyState("sensor.e", "new")
        hass = DummyHass(DummyStates([state]))
        shield.hass = hass
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        shield.pending["svc"] = {
            "entities": {"sensor.e": "new"},
            "params": {},
            "called_at": datetime.now(),
        }
        shield._log_event = AsyncMock()
        asyncio.run(queue_module.check_loop(shield, datetime.now()))
        assert "svc" not in shield.pending

    def test_start_next_call(self):
        shield = DummyShield()
        original_call = AsyncMock()
        shield.queue.append(("svc", {"p": 1}, {"e": "v"}, original_call, "domain", "service", False, None))
        shield._start_call = AsyncMock()
        asyncio.run(queue_module.check_loop(shield, datetime.now()))
        shield._start_call.assert_called_once()


class TestIsQueueIdle:
    def test_idle(self):
        shield = DummyShield()
        assert queue_module._is_queue_idle(shield) is True

    def test_not_idle_running(self):
        shield = DummyShield()
        shield.running = "svc"
        assert queue_module._is_queue_idle(shield) is False


class TestProcessPendingService:
    def test_timeout(self):
        shield = DummyShield()
        shield.pending["svc"] = {
            "entities": {}, "params": {},
            "called_at": datetime.now() - timedelta(minutes=20),
        }
        shield._log_event = AsyncMock()
        shield._log_telemetry = AsyncMock()
        result = asyncio.run(queue_module._process_pending_service(
            shield, "svc", shield.pending["svc"]
        ))
        assert result is True

    def test_entities_match(self):
        state = DummyState("sensor.e", "new")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        shield.pending["svc"] = {
            "entities": {"sensor.e": "new"},
            "params": {},
            "called_at": datetime.now(),
        }
        shield._log_event = AsyncMock()
        result = asyncio.run(queue_module._process_pending_service(
            shield, "svc", shield.pending["svc"]
        ))
        assert result is True

    def test_not_finished(self):
        state = DummyState("sensor.e", "old")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        shield.pending["svc"] = {
            "entities": {"sensor.e": "new"},
            "params": {},
            "called_at": datetime.now(),
        }
        result = asyncio.run(queue_module._process_pending_service(
            shield, "svc", shield.pending["svc"]
        ))
        assert result is False


class TestCheckPowerMonitor:
    def test_no_monitor(self):
        shield = DummyShield()
        assert queue_module._check_power_monitor(shield, {}) is False

    def test_missing_entity(self):
        shield = DummyShield()
        assert queue_module._check_power_monitor(shield, {"power_monitor": {"entity_id": "sensor.missing"}}) is False

    def test_power_jump(self, caplog):
        state = DummyState("sensor.e", "5000")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        pm = {"entity_id": "sensor.e", "last_power": 1000, "is_going_to_home_ups": True, "threshold_kw": 2.5}
        with caplog.at_level(logging.INFO):
            result = queue_module._check_power_monitor(shield, {"power_monitor": pm})
        assert result is True
        assert "POWER JUMP DETECTED" in caplog.text

    def test_power_drop(self, caplog):
        state = DummyState("sensor.e", "1000")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        pm = {"entity_id": "sensor.e", "last_power": 5000, "is_going_to_home_ups": False, "threshold_kw": 2.5}
        with caplog.at_level(logging.INFO):
            result = queue_module._check_power_monitor(shield, {"power_monitor": pm})
        assert result is True
        assert "POWER DROP DETECTED" in caplog.text

    def test_no_change(self):
        state = DummyState("sensor.e", "1000")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        pm = {"entity_id": "sensor.e", "last_power": 1000, "is_going_to_home_ups": True, "threshold_kw": 2.5}
        result = queue_module._check_power_monitor(shield, {"power_monitor": pm})
        assert result is False

    def test_parse_error(self, caplog):
        state = DummyState("sensor.e", "invalid")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        pm = {"entity_id": "sensor.e", "last_power": 1000, "is_going_to_home_ups": True, "threshold_kw": 2.5}
        with caplog.at_level(logging.WARNING):
            result = queue_module._check_power_monitor(shield, {"power_monitor": pm})
        assert result is False


class TestHandlePowerMonitorCompletion:
    def test_logs(self):
        shield = DummyShield()
        shield._log_event = AsyncMock()
        shield._log_telemetry = AsyncMock()
        asyncio.run(queue_module._handle_power_monitor_completion(
            shield, "svc", {"params": {}, "entities": {}, "original_states": {}}
        ))
        assert shield._log_event.call_count == 2


class TestEntitiesMatch:
    def test_formating_mode(self, caplog):
        state = DummyState("fake_formating_mode_123", "completed_after_timeout")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        info = {
            "entities": {"fake_formating_mode_123": "completed_after_timeout"},
            "params": {},
            "called_at": datetime.now(),
        }
        with caplog.at_level(logging.DEBUG, logger="custom_components.oig_cloud.shield.queue"):
            result = queue_module._entities_match(
                shield, "svc", info, 15
            )
        assert result is False
        assert "Formating mode" in caplog.text

    def test_unavailable_value(self, caplog):
        state = DummyState("sensor.e", "unavailable")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        info = {
            "entities": {"sensor.e": "new"},
            "params": {},
            "called_at": datetime.now(),
        }
        with caplog.at_level(logging.DEBUG, logger="custom_components.oig_cloud.shield.queue"):
            result = queue_module._entities_match(
                shield, "svc", info, 15
            )
        assert result is False
        assert "nedostupná" in caplog.text

    def test_telemetry_lag(self, caplog):
        mode_state = DummyState("sensor.oig_123_invertor_prms_to_grid", "zapnuto")
        limit_state = DummyState("sensor.oig_123_invertor_prm1_p_max_feed_grid", "500")
        hass = DummyHass(DummyStates([mode_state, limit_state]))
        shield = DummyShield(hass)
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        info = {
            "entities": {"sensor.oig_123_invertor_prm1_p_max_feed_grid": "500"},
            "params": {},
            "called_at": datetime.now(),
        }
        with caplog.at_level(logging.DEBUG):
            result = queue_module._entities_match(shield, "svc", info, 15)
        assert result is False

    def test_entities_match(self, caplog):
        state = DummyState("sensor.e", "new")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        info = {
            "entities": {"sensor.e": "new"},
            "params": {},
            "called_at": datetime.now(),
        }
        with caplog.at_level(logging.INFO):
            result = queue_module._entities_match(shield, "svc", info, 15)
        assert result is True

    def test_entities_mismatch(self, caplog):
        state = DummyState("sensor.e", "old")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        info = {
            "entities": {"sensor.e": "new"},
            "params": {},
            "called_at": datetime.now(),
        }
        with caplog.at_level(logging.DEBUG):
            result = queue_module._entities_match(shield, "svc", info, 15)
        assert result is False

    def test_grid_step_logged(self, caplog):
        state = DummyState("sensor.e", "new")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        info = {
            "entities": {"sensor.e": "new"},
            "params": {"_grid_delivery_step": "mode"},
            "called_at": datetime.now(),
        }
        with caplog.at_level(logging.INFO):
            result = queue_module._entities_match(shield, "svc", info, 15)
        assert "Grid delivery split step detected" in caplog.text

    def test_box_mode_step_logged(self, caplog):
        state = DummyState("sensor.e", "new")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        info = {
            "entities": {"sensor.e": "new"},
            "params": {"_box_mode_step": "mode"},
            "called_at": datetime.now(),
        }
        with caplog.at_level(logging.INFO):
            result = queue_module._entities_match(shield, "svc", info, 15)
        assert "Box mode split step detected" in caplog.text


class TestIsUnavailableValue:
    def test_none(self):
        assert queue_module._is_unavailable_value(None) is True

    def test_empty(self):
        assert queue_module._is_unavailable_value("") is True

    def test_unknown(self):
        assert queue_module._is_unavailable_value("unknown") is True

    def test_unavailable(self):
        assert queue_module._is_unavailable_value("unavailable") is True

    def test_none_string(self):
        assert queue_module._is_unavailable_value("none") is True

    def test_whitespace(self):
        assert queue_module._is_unavailable_value("  ") is True

    def test_valid(self):
        assert queue_module._is_unavailable_value("valid") is False

    def test_int(self):
        assert queue_module._is_unavailable_value(123) is False


class TestIsNumericValue:
    def test_none(self):
        assert queue_module._is_numeric_value(None) is False

    def test_valid_int(self):
        assert queue_module._is_numeric_value(123) is True

    def test_valid_string(self):
        assert queue_module._is_numeric_value("123.5") is True

    def test_invalid(self):
        assert queue_module._is_numeric_value("abc") is False


class TestGetGridDeliveryRelatedEntity:
    def test_limit_to_mode(self):
        result = queue_module._get_grid_delivery_related_entity("sensor.oig_123_invertor_prm1_p_max_feed_grid")
        assert result == "sensor.oig_123_invertor_prms_to_grid"

    def test_mode_to_limit(self):
        result = queue_module._get_grid_delivery_related_entity("sensor.oig_123_invertor_prms_to_grid")
        assert result == "sensor.oig_123_invertor_prm1_p_max_feed_grid"

    def test_unrelated(self):
        assert queue_module._get_grid_delivery_related_entity("sensor.other") is None


class TestShouldRejectCompletionDueToTelemetryLag:
    def test_not_grid_entity(self):
        shield = DummyShield()
        assert queue_module._should_reject_completion_due_to_telemetry_lag(
            shield, "sensor.other", "v", "c", {}
        ) is False

    def test_unavailable(self):
        shield = DummyShield()
        assert queue_module._should_reject_completion_due_to_telemetry_lag(
            shield, "sensor.oig_123_invertor_prm1_p_max_feed_grid", "v", None, {}
        ) is True

    def test_mode_not_limited(self, caplog):
        mode_state = DummyState("sensor.oig_123_invertor_prms_to_grid", "zapnuto")
        hass = DummyHass(DummyStates([mode_state]))
        shield = DummyShield(hass)
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        with caplog.at_level(logging.DEBUG, logger="custom_components.oig_cloud.shield.queue"):
            result = queue_module._should_reject_completion_due_to_telemetry_lag(
                shield, "sensor.oig_123_invertor_prm1_p_max_feed_grid", "500", "500", {}
            )
        assert result is True
        assert "Rejecting limit completion" in caplog.text

    def test_mode_limited(self):
        mode_state = DummyState("sensor.oig_123_invertor_prms_to_grid", "Omezeno")
        hass = DummyHass(DummyStates([mode_state]))
        shield = DummyShield(hass)
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        result = queue_module._should_reject_completion_due_to_telemetry_lag(
            shield, "sensor.oig_123_invertor_prm1_p_max_feed_grid", "500", "500", {}
        )
        assert result is False

    def test_no_related_entity(self):
        shield = DummyShield()
        result = queue_module._should_reject_completion_due_to_telemetry_lag(
            shield, "sensor.oig_123_invertor_prm1_p_max_feed_grid", "500", "500",
            {"sensor.oig_123_invertor_prms_to_grid": "v"}
        )
        assert result is False


class TestNormalizeEntityValues:
    def test_limit_numeric(self):
        shield = DummyShield()
        result = queue_module._normalize_entity_values(
            shield, "sensor.oig_123_invertor_prm1_p_max_feed_grid", 500, 500.4
        )
        assert result == ("500", "500")

    def test_limit_string(self):
        shield = DummyShield()
        result = queue_module._normalize_entity_values(
            shield, "sensor.oig_123_invertor_prm1_p_max_feed_grid", "500", "abc"
        )
        assert result == ("500", "abc")

    def test_limit_one_numeric(self):
        shield = DummyShield()
        result = queue_module._normalize_entity_values(
            shield, "sensor.oig_123_invertor_prm1_p_max_feed_grid", "500", "invalid"
        )
        assert result == ("500", "invalid")

    def test_to_grid_binary_omezeno(self):
        shield = DummyShield()
        result = queue_module._normalize_entity_values(
            shield, "binary_sensor.oig_123_invertor_prms_to_grid", "Omezeno", "Zapnuto"
        )
        assert result[0] == "zapnuto"

    def test_regular_entity(self):
        shield = DummyShield()
        shield._normalize_value = lambda val: validation_module.normalize_value(val)
        result = queue_module._normalize_entity_values(
            shield, "sensor.e", "Home 1", "home1"
        )
        assert result == ("home1", "home1")


class TestHandleEntityCompletion:
    def test_logs(self):
        shield = DummyShield()
        shield._log_event = AsyncMock()
        shield._log_telemetry = AsyncMock()
        asyncio.run(queue_module._handle_entity_completion(
            shield, "svc", {"params": {}, "entities": {}, "original_states": {}}
        ))
        assert shield._log_event.call_count == 2


class TestStartMonitoringTask:
    def test_starts(self):
        shield = DummyShield()
        queue_module.start_monitoring_task(shield, "task1", {"e": "v"}, 60)
        assert "task1" in shield._active_tasks
        assert shield._active_tasks["task1"]["status"] == "monitoring"


class TestCheckEntitiesPeriodically:
    def test_all_match(self):
        state = DummyState("sensor.e", "v")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        shield._get_entity_state = lambda entity_id: "v"
        shield._values_match = lambda current, expected: current == expected
        queue_module.start_monitoring_task(shield, "task1", {"sensor.e": "v"}, 60)
        asyncio.run(queue_module.check_entities_periodically(shield, "task1"))
        assert "task1" in shield._active_tasks

    def test_timeout(self):
        shield = DummyShield()
        shield._get_entity_state = lambda entity_id: "wrong"
        shield._values_match = lambda current, expected: False
        queue_module.start_monitoring_task(shield, "task1", {"sensor.e": "v"}, 0)
        asyncio.run(queue_module.check_entities_periodically(shield, "task1"))
        assert "task1" in shield._active_tasks


class TestStartMonitoring:
    async def test_starts_new(self):
        shield = DummyShield()
        queue_module.start_monitoring(shield)
        assert shield.check_task is not None
        check_task = shield.check_task
        assert check_task is not None
        check_task.cancel()
        try:
            await check_task
        except asyncio.CancelledError:
            pass

    async def test_skips_existing(self, caplog):
        shield = DummyShield()
        existing_task = MagicMock()
        existing_task.done = lambda: False
        shield.check_task = existing_task
        with caplog.at_level(logging.DEBUG, logger="custom_components.oig_cloud.shield.queue"):
            queue_module.start_monitoring(shield)
        assert "již běží" in caplog.text

    async def test_restarts_done(self, caplog):
        shield = DummyShield()
        existing_task = MagicMock()
        existing_task.done = lambda: True
        existing_task.cancelled = lambda: False
        shield.check_task = existing_task
        with caplog.at_level(logging.WARNING, logger="custom_components.oig_cloud.shield.queue"):
            queue_module.start_monitoring(shield)
        assert "Předchozí task byl dokončen" in caplog.text
        restarted_task = shield.check_task
        assert restarted_task is not None
        restarted_task.cancel()
        try:
            await restarted_task
        except asyncio.CancelledError:
            pass


class TestAsyncCheckLoop:
    async def test_loop(self):
        shield = DummyShield()
        shield._is_checking = True
        task = asyncio.create_task(queue_module.async_check_loop(shield))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestNormalizeValue:
    def test_known_mappings(self):
        assert validation_module.normalize_value("off") == "vypnuto"
        assert validation_module.normalize_value("on") == "zapnuto"
        assert validation_module.normalize_value("limited") == "omezeno"
        assert validation_module.normalize_value("manual") == "manualni"
        assert validation_module.normalize_value("cbb") == "cbb"

    def test_unknown(self):
        assert validation_module.normalize_value("something") == "something"

    def test_none(self):
        assert validation_module.normalize_value(None) == ""

    def test_whitespace_cleanup(self):
        assert validation_module.normalize_value("  OFF  ") == "vypnuto"

    def test_special_chars(self):
        assert validation_module.normalize_value("Vypnuto/On") == "vypnuto"


class TestValuesMatch:
    def test_numeric_match(self):
        assert validation_module.values_match(5, "5") is True

    def test_numeric_mismatch(self):
        assert validation_module.values_match(5, "6") is False

    def test_normalized_match(self):
        assert validation_module.values_match("on", "zapnuto") is True

    def test_fallback_string(self):
        assert validation_module.values_match("abc", "abc") is True

    def test_exception_fallback(self):
        assert validation_module.values_match(None, None) is True


class TestGetEntityState:
    def test_exists(self):
        state = DummyState("sensor.e", "v")
        hass = DummyHass(DummyStates([state]))
        assert validation_module.get_entity_state(hass, "sensor.e") == "v"

    def test_missing(self):
        assert validation_module.get_entity_state(DummyHass(), "sensor.e") is None


class TestExtractApiInfo:
    def test_boiler_manual(self):
        result = validation_module.extract_api_info("oig_cloud.set_boiler_mode", {"mode": "Manual"})
        assert result["api_column"] == "manual"
        assert result["api_value"] == 1

    def test_boiler_cbb(self):
        result = validation_module.extract_api_info("oig_cloud.set_boiler_mode", {"mode": "CBB"})
        assert result["api_value"] == 0

    def test_box_mode(self):
        result = validation_module.extract_api_info("oig_cloud.set_box_mode", {"mode": "Home 1"})
        assert result["api_table"] == "box_prms"

    def test_grid_delivery_limit(self):
        result = validation_module.extract_api_info("oig_cloud.set_grid_delivery", {"limit": 500})
        assert result["api_column"] == "p_max_feed_grid"

    def test_grid_delivery_mode(self):
        result = validation_module.extract_api_info("oig_cloud.set_grid_delivery", {"mode": "Limited"})
        assert result["api_column"] == "to_grid"

    def test_unknown_service(self):
        assert validation_module.extract_api_info("unknown", {}) == {}


class TestExpectedFormatingMode:
    def test_returns_fake_entity(self):
        result = validation_module._expected_formating_mode()
        assert len(result) == 1
        assert list(result.values())[0] == "completed_after_timeout"
        assert list(result.keys())[0].startswith("fake_formating_mode_")


class TestExpectedBoilerMode:
    def test_known_mode(self):
        state = DummyState("sensor.oig_123_boiler_manual_mode", "CBB")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            if suffix == "_boiler_manual_mode":
                return "sensor.oig_123_boiler_manual_mode"
            return None

        result = validation_module._expected_boiler_mode(shield, {"mode": "Manual"}, find_entity)
        assert result == {"sensor.oig_123_boiler_manual_mode": "Manuální"}

    def test_unknown_mode(self, caplog):
        shield = DummyShield()
        with caplog.at_level(logging.WARNING):
            result = validation_module._expected_boiler_mode(shield, {"mode": "Unknown"}, lambda s: None)
        assert result == {}
        assert "Unknown boiler mode" in caplog.text

    def test_already_match(self):
        state = DummyState("sensor.oig_123_boiler_manual_mode", "Manuální")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            if suffix == "_boiler_manual_mode":
                return "sensor.oig_123_boiler_manual_mode"
            return None

        result = validation_module._expected_boiler_mode(shield, {"mode": "Manual"}, find_entity)
        assert result == {}

    def test_entity_not_found(self):
        shield = DummyShield()
        result = validation_module._expected_boiler_mode(shield, {"mode": "Manual"}, lambda s: None)
        assert result == {}


class TestExpectedGridDelivery:
    def test_limit_only(self):
        state = DummyState("sensor.oig_123_invertor_prm1_p_max_feed_grid", "100")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            if suffix == "_invertor_prm1_p_max_feed_grid":
                return "sensor.oig_123_invertor_prm1_p_max_feed_grid"
            return None

        result = validation_module._expected_grid_delivery(shield, {"limit": 500}, find_entity)
        assert result == {"sensor.oig_123_invertor_prm1_p_max_feed_grid": "500"}

    def test_mode_only(self):
        state = DummyState("sensor.oig_123_invertor_prms_to_grid", "Vypnuto")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            if suffix == "_invertor_prms_to_grid":
                return "sensor.oig_123_invertor_prms_to_grid"
            return None

        result = validation_module._expected_grid_delivery(shield, {"mode": "Zapnuto / On"}, find_entity)
        assert result == {"sensor.oig_123_invertor_prms_to_grid": "Zapnuto"}

    def test_both_logs_error(self, caplog):
        shield = DummyShield()
        with caplog.at_level(logging.ERROR):
            result = validation_module._expected_grid_delivery(shield, {"mode": "On", "limit": 500}, lambda s: None)
        assert result == {}
        assert "CHYBA: grid_delivery dostalo mode + limit současně" in caplog.text

    def test_neither(self):
        shield = DummyShield()
        result = validation_module._expected_grid_delivery(shield, {}, lambda s: None)
        assert result == {}


class TestExpectedGridDeliveryLimit:
    def test_invalid_limit(self):
        shield = DummyShield()
        result = validation_module._expected_grid_delivery_limit(shield, {"limit": "abc"}, lambda s: None)
        assert result == {}

    def test_entity_not_found(self):
        shield = DummyShield()
        result = validation_module._expected_grid_delivery_limit(shield, {"limit": 500}, lambda s: None)
        assert result == {}

    def test_unavailable_entity(self):
        state = DummyState("sensor.e", "unavailable")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            return "sensor.e"

        result = validation_module._expected_grid_delivery_limit(shield, {"limit": 500}, find_entity)
        assert result == {"sensor.e": "500"}

    def test_already_match(self):
        state = DummyState("sensor.e", "500")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            return "sensor.e"

        result = validation_module._expected_grid_delivery_limit(shield, {"limit": 500}, find_entity)
        assert result == {}

    def test_valid_change(self):
        state = DummyState("sensor.e", "100")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            return "sensor.e"

        result = validation_module._expected_grid_delivery_limit(shield, {"limit": 500}, find_entity)
        assert result == {"sensor.e": "500"}


class TestExpectedGridDeliveryMode:
    def test_unknown_mode(self, caplog):
        shield = DummyShield()
        with caplog.at_level(logging.WARNING):
            result = validation_module._expected_grid_delivery_mode(shield, {"mode": "Unknown"}, lambda s: None)
        assert result == {}
        assert "Unknown grid delivery mode" in caplog.text

    def test_entity_not_found(self):
        shield = DummyShield()
        result = validation_module._expected_grid_delivery_mode(shield, {"mode": "On"}, lambda s: None)
        assert result == {}

    def test_unavailable_entity(self):
        state = DummyState("sensor.e", "unavailable")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            return "sensor.e"

        result = validation_module._expected_grid_delivery_mode(shield, {"mode": "On"}, find_entity)
        assert result == {"sensor.e": "Zapnuto"}

    def test_already_match(self):
        state = DummyState("sensor.e", "Zapnuto")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            return "sensor.e"

        result = validation_module._expected_grid_delivery_mode(shield, {"mode": "On"}, find_entity)
        assert result == {}

    def test_valid_change(self):
        state = DummyState("sensor.e", "Vypnuto")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            return "sensor.e"

        result = validation_module._expected_grid_delivery_mode(shield, {"mode": "On"}, find_entity)
        assert result == {"sensor.e": "Zapnuto"}


class TestResolveBoxId:
    def test_from_entry_box_id(self):
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        assert validation_module._resolve_box_id_from_entry(entry) == "123"

    def test_from_entry_inverter_sn(self):
        entry = SimpleNamespace(options={}, data={"inverter_sn": "456"})
        assert validation_module._resolve_box_id_from_entry(entry) == "456"

    def test_from_entry_none(self):
        entry = SimpleNamespace(options={}, data={})
        assert validation_module._resolve_box_id_from_entry(entry) is None

    def test_from_entry_non_digit(self):
        entry = SimpleNamespace(options={"box_id": "abc"}, data={})
        assert validation_module._resolve_box_id_from_entry(entry) is None

    def test_from_coordinator(self):
        shield = DummyShield()
        assert validation_module._resolve_box_id_from_coordinator(shield) is None

    def test_for_shield_from_entry(self):
        shield = DummyShield()
        shield.entry.options = {"box_id": "123"}
        assert validation_module._resolve_box_id_for_shield(shield) == "123"

    def test_for_shield_from_coordinator(self):
        entry = DummyEntry()
        entry.options = {}
        shield = DummyShield(entry=entry)
        assert validation_module._resolve_box_id_for_shield(shield) is None


class TestFindShieldCoordinator:
    def test_found(self):
        shield = DummyShield()
        shield.hass.data["oig_cloud"] = {
            "entry1": {"service_shield": shield, "coordinator": "coordinator"}
        }
        assert validation_module._find_shield_coordinator(shield) == "coordinator"

    def test_not_found(self):
        shield = DummyShield()
        assert validation_module._find_shield_coordinator(shield) is None

    def test_non_dict_entry(self):
        shield = DummyShield()
        shield.hass.data["oig_cloud"] = {"entry1": "not_a_dict"}
        assert validation_module._find_shield_coordinator(shield) is None


class TestFindEntityBySuffix:
    def test_exact_match(self):
        state = DummyState("sensor.oig_123_box_prms_mode", "Home 1")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        result = validation_module._find_entity_by_suffix(shield, "123", "_box_prms_mode")
        assert result == "sensor.oig_123_box_prms_mode"

    def test_suffix_match(self):
        state1 = DummyState("sensor.oig_123_box_prms_mode_2", "Home 1")
        hass = DummyHass(DummyStates([state1]))
        shield = DummyShield(hass)
        result = validation_module._find_entity_by_suffix(shield, "123", "_box_prms_mode")
        assert result == "sensor.oig_123_box_prms_mode_2"

    def test_exact_preferred_over_suffix(self):
        state1 = DummyState("sensor.oig_123_box_prms_mode", "Home 1")
        state2 = DummyState("sensor.oig_123_box_prms_mode_2", "Home 2")
        hass = DummyHass(DummyStates([state1, state2]))
        shield = DummyShield(hass)
        result = validation_module._find_entity_by_suffix(shield, "123", "_box_prms_mode")
        assert result == "sensor.oig_123_box_prms_mode"

    def test_no_match(self):
        shield = DummyShield()
        assert validation_module._find_entity_by_suffix(shield, "123", "_missing") is None


class TestIsEntityUnavailable:
    def test_missing(self):
        shield = DummyShield()
        assert validation_module._is_entity_unavailable(shield, "sensor.missing") is True

    def test_unavailable(self):
        state = DummyState("sensor.e", "unavailable")
        shield = DummyShield(DummyHass(DummyStates([state])))
        assert validation_module._is_entity_unavailable(shield, "sensor.e") is True

    def test_available(self):
        state = DummyState("sensor.e", "ok")
        shield = DummyShield(DummyHass(DummyStates([state])))
        assert validation_module._is_entity_unavailable(shield, "sensor.e") is False


class TestCheckEntityStateChange:
    def test_exists_and_matches(self):
        state = DummyState("sensor.oig_123_box_prms_mode", "Home 1")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        assert validation_module.check_entity_state_change(shield, "sensor.oig_123_box_prms_mode", "Home 1") is True

    def test_missing_entity(self):
        shield = DummyShield()
        assert validation_module.check_entity_state_change(shield, "sensor.missing", "v") is False

    def test_boiler_mode(self):
        state = DummyState("sensor.oig_123_boiler_manual_mode", "CBB")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        assert validation_module.check_entity_state_change(shield, "sensor.oig_123_boiler_manual_mode", 0) is True
        assert validation_module.check_entity_state_change(shield, "sensor.oig_123_boiler_manual_mode", 1) is False

    def test_ssr_mode(self):
        state = DummyState("sensor.oig_123_ssr", "Vypnuto")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        assert validation_module.check_entity_state_change(shield, "sensor.oig_123_ssr", 0) is True
        assert validation_module.check_entity_state_change(shield, "sensor.oig_123_ssr", 1) is False

    def test_box_prm2_app(self):
        state = DummyState("sensor.oig_123_box_prm2_app", "2")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        assert validation_module.check_entity_state_change(shield, "sensor.oig_123_box_prm2_app", 2) is True
        assert validation_module.check_entity_state_change(shield, "sensor.oig_123_box_prm2_app", 4) is False

    def test_inverter_mode(self):
        state = DummyState("sensor.oig_123_invertor_prms_to_grid", "Omezeno")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        assert validation_module.check_entity_state_change(shield, "sensor.oig_123_invertor_prms_to_grid", "Omezeno") is True

    def test_numeric_match(self):
        state = DummyState("sensor.oig_123_p_max_feed_grid", "500")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        assert validation_module.check_entity_state_change(shield, "sensor.oig_123_p_max_feed_grid", 500) is True

    def test_generic_match(self):
        state = DummyState("sensor.oig_123_other", "abc")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        assert validation_module.check_entity_state_change(shield, "sensor.oig_123_other", "abc") is True


class TestSelectEntityMatcher:
    def test_all_patterns(self):
        matchers = [
            ("boiler_manual_mode", lambda e, c: c == "CBB"),
            ("ssr", lambda e, c: c == "Vypnuto"),
            ("box_prms_mode", lambda e, c: c == "Home 1"),
            ("box_prm2_app", lambda e, c: c == 1),
            ("invertor_prms_to_grid", lambda e, c: c == "Zapnuto"),
            ("p_max_feed_grid", lambda e, c: c == 500),
            ("unknown", lambda e, c: c == "abc"),
        ]
        for marker, _ in matchers:
            matcher = validation_module._select_entity_matcher(f"sensor.oig_123_{marker}")
            assert callable(matcher)

    def test_wrap_matcher(self):
        matcher = validation_module._wrap_matcher(lambda e, c: e == c)
        assert matcher("any", "a", "a") is True
        assert matcher("any", "a", "b") is False


class TestMatchesBoilerMode:
    def test_cbb(self):
        assert validation_module._matches_boiler_mode(0, "CBB") is True
        assert validation_module._matches_boiler_mode(1, "CBB") is False

    def test_manual(self):
        assert validation_module._matches_boiler_mode(1, "Manuální") is True
        assert validation_module._matches_boiler_mode(0, "Manuální") is False


class TestMatchesSsrMode:
    def test_off(self):
        assert validation_module._matches_ssr_mode(0, "Vypnuto") is True
        assert validation_module._matches_ssr_mode(1, "Vypnuto") is False

    def test_on(self):
        assert validation_module._matches_ssr_mode(1, "Zapnuto") is True
        assert validation_module._matches_ssr_mode(0, "Zapnuto") is False


class TestMatchesBoxMode:
    def test_string_match(self):
        assert validation_module._matches_box_mode("Home 1", "Home 1") is True

    def test_digit_string(self):
        assert validation_module._matches_box_mode("0", "Home 1") is True

    def test_int(self):
        assert validation_module._matches_box_mode(1, "Home 2") is True

    def test_mismatch(self):
        assert validation_module._matches_box_mode("Home 1", "Home 2") is False


class TestMatchesInverterMode:
    def test_vypnuto(self):
        assert validation_module._matches_inverter_mode("e", "Vypnuto", "Vypnuto") is True
        assert validation_module._matches_inverter_mode("e", "Vypnuto", "Zapnuto") is False

    def test_zapnuto_binary(self):
        assert validation_module._matches_inverter_mode("binary_sensor.e", "Zapnuto", "Omezeno") is True

    def test_zapnuto_sensor(self):
        assert validation_module._matches_inverter_mode("sensor.e", "Zapnuto", "Zapnuto") is True
        assert validation_module._matches_inverter_mode("sensor.e", "Zapnuto", "Omezeno") is False

    def test_omezeno_binary(self):
        assert validation_module._matches_inverter_mode("binary_sensor.e", "Omezeno", "Zapnuto") is True

    def test_numeric_expected(self):
        assert validation_module._matches_inverter_mode("e", 1, "Zapnuto") is True
        assert validation_module._matches_inverter_mode("e", 0, "Vypnuto") is True

    def test_unknown(self):
        assert validation_module._matches_inverter_mode("e", "unknown", "Vypnuto") is False


class TestMatchesNumeric:
    def test_match(self):
        assert validation_module._matches_numeric(500, "500") is True

    def test_mismatch(self):
        assert validation_module._matches_numeric(500, "501") is False

    def test_invalid(self):
        assert validation_module._matches_numeric("abc", "def") is False


class TestMatchesGeneric:
    def test_float_match(self):
        assert validation_module._matches_generic(1.5, "1.5") is True

    def test_string_match(self):
        assert validation_module._matches_generic("abc", "abc") is True

    def test_mismatch(self):
        assert validation_module._matches_generic("a", "b") is False

    def test_invalid_float_fallback(self):
        assert validation_module._matches_generic("a", "a") is True


class TestExtractExpectedEntities:
    def test_formating_mode(self):
        shield = DummyShield()
        result = validation_module.extract_expected_entities(shield, "oig_cloud.set_formating_mode", {})
        assert len(result) == 1
        assert list(result.values())[0] == "completed_after_timeout"

    def test_boiler_mode(self):
        state = DummyState("sensor.oig_123_boiler_manual_mode", "CBB")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        result = validation_module.extract_expected_entities(shield, "oig_cloud.set_boiler_mode", {"mode": "Manual"})
        assert "sensor.oig_123_boiler_manual_mode" in result

    def test_grid_delivery(self):
        state = DummyState("sensor.oig_123_invertor_prms_to_grid", "Vypnuto")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)
        result = validation_module.extract_expected_entities(shield, "oig_cloud.set_grid_delivery", {"mode": "On"})
        assert "sensor.oig_123_invertor_prms_to_grid" in result

    def test_unknown_service(self):
        shield = DummyShield()
        result = validation_module.extract_expected_entities(shield, "unknown", {})
        assert result == {}

    def test_missing_box_id(self, caplog):
        shield = DummyShield()
        shield.entry.options = {}
        with caplog.at_level(logging.WARNING):
            result = validation_module.extract_expected_entities(shield, "oig_cloud.set_box_mode", {"mode": "Home 1"})
        assert shield._expected_entity_missing is True
        assert "box_id nelze určit" in caplog.text


class TestExpectedBoxMode:
    def test_app_step_no_toggles_raises(self):
        state = DummyState("sensor.oig_123_box_prm2_app", "1")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            if suffix == "_box_prm2_app":
                return "sensor.oig_123_box_prm2_app"
            return None

        with pytest.raises(vol.Invalid):
            validation_module._expected_box_mode(shield, {"_box_mode_step": "app"}, find_entity)

    def test_app_entity_missing_raises(self):
        shield = DummyShield()
        with pytest.raises(vol.Invalid):
            validation_module._expected_box_mode(shield, {"home_grid_v": True, "_box_mode_step": "app"}, lambda s: None)

    def test_app_step_flexibilita_no_toggles(self):
        state = DummyState("sensor.oig_123_box_prm2_app", "4")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            if suffix == "_box_prm2_app":
                return "sensor.oig_123_box_prm2_app"
            return None

        result = validation_module._expected_box_mode(shield, {"home_grid_v": None, "home_grid_vi": None, "_box_mode_step": "app"}, find_entity)
        assert result == {}

    def test_app_step_flexibilita_active_raises(self):
        state = DummyState("sensor.oig_123_box_prm2_app", "4")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            if suffix == "_box_prm2_app":
                return "sensor.oig_123_box_prm2_app"
            return None

        with pytest.raises(vol.Invalid):
            validation_module._expected_box_mode(shield, {"home_grid_v": False, "home_grid_vi": False, "_box_mode_step": "app"}, find_entity)

    def test_app_step_invalid_state_raises(self):
        state = DummyState("sensor.oig_123_box_prm2_app", "invalid")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            if suffix == "_box_prm2_app":
                return "sensor.oig_123_box_prm2_app"
            return None

        with pytest.raises(vol.Invalid):
            validation_module._expected_box_mode(shield, {"home_grid_v": True, "_box_mode_step": "app"}, find_entity)

    def test_app_step_unavailable_raises(self):
        state = DummyState("sensor.oig_123_box_prm2_app", "unavailable")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            if suffix == "_box_prm2_app":
                return "sensor.oig_123_box_prm2_app"
            return None

        with pytest.raises(vol.Invalid):
            validation_module._expected_box_mode(shield, {"home_grid_v": True, "_box_mode_step": "app"}, find_entity)

    def test_mode_step_no_change(self):
        state = DummyState("sensor.oig_123_box_prms_mode", "Home 1")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            if suffix == "_box_prms_mode":
                return "sensor.oig_123_box_prms_mode"
            return None

        result = validation_module._expected_box_mode(shield, {"mode": "Home 1"}, find_entity)
        assert result == {}

    def test_mode_step_numeric_mapping(self):
        state = DummyState("sensor.oig_123_box_prms_mode", "Home 2")
        hass = DummyHass(DummyStates([state]))
        shield = DummyShield(hass)

        def find_entity(suffix):
            if suffix == "_box_prms_mode":
                return "sensor.oig_123_box_prms_mode"
            return None

        result = validation_module._expected_box_mode(shield, {"mode": "0"}, find_entity)
        assert result == {"sensor.oig_123_box_prms_mode": "Home 1"}

    def test_no_mode_no_toggles(self):
        shield = DummyShield()
        result = validation_module._expected_box_mode(shield, {}, lambda s: None)
        assert result == {}
