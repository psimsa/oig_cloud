from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.timeline import planner
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
)


class DummySimResult:
    def __init__(self, new_soc_kwh, gi, ge, sc, gc):
        self.new_soc_kwh = new_soc_kwh
        self.grid_import_kwh = gi
        self.grid_export_kwh = ge
        self.solar_charge_kwh = sc
        self.grid_charge_kwh = gc


def test_build_planner_timeline(monkeypatch):
    def _simulate(**_kwargs):
        return DummySimResult(new_soc_kwh=4.0, gi=1.0, ge=0.2, sc=0.1, gc=0.3)

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.timeline.planner.simulate_interval",
        lambda **kwargs: _simulate(**kwargs),
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.timeline.planner.get_solar_for_timestamp",
        lambda *_a, **_k: 0.5,
    )

    modes = [CBB_MODE_HOME_I, CBB_MODE_HOME_I]
    spot_prices = [{"time": "2025-01-01T00:00:00", "price": 1.0}, {"time": "bad", "price": 2.0}]
    export_prices = [{"price": 0.1}, {"price": 0.2}]

    timeline = planner.build_planner_timeline(
        modes=modes,
        spot_prices=spot_prices,
        export_prices=export_prices,
        solar_forecast={},
        load_forecast=[0.2, 0.3],
        current_capacity=3.0,
        max_capacity=5.0,
        hw_min_capacity=1.0,
        efficiency=0.9,
        home_charge_rate_kw=2.0,
    )

    assert len(timeline) == 2
    assert timeline[0]["grid_import"] == 1.0
    assert timeline[1]["solar_kwh"] == 0.0


def test_build_planner_timeline_breaks(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.timeline.planner.simulate_interval",
        lambda **_k: DummySimResult(new_soc_kwh=1.0, gi=0.0, ge=0.0, sc=0.0, gc=0.0),
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.timeline.planner.get_solar_for_timestamp",
        lambda *_a, **_k: 0.0,
    )

    modes = [CBB_MODE_HOME_I, CBB_MODE_HOME_I]
    spot_prices = [{"time": "bad", "price": 1.0}]
    timeline = planner.build_planner_timeline(
        modes=modes,
        spot_prices=spot_prices,
        export_prices=[],
        solar_forecast={},
        load_forecast=[0.1],
        current_capacity=1.0,
        max_capacity=5.0,
        hw_min_capacity=1.0,
        efficiency=1.0,
        home_charge_rate_kw=2.0,
    )
    assert len(timeline) == 1


def test_format_planner_reason():
    assert planner.format_planner_reason("planned_charge", spot_price=2.5)
    assert planner.format_planner_reason("price_band_hold", spot_price=2.5)
    assert planner.format_planner_reason("balancing_charge") == "Balancování: nabíjení na 100 %"
    assert planner.format_planner_reason("holding_period") == "Balancování: držení 100 %"
    assert planner.format_planner_reason("negative_price_charge")
    assert planner.format_planner_reason("negative_price_curtail")
    assert planner.format_planner_reason("negative_price_consume")
    assert planner.format_planner_reason("other") is None
    assert planner.format_planner_reason(None) is None
    assert planner.format_planner_reason("planned_charge") == "Plánované nabíjení ze sítě"
    assert planner.format_planner_reason("price_band_hold") == "UPS držíme v cenovém pásmu dle účinnosti"


def test_attach_planner_reasons():
    timeline = [{"spot_price": 1.0}, {"spot_price": 2.0}]

    class Decision:
        def __init__(self, reason, is_balancing=False, is_holding=False, is_negative_price=False):
            self.reason = reason
            self.is_balancing = is_balancing
            self.is_holding = is_holding
            self.is_negative_price = is_negative_price

    decisions = [
        Decision("planned_charge", is_balancing=True),
        Decision(None, is_holding=True, is_negative_price=True),
    ]

    planner.attach_planner_reasons(timeline, decisions)

    assert "decision_metrics" in timeline[0]
    assert timeline[0]["decision_metrics"]["planner_is_balancing"] is True
    assert "decision_reason" in timeline[0]
    assert timeline[1]["decision_metrics"]["planner_is_holding"] is True
    assert timeline[1]["decision_metrics"]["planner_is_negative_price"] is True

    planner.attach_planner_reasons(timeline, decisions + [Decision("x")])


def test_add_decision_reasons_to_timeline():
    timeline = [
        {
            "mode": CBB_MODE_HOME_II,
            "grid_charge_kwh": 0.0,
            "spot_price": 2.0,
            "load_kwh": 1.0,
            "solar_kwh": 0.0,
            "battery_soc": 2.5,
        },
        {
            "mode": CBB_MODE_HOME_III,
            "spot_price": 1.0,
            "load_kwh": 0.1,
            "solar_kwh": 0.0,
            "battery_soc": 2.0,
        },
        {
            "mode": CBB_MODE_HOME_I,
            "spot_price": 1.0,
            "load_kwh": 0.0,
            "solar_kwh": 0.5,
            "battery_soc": 1.0,
            "decision_reason": "override",
            "decision_metrics": {"custom": 1},
        },
        {
            "mode": CBB_MODE_HOME_UPS,
            "grid_charge_kwh": 1.0,
            "spot_price": 3.0,
            "load_kwh": 0.2,
            "solar_kwh": 0.1,
            "battery_soc": 3.0,
        },
    ]

    planner.add_decision_reasons_to_timeline(
        timeline,
        current_capacity=4.0,
        max_capacity=5.0,
        min_capacity=1.0,
        efficiency=0.9,
    )

    assert "decision_reason" in timeline[0]
    assert "decision_reason" in timeline[1]
    assert timeline[2]["decision_reason"] == "override"
    assert timeline[2]["decision_metrics"]["custom"] == 1


def test_add_decision_reasons_to_timeline_branches():
    class BadFloat:
        def __round__(self, _ndigits=None):
            return 0.0

        def __float__(self):
            raise TypeError("no float")

    timeline = [
        {
            "mode": CBB_MODE_HOME_II,
            "grid_charge_kwh": 0.0,
            "spot_price": 2.0,
            "load_kwh": 1.0,
            "solar_kwh": 0.0,
            "battery_soc": 2.0,
        },
        {
            "mode": CBB_MODE_HOME_II,
            "spot_price": 1.0,
            "load_kwh": 0.0,
            "solar_kwh": 1.0,
            "battery_soc": 2.0,
        },
        {
            "mode": CBB_MODE_HOME_UPS,
            "grid_charge_kwh": 0.0,
            "spot_price": 1.0,
            "load_kwh": 0.0,
            "solar_kwh": 0.0,
            "battery_soc": BadFloat(),
        },
        {
            "mode": 0,
            "spot_price": 1.0,
            "load_kwh": 1.0,
            "solar_kwh": 0.0,
            "battery_soc": 1.0,
        },
    ]

    planner.add_decision_reasons_to_timeline(
        timeline,
        current_capacity=2.0,
        max_capacity=5.0,
        min_capacity=1.0,
        efficiency=0.9,
    )

    assert "chybi UPS okno" in timeline[0]["decision_reason"]
    assert timeline[1]["decision_reason"] == "Prebytky ze solaru do baterie (bez vybijeni)"
    assert timeline[2]["decision_reason"] == "UPS rezim (ochrana/udrzovani)"
    assert timeline[3]["decision_reason"] == "Vybijeni baterie misto odberu ze site"


def test_add_decision_reasons_empty_timeline():
    planner.add_decision_reasons_to_timeline(
        [],
        current_capacity=1.0,
        max_capacity=2.0,
        min_capacity=1.0,
        efficiency=1.0,
    )
