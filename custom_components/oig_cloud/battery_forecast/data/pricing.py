"""Spot/export price helpers for battery forecast."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from ...api.ote_api import OteApi
from ...const import OTE_SPOT_PRICE_CACHE_FILE
from ..utils_common import get_tariff_for_datetime

_LOGGER = logging.getLogger(__name__)


def _round_czk(value: Decimal | float) -> float:
    """Round CZK values to 2 decimals (half-up)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _get_pricing_config(sensor: Any) -> Dict[str, Any]:
    return (
        sensor._config_entry.options
        if sensor._config_entry.options
        else sensor._config_entry.data
    )


def _calculate_commercial_price(
    raw_spot_price: float, target_datetime: datetime, config: Dict[str, Any]
) -> float:
    pricing_model = config.get("spot_pricing_model", "percentage")
    positive_fee_percent = config.get("spot_positive_fee_percent", 15.0)
    negative_fee_percent = config.get("spot_negative_fee_percent", 9.0)
    fixed_fee_mwh = config.get("spot_fixed_fee_mwh", 0.0)

    if pricing_model == "percentage":
        if raw_spot_price >= 0:
            return raw_spot_price * (1 + positive_fee_percent / 100.0)
        return raw_spot_price * (1 - negative_fee_percent / 100.0)
    if pricing_model == "fixed_prices":
        fixed_price_vt = config.get("fixed_commercial_price_vt", 4.50)
        fixed_price_nt = config.get("fixed_commercial_price_nt", fixed_price_vt)
        current_tariff = get_tariff_for_datetime(target_datetime, config)
        return fixed_price_vt if current_tariff == "VT" else fixed_price_nt

    fixed_fee_kwh = fixed_fee_mwh / 1000.0
    return raw_spot_price + fixed_fee_kwh


def _get_distribution_fee(target_datetime: datetime, config: Dict[str, Any]) -> float:
    distribution_fee_vt_kwh = config.get("distribution_fee_vt_kwh", 1.50)
    distribution_fee_nt_kwh = config.get("distribution_fee_nt_kwh", 1.20)
    current_tariff = get_tariff_for_datetime(target_datetime, config)
    return (
        distribution_fee_vt_kwh if current_tariff == "VT" else distribution_fee_nt_kwh
    )


async def _resolve_spot_data(
    sensor: Any, *, price_type: str, fallback_to_spot: bool = False
) -> Dict[str, Any]:
    spot_data: Dict[str, Any] = {}
    if not sensor.coordinator:
        _LOGGER.warning("Coordinator not available in get_spot_price_timeline")
    else:
        spot_data = sensor.coordinator.data.get("spot_prices", {})

    if not spot_data:
        spot_data = get_spot_data_from_price_sensor(sensor, price_type=price_type) or {}

    if not spot_data and fallback_to_spot:
        spot_data = get_spot_data_from_price_sensor(sensor, price_type="spot") or {}

    if not spot_data and sensor._hass:
        spot_data = await get_spot_data_from_ote_cache(sensor) or {}

    return spot_data or {}


def _get_prices_dict(
    spot_data: Dict[str, Any],
    *,
    key: str,
    sensor: Any,
    fallback_type: str,
) -> Dict[str, Any]:
    prices = spot_data.get(key, {})
    if prices:
        return prices

    fallback = get_spot_data_from_price_sensor(sensor, price_type=fallback_type) or {}
    prices = fallback.get(key, {}) if isinstance(fallback, dict) else {}
    return prices or {}


async def _resolve_prices_dict(
    sensor: Any,
    spot_data: Dict[str, Any],
    *,
    key: str,
    fallback_type: str,
) -> Dict[str, Any]:
    prices = _get_prices_dict(
        spot_data, key=key, sensor=sensor, fallback_type=fallback_type
    )
    if prices:
        return prices
    if sensor._hass:
        cache_data = await get_spot_data_from_ote_cache(sensor) or {}
        if isinstance(cache_data, dict):
            prices = cache_data.get(key, {})
    return prices or {}


def _get_export_config(sensor: Any) -> Dict[str, Any]:
    config_entry = sensor.coordinator.config_entry if sensor.coordinator else None
    return config_entry.options if config_entry else {}


def _get_sensor_component(hass: Any) -> Optional[Any]:
    if not hass or not isinstance(hass.data, dict):
        return None
    entity_components = hass.data.get("entity_components")
    if isinstance(entity_components, dict) and entity_components.get("sensor"):
        return entity_components.get("sensor")
    return hass.data.get("sensor")


def _find_entity(component: Any, sensor_id: str) -> Optional[Any]:
    if component is None:
        return None
    get_entity = getattr(component, "get_entity", None)
    if callable(get_entity):
        entity_obj = get_entity(sensor_id)
        if entity_obj is not None:
            return entity_obj
    entities = getattr(component, "entities", None)
    if isinstance(entities, list):
        for ent in entities:
            if getattr(ent, "entity_id", None) == sensor_id:
                return ent
    return None


