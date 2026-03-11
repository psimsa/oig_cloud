from datetime import datetime
from types import SimpleNamespace

from custom_components.oig_cloud.entities.statistics_sensor import OigCloudStatisticsSensor


class DummyCoordinator:
    def __init__(self):
        self.data = {"123": {}}
        self.config_entry = SimpleNamespace(options=SimpleNamespace(enable_statistics=True))

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


def test_get_actual_load_value_invalid():
    coordinator = DummyCoordinator()
    sensor = OigCloudStatisticsSensor(coordinator, "battery_load_median", {"identifiers": {("oig_cloud", "123")}})
    sensor.hass = SimpleNamespace(states=DummyStates({"sensor.oig_123_actual_aco_p": SimpleNamespace(state="bad", attributes={})}))
    assert sensor._get_actual_load_value() is None
