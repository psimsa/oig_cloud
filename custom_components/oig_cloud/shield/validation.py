"""Service shield validation helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import voluptuous as vol

from ..const import DOMAIN
from ..core.box_mode_composite import build_app_value

_LOGGER = logging.getLogger(__name__)
HOME_1_LABEL = "Home 1"
HOME_2_LABEL = "Home 2"
HOME_3_LABEL = "Home 3"
HOME_UPS_LABEL = "Home UPS"
MANUAL_LABEL = "Manuální"
API_ENDPOINT_SET_VALUE = "Device.Set.Value.php"

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
            "api_endpoint": API_ENDPOINT_SET_VALUE,
            "api_table": "boiler_prms",
            "api_column": "manual",
            "api_value": 1 if mode_key in {"manual", "manuální"} else 0,
            "api_description": f"Set boiler mode to {mode}",
        }
    elif service_name == SERVICE_SET_BOX_MODE:
        mode = params.get("mode")
        api_info = {
            "api_endpoint": API_ENDPOINT_SET_VALUE,
            "api_table": "box_prms",
            "api_column": "mode",
            "api_value": mode,
            "api_description": f"Set box mode to {mode}",
        }
    elif service_name == "oig_cloud.set_grid_delivery":
        if "limit" in params:
            api_info = {
                "api_endpoint": API_ENDPOINT_SET_VALUE,
                "api_table": "invertor_prm1",
                "api_column": "p_max_feed_grid",
                "api_value": params["limit"],
                "api_description": f"Set grid delivery limit to {params['limit']}W",
            }
        elif "mode" in params:
            api_info = {
                "api_endpoint": API_ENDPOINT_SET_VALUE,
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
    shield._expected_entity_missing = False

    def find_entity(suffix: str) -> str | None:
        _LOGGER.info("[FIND ENTITY] Hledám cloud entitu se suffixem: %s", suffix)
        box_id = _resolve_box_id_for_shield(shield)
        if not box_id:
            _LOGGER.warning(
                "[FIND ENTITY] box_id nelze určit, cloud entitu pro suffix '%s' nelze vybrat",
                suffix,
            )
            shield._expected_entity_missing = True
            return None

        entity_id = _find_entity_by_suffix(shield, box_id, suffix)
        if entity_id:
            _LOGGER.info("[FIND ENTITY] Vybrána cloud entita: %s", entity_id)
            return entity_id

        _LOGGER.warning(
            "[FIND ENTITY] NENALEZENA cloud entita sensor.oig_%s_*%s",
            box_id,
            suffix,
        )
        shield._expected_entity_missing = True
        return None

    if service_name == "oig_cloud.set_formating_mode":
        return _expected_formating_mode()
    if service_name == SERVICE_SET_BOX_MODE:
        return _expected_box_mode(shield, data, find_entity)
    if service_name == "oig_cloud.set_boiler_mode":
        return _expected_boiler_mode(shield, data, find_entity)
    if service_name == "oig_cloud.set_grid_delivery":
        return _expected_grid_delivery(shield, data, find_entity)

    return {}


def _expected_formating_mode() -> Dict[str, str]:
    fake_entity_id = f"fake_formating_mode_{int(datetime.now().timestamp())}"
    _LOGGER.info(
        "[OIG Shield] Formating mode - vytváří fiktivní entitu pro 2min sledování: %s",
        fake_entity_id,
    )
    return {fake_entity_id: "completed_after_timeout"}


def _expected_box_mode(
    shield: Any, data: Dict[str, Any], find_entity: Callable[[str], Optional[str]]
) -> Dict[str, Any]:
    box_mode_step = data.get("_box_mode_step")
    mode_raw = str(data.get("mode") or "").strip()
    has_mode = bool(mode_raw and mode_raw.lower() != "none")
    has_toggles = any(k in data for k in ("home_grid_v", "home_grid_vi"))

    # App step requires toggles to be specified
    if box_mode_step == "app" and not has_toggles:
        raise vol.Invalid("App step requires home_grid_v or home_grid_vi toggle to be specified")

    if has_mode and box_mode_step != "app":
        mode_key = normalize_value(mode_raw)
        mode_mapping = {
            "home1": HOME_1_LABEL,
            "home2": HOME_2_LABEL,
            "home3": HOME_3_LABEL,
            "homeups": HOME_UPS_LABEL,
            "0": HOME_1_LABEL,
            "1": HOME_2_LABEL,
            "2": HOME_3_LABEL,
            "3": HOME_UPS_LABEL,
        }
        expected_value = mode_mapping.get(mode_key, mode_raw)
        entity_id = find_entity("_box_prms_mode")
        if entity_id:
            shield.last_checked_entity_id = entity_id
            state = shield.hass.states.get(entity_id)
            current = normalize_value(state.state if state else None)
            expected = normalize_value(expected_value)
            _LOGGER.debug("[extract] box_mode step='%s' | current='%s' expected='%s'", box_mode_step or "standalone", current, expected)
            if current != expected:
                return {entity_id: expected_value}
        return {}

    if (has_mode and box_mode_step == "app") or (not has_mode and has_toggles):
        entity_id = find_entity("_box_prm2_app")
        if not entity_id:
            raise vol.Invalid("box_prm2_app sensor not found — cannot verify supplementary toggle state")
        shield.last_checked_entity_id = entity_id
        state = shield.hass.states.get(entity_id)
        if not state or state.state in (None, "unknown", "unavailable", ""):
            raise vol.Invalid(
                f"box_prm2_app sensor is {state.state if state else 'unavailable'} — "
                "cannot perform supplementary toggle operation without current state"
            )
        try:
            current_raw = int(float(state.state))
        except (ValueError, TypeError) as e:
            raise vol.Invalid(f"box_prm2_app sensor has invalid state '{state.state}': {e}")
        home_grid_v = data.get("home_grid_v")
        home_grid_vi = data.get("home_grid_vi")

        # If no toggles specified (both None), preserve current state
        if home_grid_v is None and home_grid_vi is None:
            if current_raw == 4:
                # Flexibilita mode - cannot modify, skip
                return {}
            # No change requested, skip
            return {}

        try:
            expected_app_value = build_app_value(home_grid_v, home_grid_vi, current_raw)
        except ValueError as e:
            raise vol.Invalid(f"Cannot compute supplementary app value: {e}")
        if expected_app_value == 4:
            raise vol.Invalid("Flexibilita mode (app=4) is active — cannot modify supplementary toggles")
        if current_raw == expected_app_value:
            _LOGGER.info("[extract] box_mode app již je %s - přeskakuji", expected_app_value)
            return {}
        _LOGGER.debug("[extract] box_mode app step='%s' | current=%s expected=%s", box_mode_step or "standalone", current_raw, expected_app_value)
        return {entity_id: expected_app_value}

    return {}


def _expected_boiler_mode(
    shield: Any, data: Dict[str, Any], find_entity: Callable[[str], Optional[str]]
) -> Dict[str, str]:
    mode = str(data.get("mode") or "").strip()
    boiler_mode_mapping = {
        "CBB": "CBB",
        "Manual": MANUAL_LABEL,
        "cbb": "CBB",
        "manual": MANUAL_LABEL,
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


def _expected_grid_delivery(
    shield: Any, data: Dict[str, Any], find_entity: Callable[[str], Optional[str]]
) -> Dict[str, str]:
    if "limit" in data and "mode" not in data:
        return _expected_grid_delivery_limit(shield, data, find_entity)
    if "mode" in data and "limit" not in data:
        return _expected_grid_delivery_mode(shield, data, find_entity)
    if "mode" in data and "limit" in data:
        _LOGGER.error(
            "[extract] CHYBA: grid_delivery dostalo mode + limit současně! Wrapper měl rozdělit!"
        )
    return {}


def _expected_grid_delivery_limit(
    shield: Any, data: Dict[str, Any], find_entity: Callable[[str], Optional[str]]
) -> Dict[str, str]:
    """Extract expected entities for grid delivery limit setting.

    When part of a split flow (mode+limit), this is step 2 - the numeric limit.
    The mode should already be set to 'limited' before this step runs.
    """
    try:
        expected_value = round(float(data["limit"]))
    except (ValueError, TypeError):
        expected_value = None

    if expected_value is None:
        return {}

    entity_id = find_entity("_invertor_prm1_p_max_feed_grid")
    if not entity_id:
        return {}

    shield.last_checked_entity_id = entity_id
    grid_step = data.get("_grid_delivery_step")

    if _is_entity_unavailable(shield, entity_id):
        _LOGGER.debug(
            "[extract] grid_delivery.limit step='%s' | entity=%s unavailable",
            grid_step or "standalone",
            entity_id,
        )
        return {entity_id: str(expected_value)}

    state = shield.hass.states.get(entity_id)
    try:
        current_value = round(float(state.state))
    except (ValueError, TypeError, AttributeError):
        current_value = None

    _LOGGER.debug(
        "[extract] grid_delivery.limit step='%s' | current=%s expected=%s",
        grid_step or "standalone",
        current_value,
        expected_value,
    )

    if current_value != expected_value:
        return {entity_id: str(expected_value)}

    _LOGGER.info("[extract] Limit již je %sW - přeskakuji", expected_value)
    return {}


def _expected_grid_delivery_mode(
    shield: Any, data: Dict[str, Any], find_entity: Callable[[str], Optional[str]]
) -> Dict[str, str]:
    """Extract expected entities for grid delivery mode setting.

    When part of a split flow (mode+limit), this should only handle mode='limited'
    as the first step. The limit step is handled separately.
    """
    mode_string = str(data.get("mode")).strip()
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
    if not entity_id:
        return {}

    shield.last_checked_entity_id = entity_id
    grid_step = data.get("_grid_delivery_step")

    if _is_entity_unavailable(shield, entity_id):
        _LOGGER.debug(
            "[extract] grid_delivery.mode step='%s' | entity=%s unavailable",
            grid_step or "standalone",
            entity_id,
        )
        return {entity_id: expected_text}

    state = shield.hass.states.get(entity_id)
    current_text = state.state if state else None

    _LOGGER.debug(
        "[extract] grid_delivery.mode step='%s' | current='%s' expected='%s' (mode_string='%s')",
        grid_step or "standalone",
        current_text,
        expected_text,
        mode_string,
    )

    if current_text != expected_text:
        return {entity_id: expected_text}

    _LOGGER.info("[extract] Mode již je %s - přeskakuji", current_text)
    return {}


def _resolve_box_id_for_shield(shield: Any) -> Optional[str]:
    box_id = _resolve_box_id_from_entry(shield.entry)
    if box_id:
        return box_id
    return _resolve_box_id_from_coordinator(shield)


def _resolve_box_id_from_entry(entry: Any) -> Optional[str]:
    for key in ("box_id", "inverter_sn"):
        val = entry.options.get(key) or entry.data.get(key)
        if isinstance(val, str) and val.isdigit():
            return val
    return None


def _resolve_box_id_from_coordinator(shield: Any) -> Optional[str]:
    try:
        from ..entities.base_sensor import resolve_box_id

        coordinator = _find_shield_coordinator(shield)
        if coordinator:
            resolved = resolve_box_id(coordinator)
            if isinstance(resolved, str) and resolved.isdigit():
                return resolved
    except Exception:
        return None
    return None


def _find_shield_coordinator(shield: Any) -> Optional[Any]:
    for entry_data in shield.hass.data.get(DOMAIN, {}).values():
        if not isinstance(entry_data, dict):
            continue
        if entry_data.get("service_shield") != shield:
            continue
        return entry_data.get("coordinator")
    return None


def _find_entity_by_suffix(shield: Any, box_id: str, suffix: str) -> Optional[str]:
    """Find entity by suffix with deterministic suffix-safe resolution.

    Mirrors frontend findSensorId() logic from entity-store.ts:
    - Exact match (no numeric suffix) is preferred
    - Then _2, _3, etc. in numeric order (lowest first)
    - Returns None if no matching entity found
    """
    prefix = f"sensor.oig_{box_id}_"
    sensor_name = suffix.lstrip("_")
    base_entity = f"{prefix}{sensor_name}"

    candidates = []
    for entity in shield.hass.states.async_all():
        entity_id = entity.entity_id
        if entity_id == base_entity:
            candidates.append((entity_id, 0))
        elif entity_id.startswith(base_entity + "_"):
            numeric_suffix = entity_id[len(base_entity) + 1 :]
            if numeric_suffix.isdigit():
                candidates.append((entity_id, int(numeric_suffix)))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[1], item[0]))
    return candidates[0][0]


def _is_entity_unavailable(shield: Any, entity_id: str) -> bool:
    """Check if entity state is unavailable or unknown.

    Returns True if entity is missing, unavailable, or in unknown state.
    This distinguishes "entity not readable" from "value mismatch".
    """
    state = shield.hass.states.get(entity_id)
    if state is None:
        return True
    if state.state in ("unavailable", "unknown", None):
        return True
    return False


def check_entity_state_change(shield: Any, entity_id: str, expected_value: Any) -> bool:
    """Check if entity changed to expected value."""
    current_state = shield.hass.states.get(entity_id)
    if not current_state:
        return False

    current_value = current_state.state

    matcher = _select_entity_matcher(entity_id)
    return matcher(entity_id, expected_value, current_value)


def _select_entity_matcher(
    entity_id: str,
) -> Callable[[str, Any, Any], bool]:
    patterns: list[tuple[str, Callable[[str, Any, Any], bool]]] = [
        ("boiler_manual_mode", _wrap_matcher(_matches_boiler_mode)),
        ("ssr", _wrap_matcher(_matches_ssr_mode)),
        ("box_prms_mode", _wrap_matcher(_matches_box_mode)),
        ("box_prm2_app", _wrap_matcher(_matches_box_prm2_app)),
        ("invertor_prms_to_grid", _matches_inverter_mode),
        ("p_max_feed_grid", _wrap_matcher(_matches_numeric)),
    ]
    for marker, matcher in patterns:
        if marker in entity_id:
            return matcher
    return _wrap_matcher(_matches_generic)


def _wrap_matcher(
    matcher: Callable[[Any, Any], bool],
) -> Callable[[str, Any, Any], bool]:
    def wrapped(_entity_id: str, expected_value: Any, current_value: Any) -> bool:
        return matcher(expected_value, current_value)

    return wrapped


def _matches_boiler_mode(expected_value: Any, current_value: Any) -> bool:
    return (expected_value == 0 and current_value == "CBB") or (
        expected_value == 1 and current_value == MANUAL_LABEL
    )


def _matches_ssr_mode(expected_value: Any, current_value: Any) -> bool:
    off_values = {"Vypnuto/Off", "Vypnuto", "Off"}
    on_values = {"Zapnuto/On", "Zapnuto", "On"}
    return (expected_value == 0 and current_value in off_values) or (
        expected_value == 1 and current_value in on_values
    )


def _matches_box_mode(expected_value: Any, current_value: Any) -> bool:
    mode_mapping = {
        0: HOME_1_LABEL,
        1: HOME_2_LABEL,
        2: HOME_3_LABEL,
        3: HOME_UPS_LABEL,
    }
    if isinstance(expected_value, str):
        if normalize_value(current_value) == normalize_value(expected_value):
            return True
        if expected_value.isdigit():
            expected_value = int(expected_value)
    if isinstance(expected_value, int):
        return current_value == mode_mapping.get(expected_value)
    return False


def _matches_box_prm2_app(expected_value: Any, current_value: Any) -> bool:
    try:
        expected_num = round(float(expected_value))
        current_num = round(float(current_value))
    except (ValueError, TypeError):
        return False
    if expected_num == 4 or current_num == 4:
        return False
    return expected_num == current_num


def _matches_inverter_mode(
    entity_id: str, expected_value: Any, current_value: Any
) -> bool:
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


def _matches_numeric(expected_value: Any, current_value: Any) -> bool:
    try:
        return round(float(current_value)) == round(float(expected_value))
    except (ValueError, TypeError):
        return False


def _matches_generic(expected_value: Any, current_value: Any) -> bool:
    try:
        return float(current_value) == float(expected_value)
    except (ValueError, TypeError):
        return str(current_value) == str(expected_value)
