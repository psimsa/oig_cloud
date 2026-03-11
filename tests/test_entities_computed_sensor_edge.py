from custom_components.oig_cloud.entities.computed_sensor import OigCloudComputedSensor


class DummyCoordinator:
    def __init__(self):
        self.forced_box_id = "123"
        self.hass = None

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


def test_get_oig_number_invalid_box():
    sensor = OigCloudComputedSensor(DummyCoordinator(), "batt_bat_c")
    sensor._box_id = "unknown"
    assert sensor._get_oig_number("batt_bat_c") is None
