"""Service shield validation helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_BOX_MODE = "oig_cloud.set_box_mode"


def normalize_value(val: Any) -> str:
    """Normalize string values for shield comparisons."""
    normalized = (
        str(val or "")
        .strip()
        .lower()
        .replace(" ", "")
        .replace("/", "")
        .replace("_", "")
    )
    mapping = {
        "vypnutoon": "vypnuto",
        "vypnuto": "vypnuto",
        "off": "vypnuto",
        "zapnutoon": "zapnuto",
        "zapnuto": "zapnuto",
        "on": "zapnuto",
        "somezenimlimited": "omezeno",
        "limited": "omezeno",
        "omezeno": "omezeno",
        "manuální": "manualni",
        "manual": "manualni",
        "cbb": "cbb",
    }
    return mapping.get(normalized, normalized)


def values_match(current_value: Any, expected_value: Any) -> bool:
    """Compare values with normalization."""
    try:
        if str(expected_value).replace(".", "").replace("-", "").isdigit():
            return float(current_value or 0) == float(expected_value)
        return normalize_value(current_value) == normalize_value(expected_value)
    except (ValueError, TypeError):
        return str(current_value) == str(expected_value)


def get_entity_state(hass: Any, entity_id: str) -> Optional[str]:
    """Return state for entity id."""
    state = hass.states.get(entity_id)
    return state.state if state else None


def extract_api_info(service_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Extract API call information from service parameters."""
    api_info: Dict[str, Any] = {}

    if service_name == "oig_cloud.set_boiler_mode":
        mode = params.get("mode")
        mode_key = str(mode or "").strip().lower()
        api_info = {
            "api_endpoint": "Device.Set.Value.php",
            "api_table": "boiler_prms",
            "api_column": "manual",
            "api_value": 1 if mode_key in {"manual", "manuální"} else 0,
            "api_description": f"Set boiler mode to {mode}",
        }
    elif service_name == SERVICE_SET_BOX_MODE:
        mode = params.get("mode")
        api_info = {
            "api_endpoint": "Device.Set.Value.php",
            "api_table": "box_prms",
            "api_column": "mode",
            "api_value": mode,
            "api_description": f"Set box mode to {mode}",
        }
    elif service_name == "oig_cloud.set_grid_delivery":
        if "limit" in params:
            api_info = {
                "api_endpoint": "Device.Set.Value.php",
                "api_table": "invertor_prm1",
                "api_column": "p_max_feed_grid",
                "api_value": params["limit"],
                "api_description": f"Set grid delivery limit to {params['limit']}W",
            }
        elif "mode" in params:
            api_info = {
                "api_endpoint": "Device.Set.Value.php",
                "api_table": "invertor_prms",
                "api_column": "to_grid",
                "api_value": params["mode"],
                "api_description": f"Set grid delivery mode to {params['mode']}",
            }

    return api_info


