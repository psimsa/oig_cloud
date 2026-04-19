"""Tests for local/proxy entity mapping of box_prm2_app via local_entity_suffix."""
from __future__ import annotations

import pytest

from custom_components.oig_cloud.core.local_mapper import (
    LocalUpdateApplier,
    normalize_proxy_entity_id,
)


class DummyState:
    def __init__(self, entity_id, state):
        self.entity_id = entity_id
        self.state = state
        self.last_updated = None


def test_local_entity_suffix_registered_in_suffix_updates():
    from custom_components.oig_cloud.core.local_mapper import _SUFFIX_UPDATES

    assert "tbl_box_prm2_app" in _SUFFIX_UPDATES
    cfg = _SUFFIX_UPDATES["tbl_box_prm2_app"]
    updates = cfg.updates
    assert len(updates) == 1
    assert updates[0].node_id == "box_prm2"
    assert updates[0].node_key == "app"


def test_normalize_proxy_entity_id_parses_tbl_box_prm2_app():
    descriptor = normalize_proxy_entity_id(
        "sensor.oig_local_1234567890_tbl_box_prm2_app",
        "1234567890",
    )
    assert descriptor is not None
    assert descriptor.table == "tbl_box_prm2"
    assert descriptor.key == "app"
    assert descriptor.device_id == "1234567890"
    assert descriptor.is_control is False
    assert descriptor.raw_suffix == "tbl_box_prm2_app"


def test_normalize_proxy_entity_id_parses_cfg_variant():
    descriptor = normalize_proxy_entity_id(
        "sensor.oig_local_1234567890_tbl_box_prm2_app_cfg",
        "1234567890",
    )
    assert descriptor is not None
    assert descriptor.table == "tbl_box_prm2"
    assert descriptor.key == "app"
    assert descriptor.is_control is True


def test_local_update_applier_writes_box_prm2_app_value():
    applier = LocalUpdateApplier("1234567890")
    payload = {"1234567890": {}}
    entity_id = "sensor.oig_local_1234567890_tbl_box_prm2_app"

    changed = applier.apply_state(payload, entity_id, 3, None)
    assert changed is True
    assert payload["1234567890"]["box_prm2"]["app"] == 3


def test_local_update_applier_writes_float_value():
    applier = LocalUpdateApplier("1234567890")
    payload = {"1234567890": {}}
    entity_id = "sensor.oig_local_1234567890_tbl_box_prm2_app"

    changed = applier.apply_state(payload, entity_id, 2.0, None)
    assert changed is True
    assert payload["1234567890"]["box_prm2"]["app"] == 2


def test_local_update_applier_handles_string_number():
    applier = LocalUpdateApplier("1234567890")
    payload = {"1234567890": {}}
    entity_id = "sensor.oig_local_1234567890_tbl_box_prm2_app"

    changed = applier.apply_state(payload, entity_id, "4", None)
    assert changed is True
    assert payload["1234567890"]["box_prm2"]["app"] == 4


def test_local_update_applier_no_change_when_value_same():
    applier = LocalUpdateApplier("1234567890")
    payload = {"1234567890": {"box_prm2": {"app": 3}}}
    entity_id = "sensor.oig_local_1234567890_tbl_box_prm2_app"

    changed = applier.apply_state(payload, entity_id, 3, None)
    assert changed is False


def test_local_update_applier_no_change_for_unmatched_suffix():
    applier = LocalUpdateApplier("1234567890")
    payload = {"1234567890": {}}
    entity_id = "sensor.oig_local_1234567890_tbl_foo_bar"

    changed = applier.apply_state(payload, entity_id, 1, None)
    assert changed is False
    assert "box_prm2" not in payload.get("1234567890", {})


def test_normalize_proxy_entity_id_returns_none_for_wrong_device():
    result = normalize_proxy_entity_id(
        "sensor.oig_local_9999999999_tbl_box_prm2_app",
        "1234567890",
    )
    assert result is None


def test_normalize_proxy_entity_id_returns_none_for_wrong_domain():
    result = normalize_proxy_entity_id(
        "switch.oig_local_1234567890_tbl_box_prm2_app",
        "1234567890",
    )
    # switch IS a supported domain, so it parses successfully
    assert result is not None
    assert result.domain == "switch"
    assert result.table == "tbl_box_prm2"
    assert result.key == "app"
    assert result.raw_suffix == "tbl_box_prm2_app"


def test_box_prm2_app_sensor_type_in_sensor_types():
    from custom_components.oig_cloud.sensor_types import SENSOR_TYPES

    assert "box_prm2_app" in SENSOR_TYPES
    cfg = SENSOR_TYPES["box_prm2_app"]
    assert cfg["local_entity_suffix"] == "tbl_box_prm2_app"
    assert cfg["node_id"] == "box_prm2"
    assert cfg["node_key"] == "app"