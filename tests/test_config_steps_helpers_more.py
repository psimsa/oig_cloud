from custom_components.oig_cloud.config.steps import WizardMixin


def test_sanitize_data_source_mode():
    assert WizardMixin._sanitize_data_source_mode("hybrid") == "local_only"
    assert WizardMixin._sanitize_data_source_mode(None) == "cloud_only"


def test_migrate_old_pricing_data_fixed_prices_dual():
    data = {
        "spot_pricing_model": "fixed_prices",
        "dual_tariff_enabled": True,
        "fixed_commercial_price_vt": 4.0,
        "fixed_commercial_price_nt": 3.0,
        "export_pricing_model": "fixed",
        "export_fixed_fee_czk": 0.2,
        "vt_hours_start": "6:00",
        "vt_hours_end": "22:00",
    }
    migrated = WizardMixin._migrate_old_pricing_data(data)
    assert migrated["import_pricing_scenario"] == "fix_2tariff"
    assert migrated["export_pricing_scenario"] == "spot_fixed_2tariff"
    assert migrated["tariff_weekend_same_as_weekday"] is True


def test_map_pricing_to_backend_dual_weekend_custom():
    wizard = {
        "import_pricing_scenario": "spot_fixed",
        "spot_fixed_fee_kwh": 0.4,
        "export_pricing_scenario": "fix_price",
        "export_fixed_price_kwh": 2.2,
        "tariff_count": "dual",
        "distribution_fee_vt_kwh": 1.1,
        "distribution_fee_nt_kwh": 0.9,
        "tariff_vt_start_weekday": "6",
        "tariff_nt_start_weekday": "22,2",
        "tariff_weekend_same_as_weekday": False,
        "tariff_vt_start_weekend": "8",
        "tariff_nt_start_weekend": "0",
        "vat_rate": 10.0,
    }
    backend = WizardMixin._map_pricing_to_backend(wizard)
    assert backend["spot_pricing_model"] == "fixed"
    assert backend["spot_fixed_fee_mwh"] == 400.0
    assert backend["export_pricing_model"] == "fixed_prices"
    assert backend["tariff_vt_start_weekend"] == "8"


def test_map_backend_to_frontend_fixed_prices_dual():
    backend = {
        "spot_pricing_model": "fixed_prices",
        "fixed_commercial_price_vt": 4.0,
        "fixed_commercial_price_nt": 3.0,
        "export_pricing_model": "percentage",
        "export_fee_percent": 12.0,
        "dual_tariff_enabled": True,
        "distribution_fee_vt_kwh": 1.2,
        "distribution_fee_nt_kwh": 0.8,
        "tariff_vt_start_weekday": "6",
        "tariff_nt_start_weekday": "22,2",
        "tariff_vt_start_weekend": "8",
        "tariff_nt_start_weekend": "0",
        "tariff_weekend_same_as_weekday": False,
        "vat_rate": 21.0,
    }
    frontend = WizardMixin._map_backend_to_frontend(backend)
    assert frontend["import_pricing_scenario"] == "fix_price"
    assert frontend["export_pricing_scenario"] == "spot_percentage"
    assert frontend["tariff_count"] == "dual"