def extract_expected_entities(
    shield: Any, service_name: str, data: Dict[str, Any]
) -> Dict[str, str]:
    """Extract expected entities and target values."""
    shield.last_checked_entity_id = None

    def find_entity(suffix: str) -> str | None:
        _LOGGER.info("[FIND ENTITY] Hledám cloud entitu se suffixem: %s", suffix)

        box_id = None
        for key in ("box_id", "inverter_sn"):
            val = shield.entry.options.get(key) or shield.entry.data.get(key)
            if isinstance(val, str) and val.isdigit():
                box_id = val
                break

        if not box_id:
            try:
                from ..entities.base_sensor import resolve_box_id

                coordinator = None
                for entry_data in shield.hass.data.get(DOMAIN, {}).values():
                    if not isinstance(entry_data, dict):
                        continue
                    if entry_data.get("service_shield") != shield:
                        continue
                    coordinator = entry_data.get("coordinator")
                    break
                if coordinator:
                    resolved = resolve_box_id(coordinator)
                    if isinstance(resolved, str) and resolved.isdigit():
                        box_id = resolved
            except Exception:
                box_id = None

        if not box_id:
            _LOGGER.warning(
                "[FIND ENTITY] box_id nelze určit, cloud entitu pro suffix '%s' nelze vybrat",
                suffix,
            )
            return None

        prefix = f"sensor.oig_{box_id}_"
        matching_entities = [
            entity.entity_id
            for entity in shield.hass.states.async_all()
            if entity.entity_id.startswith(prefix) and entity.entity_id.endswith(suffix)
        ]

        if matching_entities:
            entity_id = matching_entities[0]
            _LOGGER.info("[FIND ENTITY] Vybrána cloud entita: %s", entity_id)
            return entity_id

        _LOGGER.warning("[FIND ENTITY] NENALEZENA cloud entita %s*%s", prefix, suffix)
        return None

    if service_name == "oig_cloud.set_formating_mode":
        fake_entity_id = f"fake_formating_mode_{int(datetime.now().timestamp())}"
        _LOGGER.info(
            "[OIG Shield] Formating mode - vytváří fiktivní entitu pro 2min sledování: %s",
            fake_entity_id,
        )
        return {fake_entity_id: "completed_after_timeout"}

    if service_name == SERVICE_SET_BOX_MODE:
        mode_raw = str(data.get("mode") or "").strip()
        expected_value = mode_raw
        if not expected_value or expected_value.lower() == "none":
            return {}
        mode_key = normalize_value(mode_raw)
        mode_mapping = {
            "home1": "Home 1",
            "home2": "Home 2",
            "home3": "Home 3",
            "homeups": "Home UPS",
            "home5": "Home 5",
            "home6": "Home 6",
            "0": "Home 1",
            "1": "Home 2",
            "2": "Home 3",
            "3": "Home UPS",
            "4": "Home 5",
            "5": "Home 6",
        }
        expected_value = mode_mapping.get(mode_key, mode_raw)
        entity_id = find_entity("_box_prms_mode")
        if entity_id:
            shield.last_checked_entity_id = entity_id
            state = shield.hass.states.get(entity_id)
            current = normalize_value(state.state if state else None)
            expected = normalize_value(expected_value)
            _LOGGER.debug(
                "[extract] box_mode | current='%s' expected='%s'", current, expected
            )
            if current != expected:
                return {entity_id: expected_value}
        return {}

    if service_name == "oig_cloud.set_boiler_mode":
        mode = str(data.get("mode") or "").strip()
        boiler_mode_mapping = {
            "CBB": "CBB",
            "Manual": "Manuální",
            "cbb": "CBB",
            "manual": "Manuální",
        }
        expected_value = boiler_mode_mapping.get(mode)
        if not expected_value:
            _LOGGER.warning("[extract] Unknown boiler mode: %s", mode)
            return {}

        entity_id = find_entity("_boiler_manual_mode")
        if entity_id:
            shield.last_checked_entity_id = entity_id
            state = shield.hass.states.get(entity_id)
            current = normalize_value(state.state if state else None)
            expected = normalize_value(expected_value)
            _LOGGER.debug(
                "[extract] boiler_mode | current='%s' expected='%s' (input='%s')",
                current,
                expected,
                mode,
            )
            if current != expected:
                return {entity_id: expected_value}
        return {}

    if service_name == "oig_cloud.set_grid_delivery":
        if "limit" in data and "mode" not in data:
            try:
                expected_value = round(float(data["limit"]))
            except (ValueError, TypeError):
                expected_value = None

            if expected_value is not None:
                entity_id = find_entity("_invertor_prm1_p_max_feed_grid")
                if entity_id:
                    shield.last_checked_entity_id = entity_id
                    state = shield.hass.states.get(entity_id)

                    try:
                        current_value = round(float(state.state))
                    except (ValueError, TypeError, AttributeError):
                        current_value = None

                    _LOGGER.debug(
                        "[extract] grid_delivery.limit ONLY | current=%s expected=%s",
                        current_value,
                        expected_value,
                    )

                    if current_value != expected_value:
                        return {entity_id: str(expected_value)}

                    _LOGGER.info(
                        "[extract] Limit již je %sW - přeskakuji", expected_value
                    )
                    return {}

        if "mode" in data and "limit" not in data:
            mode_string = str(data["mode"]).strip()
            mode_mapping = {
                "Vypnuto / Off": "Vypnuto",
                "Zapnuto / On": "Zapnuto",
                "S omezením / Limited": "Omezeno",
                "vypnuto / off": "Vypnuto",
                "zapnuto / on": "Zapnuto",
                "s omezením / limited": "Omezeno",
                "off": "Vypnuto",
                "on": "Zapnuto",
                "limited": "Omezeno",
            }

            expected_text = mode_mapping.get(mode_string) or mode_mapping.get(
                mode_string.lower()
            )
            if not expected_text:
                _LOGGER.warning("[extract] Unknown grid delivery mode: %s", mode_string)
                return {}

            entity_id = find_entity("_invertor_prms_to_grid")
            if entity_id:
                shield.last_checked_entity_id = entity_id
                state = shield.hass.states.get(entity_id)
                current_text = state.state if state else None

                _LOGGER.debug(
                    "[extract] grid_delivery.mode ONLY | current='%s' expected='%s' (mode_string='%s')",
                    current_text,
                    expected_text,
                    mode_string,
                )

                if current_text != expected_text:
                    return {entity_id: expected_text}

                _LOGGER.info("[extract] Mode již je %s - přeskakuji", current_text)
                return {}

        if "mode" in data and "limit" in data:
            _LOGGER.error(
                "[extract] CHYBA: grid_delivery dostalo mode + limit současně! Wrapper měl rozdělit!"
            )
            return {}

        return {}

    if service_name == "oig_cloud.set_formating_mode":
        return {}

    return {}


