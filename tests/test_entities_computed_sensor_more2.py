from datetime import datetime, timedelta, timezone

from custom_components.oig_cloud.entities.computed_sensor import OigCloudComputedSensor


class DummyCoordinator:
    def __init__(self):
        self.forced_box_id = "123"
        self.hass = None

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyState:
    def __init__(self, state, last_updated=None, last_changed=None):
        self.state = state
        self.last_updated = last_updated
        self.last_changed = last_changed or last_updated


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


class DummyHass:
    def __init__(self, mapping):
        self.states = DummyStates(mapping)

    def async_create_task(self, coro):
        coro.close()
        return object()


def test_get_oig_last_updated_missing():
    sensor = OigCloudComputedSensor(DummyCoordinator(), "batt_bat_c")
    sensor.hass = DummyHass({})
    assert sensor._get_oig_last_updated("batt_bat_c") is None


def test_accumulate_energy_missing_power():
    sensor = OigCloudComputedSensor(DummyCoordinator(), "computed_batt_charge_energy_today")
    sensor._box_id = "123"
    sensor.hass = DummyHass({})
    sensor._get_oig_number = lambda _s: None
    assert sensor._accumulate_energy() is None
