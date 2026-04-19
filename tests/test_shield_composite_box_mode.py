"""Tests for composite set_box_mode split and verification in ServiceShield.

These tests verify that:
1. set_box_mode(mode+toggles) is split into two ordered steps
2. Mode step is ALWAYS first
3. App (toggle) step is ALWAYS second
4. Step metadata is properly tracked
5. box_prm2_app matcher validates numeric values correctly
6. Toggle-only calls emit box_prm2_app expectation
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.oig_cloud.shield import dispatch as dispatch_module
from custom_components.oig_cloud.shield import validation as validation_module
from custom_components.oig_cloud.shield import queue as queue_module


class DummyState:
    def __init__(self, entity_id, state):
        self.entity_id = entity_id
        self.state = state


class DummyStates:
    def __init__(self, states):
        self._states = {state.entity_id: state for state in states}

    def get(self, entity_id):
        return self._states.get(entity_id)

    def async_all(self, domain=None):
        if domain is None:
            return list(self._states.values())
        prefix = f"{domain}."
        return [state for entity_id, state in self._states.items() if entity_id.startswith(prefix)]


class DummyHass:
    def __init__(self, states):
        self.states = states
        self.data = {"oig_cloud": {}}

    def async_create_task(self, task):
        return task


class DummyShield:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.last_checked_entity_id = None
        self.queue = []
        self.pending = {}
        self.running = None
        self.queue_metadata = {}
        self._is_checking = False

    def _normalize_value(self, val):
        return validation_module.normalize_value(val)


class DummyInterceptShield(DummyShield):
    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self.extract_expected_entities = lambda _service_name, _params: {
            "sensor.oig_123_box_prms_mode": "Home 1"
        }
        self._extract_api_info = lambda _service_name, _params: {}
        self._log_security_event = lambda *_args, **_kwargs: None
        self._notify_state_change = lambda: None
        self._check_loop = lambda _when: None
        self._log_event = AsyncMock()
        self._log_telemetry = AsyncMock()


class TestSplitBoxModeParams:
    """Tests for _split_box_mode_params function."""

    def test_split_both_mode_and_toggles(self):
        """When both mode and toggles are present, split into ordered steps."""
        params = {"mode": "home_1", "home_grid_v": True, "home_grid_vi": False}

        result = dispatch_module._split_box_mode_params(params)

        assert result is not None
        assert len(result) == 2

        # Step 1: Mode only, with step metadata
        step1 = result[0]
        assert "home_grid_v" not in step1
        assert "home_grid_vi" not in step1
        assert step1["mode"] == "home_1"
        assert step1["_box_mode_step"] == "mode"

        # Step 2: Toggles only, with step metadata
        step2 = result[1]
        assert "mode" not in step2
        assert step2["home_grid_v"] is True
        assert step2["home_grid_vi"] is False
        assert step2["_box_mode_step"] == "app"

    def test_split_preserves_other_params(self):
        """Splitting preserves all other parameters."""
        params = {"mode": "home_1", "home_grid_v": True, "device_id": "123", "acknowledgement": True}

        result = dispatch_module._split_box_mode_params(params)

        assert result is not None
        assert len(result) == 2

        # Both steps should preserve device_id and acknowledgement
        assert result[0]["device_id"] == "123"
        assert result[0]["acknowledgement"] is True
        assert result[1]["device_id"] == "123"
        assert result[1]["acknowledgement"] is True

    def test_no_split_when_only_mode(self):
        """When only mode is present, no split occurs."""
        params = {"mode": "home_1"}

        result = dispatch_module._split_box_mode_params(params)

        assert result is None

    def test_no_split_when_only_toggles(self):
        """When only toggles are present, no split occurs."""
        params = {"home_grid_v": True, "home_grid_vi": False}

        result = dispatch_module._split_box_mode_params(params)

        assert result is None

    def test_no_split_when_no_toggles(self):
        """When no recognized toggles are present, no split occurs."""
        params = {"mode": "home_1", "unknown_param": True}

        result = dispatch_module._split_box_mode_params(params)

        assert result is None


class TestMatchesBoxPrm2App:
    """Tests for _matches_box_prm2_app matcher."""

    def test_matcher_validates_numeric_match(self):
        """Matcher returns True when numeric values match."""
        assert validation_module._matches_box_prm2_app(1, 1) is True
        assert validation_module._matches_box_prm2_app(0, 0) is True
        assert validation_module._matches_box_prm2_app(3, 3) is True

    def test_matcher_rejects_numeric_mismatch(self):
        """Matcher returns False when numeric values differ."""
        assert validation_module._matches_box_prm2_app(1, 0) is False
        assert validation_module._matches_box_prm2_app(0, 1) is False
        assert validation_module._matches_box_prm2_app(2, 3) is False

    def test_matcher_handles_string_numeric(self):
        """Matcher handles string-formatted numeric values."""
        assert validation_module._matches_box_prm2_app("1", 1) is True
        assert validation_module._matches_box_prm2_app(1, "1") is True
        assert validation_module._matches_box_prm2_app("1", "1") is True

    def test_matcher_rejects_app_4(self):
        """Matcher must not allow app=4 as matching value."""
        assert validation_module._matches_box_prm2_app(4, 4) is False
        assert validation_module._matches_box_prm2_app("4", 4) is False


class TestExpectedBoxModeValidation:
    """Tests for _expected_box_mode with composite and toggle-only calls."""

    def test_expected_box_mode_mode_step(self):
        """Mode step returns box_prms_mode expectation."""
        entity = DummyState("sensor.oig_123_box_prms_mode", "Home 2")
        hass = DummyHass(DummyStates([entity]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)

        def find_entity(suffix):
            if suffix == "_box_prms_mode":
                return "sensor.oig_123_box_prms_mode"
            if suffix == "_box_prm2_app":
                return "sensor.oig_123_box_prm2_app"
            return None

        data = {"mode": "home_1", "_box_mode_step": "mode"}
        result = validation_module._expected_box_mode(shield, data, find_entity)

        assert result == {"sensor.oig_123_box_prms_mode": "Home 1"}

    def test_expected_box_mode_app_step(self):
        """App step returns box_prm2_app expectation using build_app_value."""
        mode_entity = DummyState("sensor.oig_123_box_prms_mode", "Home 1")
        app_entity = DummyState("sensor.oig_123_box_prm2_app", "0")
        hass = DummyHass(DummyStates([mode_entity, app_entity]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)

        def find_entity(suffix):
            if suffix == "_box_prms_mode":
                return "sensor.oig_123_box_prms_mode"
            if suffix == "_box_prm2_app":
                return "sensor.oig_123_box_prm2_app"
            return None

        data = {"home_grid_v": True, "home_grid_vi": False, "_box_mode_step": "app"}
        result = validation_module._expected_box_mode(shield, data, find_entity)

        # build_app_value(0, None, 0) -> 1? Wait, home_grid_v=True -> result = 0 | 1 = 1
        # home_grid_vi=False -> result = 1 & ~2 = 1
        assert result == {"sensor.oig_123_box_prm2_app": 1}

    def test_expected_box_mode_toggle_only(self):
        """Toggle-only call returns box_prm2_app expectation."""
        app_entity = DummyState("sensor.oig_123_box_prm2_app", "2")
        hass = DummyHass(DummyStates([app_entity]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)

        def find_entity(suffix):
            if suffix == "_box_prm2_app":
                return "sensor.oig_123_box_prm2_app"
            return None

        data = {"home_grid_v": True, "home_grid_vi": False}
        result = validation_module._expected_box_mode(shield, data, find_entity)

        # build_app_value(True, False, 2) -> (2 | 1) & ~2 = 3 & ~2 = 1
        assert result == {"sensor.oig_123_box_prm2_app": 1}

    def test_expected_box_mode_app_step_skips_if_already_match(self):
        """App step returns empty if box_prm2_app already matches."""
        app_entity = DummyState("sensor.oig_123_box_prm2_app", "1")
        hass = DummyHass(DummyStates([app_entity]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)

        def find_entity(suffix):
            if suffix == "_box_prm2_app":
                return "sensor.oig_123_box_prm2_app"
            return None

        data = {"home_grid_v": True, "home_grid_vi": False, "_box_mode_step": "app"}
        result = validation_module._expected_box_mode(shield, data, find_entity)

        # Already 1, no change needed
        assert result == {}

    def test_expected_box_mode_app_step_no_toggles_raises(self):
        """App step with no toggles specified raises vol.Invalid."""
        app_entity = DummyState("sensor.oig_123_box_prm2_app", "1")
        hass = DummyHass(DummyStates([app_entity]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)

        def find_entity(suffix):
            if suffix == "_box_prm2_app":
                return "sensor.oig_123_box_prm2_app"
            return None

        import voluptuous as vol

        # No toggles specified - should raise Invalid
        data = {"_box_mode_step": "app"}
        with pytest.raises(vol.Invalid):
            validation_module._expected_box_mode(shield, data, find_entity)

    def test_expected_box_mode_mode_step_skips_if_already_match(self):
        """Mode step returns empty if box_prms_mode already matches."""
        entity = DummyState("sensor.oig_123_box_prms_mode", "Home 1")
        hass = DummyHass(DummyStates([entity]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)

        def find_entity(suffix):
            if suffix == "_box_prms_mode":
                return "sensor.oig_123_box_prms_mode"
            return None

        data = {"mode": "home_1", "_box_mode_step": "mode"}
        result = validation_module._expected_box_mode(shield, data, find_entity)

        assert result == {}

    def test_expected_box_mode_without_step_defaults_to_mode(self):
        """Without step metadata, mode-present params use existing mode behavior."""
        entity = DummyState("sensor.oig_123_box_prms_mode", "Home 2")
        hass = DummyHass(DummyStates([entity]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)

        def find_entity(suffix):
            if suffix == "_box_prms_mode":
                return "sensor.oig_123_box_prms_mode"
            return None

        data = {"mode": "home_1"}
        result = validation_module._expected_box_mode(shield, data, find_entity)

        assert result == {"sensor.oig_123_box_prms_mode": "Home 1"}

    def test_expected_box_mode_rejects_app_value_4(self):
        """App step must not emit expected value of 4."""
        app_entity = DummyState("sensor.oig_123_box_prm2_app", "4")
        hass = DummyHass(DummyStates([app_entity]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)

        def find_entity(suffix):
            if suffix == "_box_prm2_app":
                return "sensor.oig_123_box_prm2_app"
            return None

        # Toggles that would preserve app=4 (current_raw=4, no toggles that change it)
        data = {"home_grid_v": None, "home_grid_vi": None, "_box_mode_step": "app"}
        result = validation_module._expected_box_mode(shield, data, find_entity)

        assert result == {}

    def test_expected_box_mode_app_entity_missing_raises(self):
        """App step raises vol.Invalid if box_prm2_app entity not found."""
        hass = DummyHass(DummyStates([]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)

        def find_entity(suffix):
            return None

        import voluptuous as vol

        data = {"home_grid_v": True, "_box_mode_step": "app"}
        with pytest.raises(vol.Invalid):
            validation_module._expected_box_mode(shield, data, find_entity)


class TestSelectEntityMatcher:
    """Tests for _select_entity_matcher with box_prm2_app registration."""

    def test_box_prm2_app_uses_numeric_matcher(self):
        """box_prm2_app entity uses the _matches_box_prm2_app matcher."""
        matcher = validation_module._select_entity_matcher("sensor.oig_123_box_prm2_app")

        # Should match when values are equal numerically
        assert matcher("sensor.oig_123_box_prm2_app", 1, 1) is True
        # Should NOT match when values differ
        assert matcher("sensor.oig_123_box_prm2_app", 1, 0) is False
        # Should NOT allow app=4
        assert matcher("sensor.oig_123_box_prm2_app", 4, 4) is False


class TestQueueEntitiesMatch:
    """Tests for _entities_match in queue module with box mode step handling."""

    def test_entities_match_logs_box_mode_step(self, caplog):
        """Queue entities_match logs box mode step when present."""
        import logging

        entity = DummyState("sensor.oig_123_box_prms_mode", "Home 1")
        hass = DummyHass(DummyStates([entity]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)

        info = {
            "entities": {"sensor.oig_123_box_prms_mode": "Home 1"},
            "params": {"_box_mode_step": "mode", "mode": "home_1"},
            "called_at": __import__('datetime').datetime.now(),
        }

        with caplog.at_level(logging.INFO):
            result = queue_module._entities_match(
                shield, "oig_cloud.set_box_mode", info, 15
            )

        assert result is True
        assert "Box mode split step detected: mode" in caplog.text

    def test_entities_match_logs_app_step(self, caplog):
        """Queue entities_match logs app step when present."""
        import logging

        entity = DummyState("sensor.oig_123_box_prm2_app", "1")
        hass = DummyHass(DummyStates([entity]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)

        info = {
            "entities": {"sensor.oig_123_box_prm2_app": 1},
            "params": {"_box_mode_step": "app", "home_grid_v": True},
            "called_at": __import__('datetime').datetime.now(),
        }

        with caplog.at_level(logging.INFO):
            result = queue_module._entities_match(
                shield, "oig_cloud.set_box_mode", info, 15
            )

        assert result is True
        assert "Box mode split step detected: app" in caplog.text


class TestIntegrationSplitFlow:
    """Integration tests for the complete composite box mode split flow."""

    def test_split_flow_ordering(self):
        """Verify split flow always orders mode before app."""
        params = {"mode": "home_1", "home_grid_v": True, "home_grid_vi": False}

        result = dispatch_module._split_box_mode_params(params)

        assert result is not None
        assert len(result) == 2

        # First step MUST be mode
        assert result[0]["_box_mode_step"] == "mode"
        assert "mode" in result[0]
        assert "home_grid_v" not in result[0]

        # Second step MUST be app
        assert result[1]["_box_mode_step"] == "app"
        assert "home_grid_v" in result[1]
        assert "mode" not in result[1]

    def test_step_metadata_preserved_through_validation(self):
        """Step metadata is preserved through validation."""
        mode_entity = DummyState("sensor.oig_123_box_prms_mode", "Home 2")
        app_entity = DummyState("sensor.oig_123_box_prm2_app", "0")
        hass = DummyHass(DummyStates([mode_entity, app_entity]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)

        # Test mode step
        mode_data = {"mode": "home_1", "_box_mode_step": "mode"}
        mode_result = validation_module._expected_box_mode(shield, mode_data, lambda s: f"sensor.oig_123{s}")

        assert mode_result == {"sensor.oig_123_box_prms_mode": "Home 1"}

        # Test app step
        app_data = {"home_grid_v": True, "home_grid_vi": False, "_box_mode_step": "app"}
        app_result = validation_module._expected_box_mode(shield, app_data, lambda s: f"sensor.oig_123{s}")

        assert app_result == {"sensor.oig_123_box_prm2_app": 1}

    def test_handle_split_box_mode_queues_both_steps_in_order(self, monkeypatch):
        """Split handler forwards mode step first and app step second."""
        hass = DummyHass(DummyStates([]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)
        recorded_calls = []

        async def fake_intercept(*args):
            recorded_calls.append(args[3]["params"])

        monkeypatch.setattr(dispatch_module, "intercept_service_call", fake_intercept)

        result = asyncio.run(
            dispatch_module._handle_split_box_mode(
                shield,
                "oig_cloud",
                "set_box_mode",
                {"mode": "home_1", "home_grid_v": True, "home_grid_vi": False},
                AsyncMock(),
                False,
                None,
            )
        )

        assert result is True
        assert recorded_calls == [
            {"mode": "home_1", "_box_mode_step": "mode"},
            {"home_grid_v": True, "home_grid_vi": False, "_box_mode_step": "app"},
        ]

    def test_two_back_to_back_composite_requests_serialized(self, monkeypatch):
        """Two composite requests are fully serialized: mode1→app1→mode2→app2."""
        hass = DummyHass(DummyStates([]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyShield(hass, entry)
        recorded_calls = []

        async def fake_intercept(*args):
            recorded_calls.append(args[3]["params"])

        monkeypatch.setattr(dispatch_module, "intercept_service_call", fake_intercept)

        req1 = {"mode": "home_1", "home_grid_v": True}
        req2 = {"mode": "home_2", "home_grid_v": False}

        asyncio.run(
            dispatch_module._handle_split_box_mode(
                shield, "oig_cloud", "set_box_mode", req1, AsyncMock(), False, None
            )
        )
        asyncio.run(
            dispatch_module._handle_split_box_mode(
                shield, "oig_cloud", "set_box_mode", req2, AsyncMock(), False, None
            )
        )

        assert recorded_calls == [
            {"mode": "home_1", "_box_mode_step": "mode"},
            {"home_grid_v": True, "_box_mode_step": "app"},
            {"mode": "home_2", "_box_mode_step": "mode"},
            {"home_grid_v": False, "_box_mode_step": "app"},
        ]

    def test_intercept_service_call_uses_split_for_composite_box_mode(self, monkeypatch):
        """intercept_service_call delegates composite set_box_mode to split handler."""
        hass = DummyHass(DummyStates([]))
        entry = SimpleNamespace(options={"box_id": "123"}, data={})
        shield = DummyInterceptShield(hass, entry)

        split_called = []

        async def fake_handle_split(*args, **kwargs):
            split_called.append(args[3])
            return True

        monkeypatch.setattr(dispatch_module, "_handle_split_box_mode", fake_handle_split)

        asyncio.run(
            dispatch_module.intercept_service_call(
                shield,
                "oig_cloud",
                "set_box_mode",
                {"params": {"mode": "home_1", "home_grid_v": True}},
                AsyncMock(),
                False,
                None,
            )
        )

        assert len(split_called) == 1
        assert split_called[0]["mode"] == "home_1"


class TestShieldSensorDescriptions:
    """Tests for shield_sensor queue target descriptions."""

    def test_box_prm2_app_param_type(self):
        """box_prm2_app entity is recognized in param type extraction."""
        from custom_components.oig_cloud.entities.shield_sensor import _extract_param_type

        assert _extract_param_type("sensor.oig_123_box_prm2_app") == "app"

    def test_existing_param_types_unchanged(self):
        """Existing param type extractions remain unchanged."""
        from custom_components.oig_cloud.entities.shield_sensor import _extract_param_type

        assert _extract_param_type("sensor.oig_123_box_prms_mode") == "mode"
        assert _extract_param_type("sensor.oig_123_invertor_prm1_p_max_feed_grid") == "limit"
        assert _extract_param_type("sensor.oig_123_invertor_prms_to_grid") == "mode"