def _derive_export_prices(
    spot_prices_dict: Dict[str, Any], config: Dict[str, Any]
) -> Dict[str, Any]:
    export_model = config.get("export_pricing_model", "percentage")
    export_fee = config.get("export_fee_percent", 15.0)
    export_fixed_price = config.get("export_fixed_price", 2.50)

    export_prices: Dict[str, Any] = {}
    for timestamp_str, spot_price in spot_prices_dict.items():
        if export_model == "percentage":
            export_price = spot_price * (1 - export_fee / 100)
        elif export_model == "fixed_prices":
            export_price = export_fixed_price
        else:
            export_price = max(0, spot_price - export_fee)
        export_prices[timestamp_str] = export_price
    return export_prices


def calculate_final_spot_price(
    sensor: Any, raw_spot_price: float, target_datetime: datetime
) -> float:
    """Return final spot price including fees, distribution, and VAT."""
    config = _get_pricing_config(sensor)
    vat_rate = config.get("vat_rate", 21.0)
    commercial_price = _calculate_commercial_price(
        raw_spot_price, target_datetime, config
    )
    distribution_fee = _get_distribution_fee(target_datetime, config)

    price_without_vat = Decimal(str(commercial_price)) + Decimal(str(distribution_fee))
    vat_multiplier = Decimal("1") + (Decimal(str(vat_rate)) / Decimal("100"))
    final_price = price_without_vat * vat_multiplier
    return _round_czk(final_price)


async def get_spot_price_timeline(sensor: Any) -> List[Dict[str, Any]]:
    """Return 15-minute spot prices with fees applied."""
    spot_data = await _resolve_spot_data(sensor, price_type="spot")
    if not spot_data:
        _LOGGER.warning("No spot price data available for forecast")
        return []

    raw_prices_dict = await _resolve_prices_dict(
        sensor, spot_data, key="prices15m_czk_kwh", fallback_type="spot"
    )
    if not raw_prices_dict:
        _LOGGER.warning("No prices15m_czk_kwh in spot price data")
        return []

    timeline = []
    for timestamp_str, raw_spot_price in sorted(raw_prices_dict.items()):
        try:
            target_datetime = datetime.fromisoformat(timestamp_str)
            final_price = calculate_final_spot_price(
                sensor, raw_spot_price, target_datetime
            )
            timeline.append({"time": timestamp_str, "price": final_price})
        except ValueError:
            _LOGGER.warning("Invalid timestamp in spot prices: %s", timestamp_str)
            continue

    _LOGGER.info(
        "Loaded %s spot price points from coordinator (final price with fees)",
        len(timeline),
    )
    return timeline


async def get_export_price_timeline(sensor: Any) -> List[Dict[str, Any]]:
    """Return 15-minute export prices."""
    spot_data = await _resolve_spot_data(
        sensor, price_type="export", fallback_to_spot=True
    )
    if not spot_data:
        _LOGGER.warning("No spot price data available for export timeline")
        return []

    export_prices_dict = await _resolve_prices_dict(
        sensor, spot_data, key="export_prices15m_czk_kwh", fallback_type="export"
    )
    if not export_prices_dict:
        _LOGGER.info("No direct export prices, calculating from spot prices")
        spot_prices_dict = await _resolve_prices_dict(
            sensor, spot_data, key="prices15m_czk_kwh", fallback_type="spot"
        )
        if not spot_prices_dict:
            _LOGGER.warning("No prices15m_czk_kwh for export price calculation")
            return []

        export_prices_dict = _derive_export_prices(
            spot_prices_dict, _get_export_config(sensor)
        )

    timeline = []
    for timestamp_str, price in sorted(export_prices_dict.items()):
        try:
            datetime.fromisoformat(timestamp_str)
            timeline.append({"time": timestamp_str, "price": price})
        except ValueError:
            _LOGGER.warning("Invalid timestamp in export prices: %s", timestamp_str)
            continue

    _LOGGER.info("Loaded %s export price points from coordinator", len(timeline))
    return timeline


def get_spot_data_from_price_sensor(
    sensor: Any, *, price_type: str
) -> Optional[Dict[str, Any]]:
    """Read spot price data from the price sensor entity."""
    hass = sensor._hass
    if not hass:
        return None

    if price_type == "export":
        sensor_id = f"sensor.oig_{sensor._box_id}_export_price_current_15min"
    else:
        sensor_id = f"sensor.oig_{sensor._box_id}_spot_price_current_15min"

    try:
        component = _get_sensor_component(hass)
        entity_obj = _find_entity(component, sensor_id)

        if entity_obj is None:
            return None

        spot_data = getattr(entity_obj, "_spot_data_15min", None)
        if isinstance(spot_data, dict) and spot_data:
            return spot_data
    except Exception as err:
        _LOGGER.debug("Failed to read spot data from %s: %s", sensor_id, err)

    return None


async def get_spot_data_from_ote_cache(sensor: Any) -> Optional[Dict[str, Any]]:
    """Load spot prices via OTE cache storage."""
    hass = sensor._hass
    if not hass:
        return None
    try:
        cache_path = hass.config.path(".storage", OTE_SPOT_PRICE_CACHE_FILE)
        ote = OteApi(cache_path=cache_path)
        try:
            await ote.async_load_cached_spot_prices()
            data = await ote.get_spot_prices()
            return data if isinstance(data, dict) and data else None
        finally:
            await ote.close()
    except Exception as err:
        _LOGGER.debug("Failed to load OTE spot prices from cache: %s", err)
        return None
