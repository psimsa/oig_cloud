from custom_components.oig_cloud.pricing import spot_price_sensor as spot_module


def test_spot_price_sensor_exports():
    assert spot_module.SpotPriceSensor is not None
    assert spot_module.SpotPrice15MinSensor is not None
    assert spot_module.ExportPrice15MinSensor is not None
    assert set(spot_module.__all__) == {
        "ExportPrice15MinSensor",
        "SpotPrice15MinSensor",
        "SpotPriceSensor",
    }
