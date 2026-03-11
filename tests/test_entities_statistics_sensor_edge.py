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


def test_available_hourly_missing_entity():
    coordinator = DummyCoordinator()
    sensor = OigCloudStatisticsSensor(coordinator, "hourly_test", {"identifiers": {("oig_cloud", "123")}})
    sensor._source_entity_id = "sensor.oig_123_source"
    sensor.hass = SimpleNamespace(states=DummyStates({}))
    assert sensor.available is False
