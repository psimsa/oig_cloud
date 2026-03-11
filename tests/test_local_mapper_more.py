from __future__ import annotations

from datetime import datetime

from custom_components.oig_cloud.core import local_mapper


def test_apply_state_unknown_entity():
    applier = local_mapper.LocalUpdateApplier("123")
    payload = {}
    assert applier.apply_state(payload, "sensor.other", 1, datetime.now()) is False


def test_apply_state_node_update_box_mode():
    applier = local_mapper.LocalUpdateApplier("123")
    payload = {}
    entity_id = "sensor.oig_local_123_tbl_box_prms_mode"
    changed = applier.apply_state(payload, entity_id, "Home 2", datetime.now())
    assert changed is True
    assert payload["123"]["box_prms"]["mode"] == 1


def test_apply_state_extended_update():
    applier = local_mapper.LocalUpdateApplier("123")
    payload = {}
    entity_id = "sensor.oig_local_123_tbl_batt_bat_v"
    changed = applier.apply_state(payload, entity_id, 12.5, datetime.now())
    assert changed is True
    ext = payload["extended_batt"]["items"][-1]["values"]
    assert ext[0] == 12.5


def test_apply_state_unknown_suffix():
    applier = local_mapper.LocalUpdateApplier("123")
    payload = {}
    entity_id = "sensor.oig_local_123_unknown_suffix"
    assert applier.apply_state(payload, entity_id, 1, datetime.now()) is False