def check_entity_state_change(shield: Any, entity_id: str, expected_value: Any) -> bool:
    """Check if entity changed to expected value."""
    current_state = shield.hass.states.get(entity_id)
    if not current_state:
        return False

    current_value = current_state.state

    if "boiler_manual_mode" in entity_id:
        return (expected_value == 0 and current_value == "CBB") or (
            expected_value == 1 and current_value == "Manuální"
        )
    if "ssr" in entity_id:
        off_values = {"Vypnuto/Off", "Vypnuto", "Off"}
        on_values = {"Zapnuto/On", "Zapnuto", "On"}
        return (expected_value == 0 and current_value in off_values) or (
            expected_value == 1 and current_value in on_values
        )
    if "box_prms_mode" in entity_id:
        mode_mapping = {
            0: "Home 1",
            1: "Home 2",
            2: "Home 3",
            3: "Home UPS",
            4: "Home 5",
            5: "Home 6",
        }
        if isinstance(expected_value, str):
            if normalize_value(current_value) == normalize_value(expected_value):
                return True
            if expected_value.isdigit():
                expected_value = int(expected_value)
        if isinstance(expected_value, int):
            return current_value == mode_mapping.get(expected_value)
    if "invertor_prms_to_grid" in entity_id:
        norm_expected = normalize_value(expected_value)
        norm_current = normalize_value(current_value)
        if isinstance(expected_value, int) or str(expected_value).isdigit():
            norm_expected = "zapnuto" if int(expected_value) == 1 else "vypnuto"
        if norm_expected == "vypnuto":
            return norm_current in {"vypnuto"}
        if norm_expected == "zapnuto":
            if entity_id.startswith("binary_sensor."):
                return norm_current in {"zapnuto", "omezeno"}
            return norm_current == "zapnuto"
        if norm_expected == "omezeno":
            if entity_id.startswith("binary_sensor."):
                return norm_current in {"zapnuto", "omezeno"}
            return norm_current == "omezeno"
        return False
    if "p_max_feed_grid" in entity_id:
        try:
            current_num = round(float(current_value))
            expected_num = round(float(expected_value))
            if current_num == expected_num:
                return True
        except (ValueError, TypeError):
            pass
    else:
        try:
            if float(current_value) == float(expected_value):
                return True
        except (ValueError, TypeError):
            if str(current_value) == str(expected_value):
                return True

    return False
