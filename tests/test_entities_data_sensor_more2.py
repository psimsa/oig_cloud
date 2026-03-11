from custom_components.oig_cloud.entities.data_sensor import OigCloudDataSensor


class DummyCoordinator:
    def __init__(self, data):
        self.data = data


def test_extended_value_out_of_range():
    sensor = OigCloudDataSensor(DummyCoordinator({"extended_batt": {"items": [{"values": [1.0]}]}}), "extended_battery_temperature", extended=True)
    assert sensor._get_extended_value_for_sensor() is None
