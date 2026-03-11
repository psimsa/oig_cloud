"""Platform pro OIG Cloud senzory."""

import logging
from typing import Any, Dict, List

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entities.base_sensor import resolve_box_id
from .entities.data_source_sensor import OigCloudDataSourceSensor

_LOGGER = logging.getLogger(__name__)

try:
    _LOGGER.debug("Attempting to import SENSOR_TYPES from sensor_types.py")
    from .sensor_types import SENSOR_TYPES

    _LOGGER.debug(
        f"Successfully imported SENSOR_TYPES with {len(SENSOR_TYPES)} sensor types"
    )

    # Debug informace o obsahu
    for sensor_type, config in SENSOR_TYPES.items():
        _LOGGER.debug(
            f"Sensor type: {sensor_type}, category: {config.get('sensor_type_category', 'unknown')}"
        )

except ImportError as e:
    _LOGGER.error(f"Failed to import sensor_types.py: {e}")
    _LOGGER.error("This is a critical error - sensor_types.py must exist and be valid")
    raise
except AttributeError as e:
    _LOGGER.error(f"SENSOR_TYPES not found in sensor_types.py: {e}")
    raise
except Exception as e:
    _LOGGER.error(f"Unexpected error importing sensor_types.py: {e}")
    raise


# ============================================================================
# HELPER FUNCTIONS - Sensor Registry
# ============================================================================


def _get_expected_sensor_types(hass: HomeAssistant, entry: ConfigEntry) -> set[str]:
    """
    Vrátí set všech sensor_types které by měly být registrované
    podle aktuální konfigurace entry.

    Používá se pro cleanup - senzory které nejsou v tomto setu jsou osiřelé.
    """
    expected = set()

    # Získáme statistics_enabled z hass.data
    statistics_enabled = hass.data[DOMAIN][entry.entry_id].get(
        "statistics_enabled", False
    )

    always_enabled_categories = {"data", "computed", "shield", "notification"}
    category_to_option_key: dict[str, str] = {
        "extended": "enable_extended_sensors",
        "solar_forecast": "enable_solar_forecast",
        "pricing": "enable_pricing",
        "chmu_warnings": "enable_chmu_warnings",
    }

    for sensor_type, config in SENSOR_TYPES.items():
        category = config.get("sensor_type_category")

        # Základní kategorie (vždy aktivní)
        if category in always_enabled_categories:
            expected.add(sensor_type)
            continue

        # Statistics sensors (volitelné)
        if category == "statistics" and statistics_enabled:
            expected.add(sensor_type)
            continue

        # Battery-related sensors (volitelné, společně s battery_prediction)
        if category in {
            "battery_prediction",
            "grid_charging_plan",
            "battery_efficiency",
            "planner_status",
        } and entry.options.get("enable_battery_prediction", False):
            expected.add(sensor_type)
            continue

        option_key = category_to_option_key.get(str(category))
        if option_key and entry.options.get(option_key, False):
            expected.add(sensor_type)
            continue

    _LOGGER.debug(f"Expected {len(expected)} sensor types based on configuration")
    return expected


async def _cleanup_renamed_sensors(
    entity_reg, entry: ConfigEntry, expected_sensor_types: set[str]
) -> int:
    """
    Smaže senzory které už nejsou v konfiguraci (přejmenované/odstraněné).

    Args:
        entity_reg: Entity registry z HA
        entry: Config entry
        expected_sensor_types: Set očekávaných sensor_types

    Returns:
        Počet odstraněných senzorů
    """
    removed = 0

    # Známé přejmenování a deprecated senzory
    deprecated_patterns = [
        "_battery_prediction_",  # nahrazeno battery_forecast
        "_old_",  # obecný pattern pro staré
    ]

    from homeassistant.helpers import entity_registry as er

    entries = er.async_entries_for_config_entry(entity_reg, entry.entry_id)

    for entity_entry in entries:
        # Extrahuj sensor_type z entity_id
        # Formát: sensor.oig_{box_id}_{sensor_type}
        parts = entity_entry.entity_id.split("_")
        if len(parts) < 3 or not entity_entry.entity_id.startswith("sensor.oig_"):
            continue

        # SKIP bojler senzory - ty mají vlastní životní cyklus
        # Format: sensor.oig_bojler_{sensor_type}
        if "_bojler_" in entity_entry.entity_id or entity_entry.entity_id.startswith(
            "sensor.oig_bojler"
        ):
            _LOGGER.debug(f"Skipping boiler sensor cleanup: {entity_entry.entity_id}")
            continue

        # Sensor type je vše po box_id
        # sensor.oig_{box_id}_{zbytek} -> zbytek je sensor_type
        # Najdeme index za "sensor.oig_" a box_id
        prefix = "sensor.oig_"
        if entity_entry.entity_id.startswith(prefix):
            after_prefix = entity_entry.entity_id[len(prefix) :]
            parts_after = after_prefix.split("_", 1)  # Split pouze na box_id a zbytek
            if len(parts_after) > 1:
                sensor_type = parts_after[1]  # Vše za box_id
            else:
                continue
        else:
            continue

        # Check deprecated patterns
        is_deprecated = any(
            pattern in entity_entry.entity_id for pattern in deprecated_patterns
        )

        # Check if sensor_type is expected
        is_expected = sensor_type in expected_sensor_types

        if is_deprecated or not is_expected:
            try:
                _LOGGER.info(
                    f"🗑️ Removing deprecated/renamed sensor: {entity_entry.entity_id} (type: {sensor_type})"
                )
                entity_reg.async_remove(entity_entry.entity_id)
                removed += 1
            except Exception as e:
                _LOGGER.error(f"Failed to remove sensor {entity_entry.entity_id}: {e}")

    return removed


async def _cleanup_removed_devices(
    device_reg, entity_reg, entry: ConfigEntry, coordinator
) -> int:
    """
    Smaže zařízení pro Battery Boxy které už neexistují v coordinator.data.

    Args:
        device_reg: Device registry z HA
        entity_reg: Entity registry z HA
        entry: Config entry
        coordinator: Data coordinator

    Returns:
        Počet odstraněných zařízení
    """
    if not coordinator or not coordinator.data:
        return 0

    removed = 0
    current_box_ids = set(coordinator.data.keys())

    from homeassistant.helpers import device_registry as dr

    devices = dr.async_entries_for_config_entry(device_reg, entry.entry_id)

    for device in devices:
        device_box_id = None

        # Extrahuj box_id z identifiers
        for identifier in device.identifiers:
            if identifier[0] in [DOMAIN, "oig_cloud_analytics", "oig_cloud_shield"]:
                identifier_value = identifier[1]
                # Odstraň suffix _shield/_analytics/_boiler pokud existuje
                device_box_id = (
                    identifier_value.replace("_shield", "")
                    .replace("_analytics", "")
                    .replace("_boiler", "")
                )

                # OPRAVA: Pokud je to speciální zařízení (analytics, shield, boiler), nemaž ho
                # Tato zařízení existují vždy když je integrace zapnutá
                if (
                    "_analytics" in identifier_value
                    or "_shield" in identifier_value
                    or "_boiler" in identifier_value
                ):
                    device_box_id = None  # Přeskočíme toto zařízení
                break

        if device_box_id and device_box_id not in current_box_ids:
            try:
                _LOGGER.warning(
                    f"🗑️ Removing device for non-existent box: {device.name} (box_id: {device_box_id})"
                )

                # Smaž entity prvně
                from homeassistant.helpers import entity_registry as er

                entities = er.async_entries_for_device(entity_reg, device.id)
                for entity in entities:
                    entity_reg.async_remove(entity.entity_id)
                    _LOGGER.debug(f"  Removed entity: {entity.entity_id}")

                device_reg.async_remove_device(device.id)
                removed += 1
            except Exception as e:
                _LOGGER.error(f"Failed to remove device {device.name}: {e}")

    return removed


async def _cleanup_empty_devices_internal(
    device_reg, entity_reg, entry: ConfigEntry
) -> int:
    """
    Smaže zařízení která nemají žádné entity.

    Args:
        device_reg: Device registry z HA
        entity_reg: Entity registry z HA
        entry: Config entry

    Returns:
        Počet odstraněných zařízení
    """
    removed = 0

    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    devices = dr.async_entries_for_config_entry(device_reg, entry.entry_id)

    for device in devices:
        entities = er.async_entries_for_device(entity_reg, device.id)

        if not entities:
            try:
                _LOGGER.info(f"🗑️ Removing empty device: {device.name}")
                device_reg.async_remove_device(device.id)
                removed += 1
            except Exception as e:
                _LOGGER.error(f"Failed to remove empty device {device.name}: {e}")

    return removed


async def _cleanup_all_orphaned_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator,
    expected_sensor_types: set[str],
) -> int:
    """
    Univerzální cleanup pro všechny typy osiřelých entit.
    Sjednocuje 3 stávající cleanup funkce.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        coordinator: Data coordinator
        expected_sensor_types: Set očekávaných sensor_types podle konfigurace

    Returns:
        Celkový počet odstraněných položek (sensors + devices)
    """
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    _LOGGER.info("🧹 Starting comprehensive cleanup of orphaned entities")

    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    # 1. Cleanup starých/přejmenovaných senzorů
    removed_sensors = await _cleanup_renamed_sensors(
        entity_reg, entry, expected_sensor_types
    )

    # 2. Cleanup osiřelých zařízení (neexistující Battery Boxy)
    removed_devices = await _cleanup_removed_devices(
        device_reg, entity_reg, entry, coordinator
    )

    # 3. Cleanup prázdných zařízení (bez entit)
    removed_empty = await _cleanup_empty_devices_internal(device_reg, entity_reg, entry)

    total_removed = removed_sensors + removed_devices + removed_empty

    _LOGGER.info(
        f"✅ Cleanup completed: {removed_sensors} deprecated sensors, "
        f"{removed_devices} orphaned devices, {removed_empty} empty devices "
        f"(total: {total_removed} items removed)"
    )

    return total_removed


def get_device_info_for_sensor(
    sensor_config: Dict[str, Any],
    box_id: str,
    main_device_info: Dict[str, Any],
    analytics_device_info: Dict[str, Any],
    shield_device_info: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Vrací správný device_info pro senzor podle device_mapping.

    Args:
        sensor_config: Konfigurace senzoru obsahující device_mapping
        box_id: ID Battery Boxu
        main_device_info: Device info pro hlavní OIG zařízení
        analytics_device_info: Device info pro Analytics & Predictions
        shield_device_info: Device info pro ServiceShield

    Returns:
        Device info dictionary pro senzor
    """
    _ = box_id
    device_mapping = sensor_config.get("device_mapping", "main")

    if device_mapping == "analytics":
        return analytics_device_info
    elif device_mapping == "shield":
        return shield_device_info
    else:  # "main" nebo jiná hodnota (fallback na main)
        return main_device_info


async def async_setup_entry(  # noqa: C901
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OIG Cloud sensors from a config entry."""
    _LOGGER.debug("Starting sensor setup with coordinator data")

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # PERFORMANCE FIX: Collect all sensors in one list instead of calling async_add_entities 17 times
    all_sensors: List[Any] = []

    # Do not block platform setup waiting for coordinator refresh.
    # HA will warn if setup exceeds 10s; sensors can be registered immediately and will
    # populate when coordinator/local entities become available.
    if coordinator.data is None:
        _LOGGER.debug(
            "Coordinator data not ready during sensor setup; registering entities anyway"
        )
    else:
        try:
            _LOGGER.debug(
                "Setting up sensors with coordinator data: %s devices",
                len(coordinator.data),
            )
        except Exception:
            _LOGGER.debug(
                "Setting up sensors with coordinator data (device count unavailable)"
            )

    # === CLEANUP PŘED REGISTRACÍ ===
    # POZN: Cleanup je vypnutý kvůli pomalému setupu (>10s)
    # Cleanup běží pouze při první instalaci nebo pokud je explicitně vyžádán
    # expected_sensor_types = _get_expected_sensor_types(hass, entry)
    # await _cleanup_all_orphaned_entities(
    #     hass, entry, coordinator, expected_sensor_types
    # )

    # === DEVICE INFO OBJEKTY ===
    # Vytvoříme device_info objekty jednou pro všechny senzory
    inverter_sn = resolve_box_id(coordinator)

    # Pokud resolve_box_id selže, zkusíme číslo z title a uložíme ho
    if inverter_sn == "unknown":
        from_title = None
        try:
            import re

            m = re.search(r"(\\d{6,})", entry.title or "")
            if m:
                from_title = m.group(1)
        except Exception:
            from_title = None

        if from_title:
            inverter_sn = from_title
            new_opts = dict(entry.options)
            if new_opts.get("box_id") != inverter_sn:
                new_opts["box_id"] = inverter_sn
                hass.config_entries.async_update_entry(entry, options=new_opts)
                _LOGGER.info(
                    "Stored box_id=%s from title into entry options", inverter_sn
                )

    if inverter_sn == "unknown":
        _LOGGER.error("No valid box_id/inverter_sn resolved, skipping sensor setup")
        return

    # Ulož box_id do options, ať je dostupné i bez dat z koordinátoru
    if entry.options.get("box_id") != inverter_sn:
        new_opts = dict(entry.options)
        new_opts["box_id"] = inverter_sn
        hass.config_entries.async_update_entry(entry, options=new_opts)
        _LOGGER.info("Stored box_id=%s into entry options", inverter_sn)

    # Propaguj box_id přímo do koordinátoru, aby všechny senzory měly stabilní ID
    try:
        setattr(coordinator, "forced_box_id", inverter_sn)
    except Exception:
        _LOGGER.debug("Could not set forced_box_id on coordinator")

    # Main OIG Device

    # Analytics & Predictions Device (prefer definition from __init__.py for consistency)
    analytics_device_info: Dict[str, Any] = hass.data.get(DOMAIN, {}).get(
        entry.entry_id, {}
    ).get("analytics_device_info") or {
        "identifiers": {(DOMAIN, f"{inverter_sn}_analytics")},
        "name": f"Analytics & Predictions {inverter_sn}",
        "manufacturer": "OIG",
        "model": "Analytics Module",
        "via_device": (DOMAIN, inverter_sn),
        "entry_type": "service",
    }

    # ServiceShield Device

    _LOGGER.debug(f"Created device_info objects for box_id: {inverter_sn}")

    # ================================================================
    # SECTION 0: DATA SOURCE STATE SENSOR (always on)
    # ================================================================
    try:
        data_source_sensor = OigCloudDataSourceSensor(hass, coordinator, entry)
        all_sensors.append(data_source_sensor)
        _LOGGER.info("Registered data source state sensor")
    except Exception as e:
        _LOGGER.error(f"Error creating data source sensor: {e}", exc_info=True)

    # ================================================================
    # SECTION 1: BASIC DATA SENSORS (kategorie: "data")
    # ================================================================
    # Základní senzory s daty z API - vždy aktivní
    # Device: main_device_info (OIG Cloud {box_id})
    # Třída: OigCloudDataSensor
    # ================================================================
    basic_sensors: List[Any] = []

    try:
        data_sensors = {
            k: v
            for k, v in SENSOR_TYPES.items()
            if v.get("sensor_type_category") == "data"
        }
        _LOGGER.debug(f"Found {len(data_sensors)} data sensors to create")

        for sensor_type, config in data_sensors.items():
            try:
                from .entities.data_sensor import OigCloudDataSensor

                sensor = OigCloudDataSensor(coordinator, sensor_type)

                # Ověříme, že senzor má správnou device_info před přidáním
                if hasattr(sensor, "device_info") and sensor.device_info is not None:
                    if not isinstance(sensor.device_info, dict):
                        _LOGGER.error(
                            f"Sensor {sensor_type} has invalid device_info type: {type(sensor.device_info)}"
                        )
                        continue

                basic_sensors.append(sensor)
                _LOGGER.debug(f"Created data sensor: {sensor_type}")
            except ImportError as e:
                _LOGGER.error(
                    f"OigCloudDataSensor not available for {sensor_type}: {e}"
                )
                continue
            except Exception as e:
                _LOGGER.error(f"Error creating data sensor {sensor_type}: {e}")
                continue

        if basic_sensors:
            _LOGGER.info(f"Registering {len(basic_sensors)} basic sensors")
            all_sensors.extend(
                basic_sensors
            )  # PERFORMANCE: Collect instead of immediate add
        else:
            _LOGGER.warning("No basic sensors could be created")
    except Exception as e:
        _LOGGER.error(f"Error initializing basic sensors: {e}", exc_info=True)

    # ================================================================
    # SECTION 2: COMPUTED SENSORS (kategorie: "computed")
    # ================================================================
    # Vypočítané hodnoty z existujících dat - vždy aktivní
    # Device: main_device_info (OIG Cloud {box_id})
    # Třída: OigCloudComputedSensor
    # ================================================================
    computed_sensors: List[Any] = []
    try:
        if coordinator.data is not None:
            computed_sensor_types = {
                k: v
                for k, v in SENSOR_TYPES.items()
                if v.get("sensor_type_category") == "computed"
            }
            _LOGGER.debug(
                f"Found {len(computed_sensor_types)} computed sensors to create"
            )

            for sensor_type, config in computed_sensor_types.items():
                try:
                    from .entities.computed_sensor import OigCloudComputedSensor

                    sensor = OigCloudComputedSensor(coordinator, sensor_type)

                    # Ověříme device_info
                    if (
                        hasattr(sensor, "device_info")
                        and sensor.device_info is not None
                    ):
                        if not isinstance(sensor.device_info, dict):
                            _LOGGER.error(
                                f"Computed sensor {sensor_type} has invalid device_info type: {type(sensor.device_info)}"
                            )
                            continue

                    computed_sensors.append(sensor)
                    _LOGGER.debug(f"Created computed sensor: {sensor_type}")
                except ImportError as e:
                    _LOGGER.error(
                        f"OigCloudComputedSensor not available for {sensor_type}: {e}"
                    )
                    continue
                except Exception as e:
                    _LOGGER.error(f"Error creating computed sensor {sensor_type}: {e}")
                    continue

            if computed_sensors:
                _LOGGER.info(f"Registering {len(computed_sensors)} computed sensors")
                all_sensors.extend(computed_sensors)  # PERFORMANCE: Collect
            else:
                _LOGGER.debug("No computed sensors found")
        else:
            _LOGGER.debug("Coordinator data is None, skipping computed sensors")
    except Exception as e:
        _LOGGER.error(f"Error initializing computed sensors: {e}", exc_info=True)

    # ================================================================
    # SECTION 3: EXTENDED SENSORS (kategorie: "extended")
    # ================================================================
    # Rozšířené metriky - volitelné (enable_extended_sensors flag)
    # Device: main_device_info (OIG Cloud {box_id})
    # Třída: OigCloudDataSensor (s extended=True)
    # ================================================================
    extended_sensors_enabled = entry.options.get("enable_extended_sensors", False)
    _LOGGER.debug(f"Extended sensors enabled from options: {extended_sensors_enabled}")

    if extended_sensors_enabled is True:
        extended_sensors: List[Any] = []
        try:
            if coordinator.data is not None:
                extended_sensor_types = {
                    k: v
                    for k, v in SENSOR_TYPES.items()
                    if v.get("sensor_type_category") == "extended"
                }
                _LOGGER.debug(
                    f"Found {len(extended_sensor_types)} extended sensors to create"
                )

                for sensor_type, config in extended_sensor_types.items():
                    try:
                        from .entities.data_sensor import OigCloudDataSensor

                        # OPRAVA: Odstraňujeme _ext suffix - extended už je v názvu sensor_type
                        extended_sensor = OigCloudDataSensor(
                            coordinator, sensor_type, extended=True
                        )
                        # Neměníme unique_id ani entity_id - sensor_type už obsahuje "extended"

                        extended_sensors.append(extended_sensor)
                        _LOGGER.debug(f"Created extended sensor: {sensor_type}")
                    except ImportError as e:
                        _LOGGER.error(
                            f"OigCloudDataSensor not available for {sensor_type}: {e}"
                        )
                        continue
                    except Exception as e:
                        _LOGGER.error(
                            f"Error creating extended sensor {sensor_type}: {e}"
                        )
                        continue

                if extended_sensors:
                    _LOGGER.info(
                        f"Registering {len(extended_sensors)} extended sensors"
                    )
                    all_sensors.extend(extended_sensors)  # PERFORMANCE: Collect
                else:
                    _LOGGER.debug("No extended sensors found")
            else:
                _LOGGER.debug("Coordinator data is None, skipping extended sensors")
        except Exception as e:
            _LOGGER.error(f"Error initializing extended sensors: {e}", exc_info=True)
    else:
        _LOGGER.info("Extended sensors disabled - skipping creation")

    # ================================================================
    # SECTION 4: STATISTICS SENSORS (kategorie: "statistics")
    # ================================================================
    # Historická statistika - volitelné (enable_statistics flag)
    # Device: analytics_device_info (Analytics & Predictions {box_id})
    # Třída: OigCloudStatisticsSensor
    # ================================================================
    statistics_enabled = hass.data[DOMAIN][entry.entry_id].get(
        "statistics_enabled", False
    )
    statistics_option = entry.options.get("enable_statistics", True)
    _LOGGER.info(
        f"Statistics check: option={statistics_option}, hass.data={statistics_enabled}"
    )

    if statistics_enabled:
        try:
            if coordinator.data is not None and SENSOR_TYPES:
                from .entities.statistics_sensor import OigCloudStatisticsSensor

                statistics_sensors: List[Any] = []

                for sensor_type, config in SENSOR_TYPES.items():
                    if config.get("sensor_type_category") == "statistics":
                        try:
                            _LOGGER.debug(f"Creating statistics sensor: {sensor_type}")

                            # OPRAVA: Použít předem definované analytics_device_info
                            sensor = OigCloudStatisticsSensor(
                                coordinator, sensor_type, analytics_device_info
                            )

                            statistics_sensors.append(sensor)
                            _LOGGER.debug(
                                f"Successfully created statistics sensor: {sensor_type}"
                            )
                        except Exception as e:
                            _LOGGER.error(
                                f"Error creating statistics sensor {sensor_type}: {e}",
                                exc_info=True,
                            )
                            continue

                if statistics_sensors:
                    _LOGGER.info(
                        f"Registering {len(statistics_sensors)} statistics sensors"
                    )
                    all_sensors.extend(statistics_sensors)  # PERFORMANCE: Collect
                else:
                    _LOGGER.debug("No statistics sensors found")
            else:
                _LOGGER.debug(
                    "Coordinator data is None or SENSOR_TYPES empty, skipping statistics sensors"
                )
        except Exception as e:
            _LOGGER.error(f"Error initializing statistics sensors: {e}", exc_info=True)
    else:
        _LOGGER.info("Statistics sensors disabled - skipping creation")

    # ================================================================
    # SECTION 5: SOLAR FORECAST SENSORS (kategorie: "solar_forecast")
    # ================================================================
    # Solární předpovědi - volitelné (enable_solar_forecast flag)
    # Device: analytics_device_info (Analytics & Predictions {box_id})
    # Třída: OigCloudSolarForecastSensor
    # ================================================================
    if entry.options.get("enable_solar_forecast", False):
        try:
            from .entities.solar_forecast_sensor import OigCloudSolarForecastSensor

            solar_sensors: List[Any] = []
            if SENSOR_TYPES:
                for sensor_type, config in SENSOR_TYPES.items():
                    if config.get("sensor_type_category") == "solar_forecast":
                        # OPRAVA: Předat analytics_device_info
                        solar_sensors.append(
                            OigCloudSolarForecastSensor(
                                coordinator, sensor_type, entry, analytics_device_info
                            )
                        )

            if solar_sensors:
                _LOGGER.debug(
                    f"Registering {len(solar_sensors)} solar forecast sensors"
                )
                all_sensors.extend(solar_sensors)  # PERFORMANCE: Collect

                # Uložíme reference na solar forecast senzory pro službu
                hass.data[DOMAIN][entry.entry_id][
                    "solar_forecast_sensors"
                ] = solar_sensors
                _LOGGER.debug("Solar forecast sensors stored for service access")
            else:
                _LOGGER.debug(
                    "No solar forecast sensors found - this is normal if not configured"
                )
        except ImportError as e:
            _LOGGER.warning(f"Solar forecast sensors not available: {e}")
        except Exception as e:
            _LOGGER.error(f"Error initializing solar forecast sensors: {e}")

    # ================================================================
    # SECTION 6: SERVICESHIELD SENSORS (kategorie: "shield")
    # ================================================================
    # ServiceShield monitoring - vždy aktivní (nativní součást)
    # Device: shield_device_info (ServiceShield {box_id})
    # Třída: OigCloudShieldSensor
    # ================================================================
    try:
        if coordinator.data is not None and SENSOR_TYPES:
            from .entities.shield_sensor import OigCloudShieldSensor

            shield_sensors: List[Any] = []
            for sensor_type, config in SENSOR_TYPES.items():
                if config.get("sensor_type_category") == "shield":
                    try:
                        sensor = OigCloudShieldSensor(coordinator, sensor_type)

                        # Ověříme device_info
                        if (
                            hasattr(sensor, "device_info")
                            and sensor.device_info is not None
                        ):
                            if not isinstance(sensor.device_info, dict):
                                _LOGGER.error(
                                    f"Shield sensor {sensor_type} has invalid device_info type: {type(sensor.device_info)}"
                                )
                                continue

                        shield_sensors.append(sensor)
                        _LOGGER.debug(f"Created shield sensor: {sensor_type}")
                    except Exception as e:
                        _LOGGER.error(
                            f"Error creating shield sensor {sensor_type}: {e}"
                        )
                        continue

            if shield_sensors:
                _LOGGER.debug(
                    f"Registering {len(shield_sensors)} ServiceShield sensors"
                )
                all_sensors.extend(shield_sensors)  # PERFORMANCE: Collect
            else:
                _LOGGER.debug("No ServiceShield sensors found")
        else:
            _LOGGER.debug(
                "Coordinator data is None or SENSOR_TYPES empty, skipping ServiceShield sensors"
            )
    except Exception as e:
        _LOGGER.error(f"Error initializing ServiceShield sensors: {e}")

    # ================================================================
    # SECTION 7: NOTIFICATION SENSORS (kategorie: "notification")
    # ================================================================
    # Systémové notifikace - vždy aktivní
    # Device: main_device_info (OIG Cloud {box_id})
    # Třída: OigCloudDataSensor (s notification=True)
    # ================================================================
    try:
        if coordinator.data is not None and SENSOR_TYPES:
            from .entities.data_sensor import OigCloudDataSensor

            notification_sensors: List[Any] = []
            notification_sensor_types = {
                k: v
                for k, v in SENSOR_TYPES.items()
                if v.get("sensor_type_category") == "notification"
            }
            _LOGGER.debug(
                f"Found {len(notification_sensor_types)} notification sensors to create"
            )

            for sensor_type, config in notification_sensor_types.items():
                try:
                    sensor = OigCloudDataSensor(
                        coordinator, sensor_type, notification=True
                    )

                    # Jednoduché ověření device_info
                    if (
                        hasattr(sensor, "device_info")
                        and sensor.device_info is not None
                    ):
                        if not isinstance(sensor.device_info, dict):
                            _LOGGER.error(
                                f"Notification sensor {sensor_type} has invalid device_info type: {type(sensor.device_info)}"
                            )
                            continue

                    notification_sensors.append(sensor)
                    _LOGGER.debug(f"Created notification sensor: {sensor_type}")
                except Exception as e:
                    _LOGGER.error(
                        f"Error creating notification sensor {sensor_type}: {e}"
                    )
                    continue

            if notification_sensors:
                _LOGGER.info(
                    f"Registering {len(notification_sensors)} notification sensors"
                )
                all_sensors.extend(notification_sensors)  # PERFORMANCE: Collect
            else:
                _LOGGER.debug("No notification sensors found")
        else:
            _LOGGER.debug(
                "Coordinator data is None or SENSOR_TYPES empty, skipping notification sensors"
            )
    except Exception as e:
        _LOGGER.error(f"Error initializing notification sensors: {e}")

    # ================================================================
    # SECTION 8: BATTERY PREDICTION SENSORS (kategorie: "battery_prediction")
    # ================================================================
    # Predikce baterie - volitelné (enable_battery_prediction flag)
    # Device: analytics_device_info (Analytics & Predictions {box_id})
    # Třída: OigCloudBatteryForecastSensor
    # ================================================================
    battery_prediction_enabled = entry.options.get("enable_battery_prediction", False)
    _LOGGER.info(f"Battery prediction enabled: {battery_prediction_enabled}")

    if battery_prediction_enabled:
        try:
            from .battery_forecast.sensors.ha_sensor import (
                OigCloudBatteryForecastSensor,
            )

            battery_forecast_sensors: List[Any] = []
            if SENSOR_TYPES:
                for sensor_type, config in SENSOR_TYPES.items():
                    if config.get("sensor_type_category") == "battery_prediction":
                        try:
                            # OPRAVA: Předat analytics_device_info a hass
                            sensor = OigCloudBatteryForecastSensor(
                                coordinator,
                                sensor_type,
                                entry,
                                analytics_device_info,
                                hass,
                            )
                            battery_forecast_sensors.append(sensor)

                            _LOGGER.debug(
                                f"Created battery prediction sensor: {sensor_type}"
                            )
                        except ValueError as e:
                            _LOGGER.warning(
                                f"Skipping battery prediction sensor {sensor_type}: {e}"
                            )
                            continue
                        except Exception as e:
                            _LOGGER.error(
                                f"Error creating battery prediction sensor {sensor_type}: {e}"
                            )
                            continue

            if battery_forecast_sensors:
                _LOGGER.info(
                    f"Registering {len(battery_forecast_sensors)} battery prediction sensors"
                )
                all_sensors.extend(battery_forecast_sensors)  # PERFORMANCE: Collect

                # PHASE 3: Set forecast sensor reference in BalancingManager
                try:
                    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
                        balancing_manager = hass.data[DOMAIN][entry.entry_id].get(
                            "balancing_manager"
                        )
                        if balancing_manager and battery_forecast_sensors:
                            # Use first forecast sensor (typically battery_forecast)
                            forecast_sensor = battery_forecast_sensors[0]
                            balancing_manager.set_forecast_sensor(forecast_sensor)
                            balancing_manager.set_coordinator(coordinator)
                            _LOGGER.info(
                                "✅ Connected BalancingManager to forecast sensor and coordinator"
                            )
                except Exception as e:
                    _LOGGER.debug(
                        f"Could not set forecast sensor in BalancingManager: {e}"
                    )

                # Přidat Battery Health sensor (SoH monitoring)
                try:
                    from .entities.battery_health_sensor import BatteryHealthSensor

                    health_sensor = BatteryHealthSensor(
                        coordinator,
                        "battery_health",
                        entry,
                        analytics_device_info,
                        hass,
                    )
                    all_sensors.append(health_sensor)  # PERFORMANCE: Collect
                    _LOGGER.info("✅ Registered Battery Health sensor")
                except Exception as e:
                    _LOGGER.error(f"Failed to create Battery Health sensor: {e}")

                # Battery balancing sensor - displays BalancingManager state
                try:
                    from .entities.battery_balancing_sensor import (
                        OigCloudBatteryBalancingSensor,
                    )

                    balancing_sensors: List[Any] = []

                    for sensor_type, config in SENSOR_TYPES.items():
                        if config.get("sensor_type_category") == "battery_balancing":
                            sensor = OigCloudBatteryBalancingSensor(
                                coordinator,
                                sensor_type,
                                entry,
                                analytics_device_info,
                                hass,
                            )
                            balancing_sensors.append(sensor)
                            _LOGGER.debug(
                                f"Created battery balancing sensor: {sensor_type}"
                            )

                    if balancing_sensors:
                        _LOGGER.info(
                            f"Registering {len(balancing_sensors)} battery balancing sensors"
                        )
                        all_sensors.extend(balancing_sensors)  # PERFORMANCE: Collect
                except Exception as e:
                    _LOGGER.error(f"Error creating battery balancing sensors: {e}")

                # Přidat také grid charging plan sensor
                try:
                    from .battery_forecast.sensors.grid_charging_sensor import (
                        OigCloudGridChargingPlanSensor,
                    )

                    grid_charging_sensors: List[Any] = []

                    for sensor_type, config in SENSOR_TYPES.items():
                        if config.get("sensor_type_category") == "grid_charging_plan":
                            sensor = OigCloudGridChargingPlanSensor(
                                coordinator, sensor_type, analytics_device_info
                            )
                            grid_charging_sensors.append(sensor)
                            _LOGGER.debug(
                                f"Created grid charging plan sensor: {sensor_type}"
                            )

                    if grid_charging_sensors:
                        _LOGGER.info(
                            f"Registering {len(grid_charging_sensors)} grid charging plan sensors"
                        )
                        all_sensors.extend(
                            grid_charging_sensors
                        )  # PERFORMANCE: Collect
                except Exception as e:
                    _LOGGER.error(f"Error creating grid charging plan sensors: {e}")

                # Přidat také battery efficiency sensor
                try:
                    from .battery_forecast.sensors.efficiency_sensor import (
                        OigCloudBatteryEfficiencySensor,
                    )

                    efficiency_sensors: List[Any] = []

                    for sensor_type, config in SENSOR_TYPES.items():
                        if config.get("sensor_type_category") == "battery_efficiency":
                            sensor = OigCloudBatteryEfficiencySensor(
                                coordinator,
                                sensor_type,
                                entry,
                                analytics_device_info,
                                hass,
                            )
                            efficiency_sensors.append(sensor)
                            _LOGGER.debug(
                                f"Created battery efficiency sensor: {sensor_type}"
                            )

                    if efficiency_sensors:
                        _LOGGER.info(
                            f"Registering {len(efficiency_sensors)} battery efficiency sensors"
                        )
                        all_sensors.extend(efficiency_sensors)  # PERFORMANCE: Collect
                except Exception as e:
                    _LOGGER.error(f"Error creating battery efficiency sensors: {e}")

                # Přidat také planner status sensor (recommended mode)
                try:
                    from .battery_forecast.sensors.recommended_sensor import (
                        OigCloudPlannerRecommendedModeSensor,
                    )

                    planner_status_sensors: List[Any] = []
                    for sensor_type, config in SENSOR_TYPES.items():
                        if config.get("sensor_type_category") == "planner_status":
                            sensor = OigCloudPlannerRecommendedModeSensor(
                                coordinator,
                                sensor_type,
                                entry,
                                analytics_device_info,
                                hass,
                            )
                            planner_status_sensors.append(sensor)
                            _LOGGER.debug(
                                f"Created planner status sensor: {sensor_type}"
                            )

                    if planner_status_sensors:
                        _LOGGER.info(
                            f"Registering {len(planner_status_sensors)} planner status sensors"
                        )
                        all_sensors.extend(planner_status_sensors)
                except Exception as e:
                    _LOGGER.error(f"Error creating planner status sensors: {e}")

                # Přidat také adaptive load profiles sensor
                try:
                    from .entities.adaptive_load_profiles_sensor import (
                        OigCloudAdaptiveLoadProfilesSensor,
                    )

                    adaptive_sensors: List[Any] = []

                    for sensor_type, config in SENSOR_TYPES.items():
                        if config.get("sensor_type_category") == "adaptive_profiles":
                            sensor = OigCloudAdaptiveLoadProfilesSensor(
                                coordinator,
                                sensor_type,
                                entry,
                                analytics_device_info,
                                hass,
                            )
                            adaptive_sensors.append(sensor)
                            _LOGGER.debug(
                                f"Created adaptive load profiles sensor: {sensor_type}"
                            )

                    if adaptive_sensors:
                        _LOGGER.info(
                            f"Registering {len(adaptive_sensors)} adaptive load profiles sensors"
                        )
                        all_sensors.extend(adaptive_sensors)  # PERFORMANCE: Collect
                except Exception as e:
                    _LOGGER.error(f"Error creating adaptive load profiles sensors: {e}")
            else:
                _LOGGER.debug("No battery prediction sensors found")
        except ImportError as e:
            _LOGGER.warning(f"Battery prediction sensors not available: {e}")
        except Exception as e:
            _LOGGER.error(f"Error initializing battery prediction sensors: {e}")
    else:
        _LOGGER.info("Battery prediction sensors disabled - skipping creation")

    # ================================================================
    # SECTION 9: PRICING & SPOT PRICE SENSORS (kategorie: "pricing")
    # ================================================================
    # Spotové ceny elektřiny - volitelné (enable_pricing flag)
    # Device: analytics_device_info (Analytics & Predictions {box_id})
    # Třídy: OigCloudAnalyticsSensor, SpotPrice15MinSensor, ExportPrice15MinSensor
    # ================================================================
    pricing_enabled = entry.options.get("enable_pricing", False)
    _LOGGER.info(f"Pricing and spot prices enabled: {pricing_enabled}")

    if pricing_enabled:
        try:
            _LOGGER.info("💰 Creating analytics sensors for pricing and spot prices")

            from .entities.analytics_sensor import OigCloudAnalyticsSensor
            from .pricing.spot_price_sensor import (
                ExportPrice15MinSensor,
                SpotPrice15MinSensor,
            )
            from .sensors.SENSOR_TYPES_SPOT import SENSOR_TYPES_SPOT

            analytics_sensors: List[Any] = []

            pricing_sensors = {
                k: v
                for k, v in SENSOR_TYPES_SPOT.items()
                if v.get("sensor_type_category") == "pricing"
            }

            _LOGGER.debug(f"Found {len(pricing_sensors)} pricing sensors to create")

            for sensor_type, config in pricing_sensors.items():
                try:
                    _LOGGER.debug(f"Creating analytics sensor: {sensor_type}")

                    # OPRAVA: Přidat 15min senzor pokud je typ spot_price_current_15min
                    if sensor_type == "spot_price_current_15min":
                        sensor = SpotPrice15MinSensor(
                            coordinator, entry, sensor_type, analytics_device_info
                        )
                        _LOGGER.debug(f"Created 15min spot price sensor: {sensor_type}")
                    elif sensor_type == "export_price_current_15min":
                        sensor = ExportPrice15MinSensor(
                            coordinator, entry, sensor_type, analytics_device_info
                        )
                        _LOGGER.debug(
                            f"Created 15min export price sensor: {sensor_type}"
                        )
                    else:
                        # OPRAVA: Použít předem definované analytics_device_info
                        sensor = OigCloudAnalyticsSensor(
                            coordinator, sensor_type, entry, analytics_device_info
                        )
                        _LOGGER.debug(f"Created analytics sensor: {sensor_type}")

                    analytics_sensors.append(sensor)
                    _LOGGER.debug(
                        f"Successfully created analytics sensor: {sensor_type}"
                    )
                except Exception as e:
                    _LOGGER.error(
                        f"Failed to create analytics sensor {sensor_type}: {e}",
                        exc_info=True,
                    )
                    continue

            if analytics_sensors:
                _LOGGER.info(f"Registering {len(analytics_sensors)} analytics sensors")
                all_sensors.extend(analytics_sensors)  # PERFORMANCE: Collect
                _LOGGER.info(
                    f"Successfully registered {len(analytics_sensors)} analytics sensors"
                )

                # PŘIDÁNO: Debug log entity IDs
                for sensor in analytics_sensors:
                    _LOGGER.debug(
                        f"💰 Registered analytics sensor: {sensor.entity_id} (unique_id: {sensor.unique_id})"
                    )
            else:
                _LOGGER.warning("No analytics sensors could be created")

        except ImportError as e:
            _LOGGER.error(f"OigCloudAnalyticsSensor not available: {e}")
        except Exception as e:
            _LOGGER.error(f"Error initializing analytics sensors: {e}", exc_info=True)
    else:
        _LOGGER.info("💰 Pricing disabled - skipping pricing and spot price sensors")

    # ================================================================
    # SECTION 10: ČHMÚ WEATHER WARNINGS (kategorie: "chmu_warnings")
    # ================================================================
    # Meteorologická varování ČHMÚ - volitelné (enable_chmu_warnings flag)
    # Device: analytics_device_info (Analytics & Predictions {box_id})
    # Třída: OigCloudChmuSensor
    # ================================================================
    chmu_enabled = entry.options.get("enable_chmu_warnings", False)
    _LOGGER.info(f"ČHMÚ weather warnings enabled: {chmu_enabled}")

    if chmu_enabled:
        try:
            _LOGGER.info("🌦️ Creating ČHMÚ weather warning sensors")

            from .entities.chmu_sensor import OigCloudChmuSensor
            from .sensors.SENSOR_TYPES_CHMU import SENSOR_TYPES_CHMU

            chmu_sensors: List[Any] = []

            chmu_sensor_types = {
                k: v
                for k, v in SENSOR_TYPES_CHMU.items()
                if v.get("sensor_type_category") == "chmu_warnings"
            }

            _LOGGER.debug(f"Found {len(chmu_sensor_types)} ČHMÚ sensors to create")

            for sensor_type, config in chmu_sensor_types.items():
                try:
                    _LOGGER.debug(f"Creating ČHMÚ sensor: {sensor_type}")

                    sensor = OigCloudChmuSensor(
                        coordinator, sensor_type, entry, analytics_device_info
                    )
                    chmu_sensors.append(sensor)
                    _LOGGER.debug(f"Created ČHMÚ sensor: {sensor_type}")

                except Exception as e:
                    _LOGGER.error(
                        f"Failed to create ČHMÚ sensor {sensor_type}: {e}",
                        exc_info=True,
                    )
                    continue

            if chmu_sensors:
                _LOGGER.info(f"Registering {len(chmu_sensors)} ČHMÚ sensors")
                all_sensors.extend(chmu_sensors)  # PERFORMANCE: Collect
                _LOGGER.info(
                    f"Successfully registered {len(chmu_sensors)} ČHMÚ sensors"
                )

                # Debug log entity IDs
                for sensor in chmu_sensors:
                    _LOGGER.debug(
                        f"🌦️ Registered ČHMÚ sensor: {sensor.entity_id} (unique_id: {sensor.unique_id})"
                    )
            else:
                _LOGGER.warning("No ČHMÚ sensors could be created")

        except ImportError as e:
            _LOGGER.error(f"OigCloudChmuSensor not available: {e}")
        except Exception as e:
            _LOGGER.error(f"Error initializing ČHMÚ sensors: {e}", exc_info=True)
    else:
        _LOGGER.info("🌦️ ČHMÚ warnings disabled - skipping weather warning sensors")

    # ================================================================
    # SECTION 11: BOILER SENSORS (kategorie: "boiler")
    # ================================================================
    # Bojlerové senzory - volitelné (enable_boiler flag)
    # Device: OIG Bojler (samostatné zařízení)
    # Třída: BoilerSensor* (13 senzorů)
    # ================================================================
    boiler_enabled = entry.options.get("enable_boiler", False)
    _LOGGER.info(f"Boiler module enabled: {boiler_enabled}")

    if boiler_enabled:
        try:
            boiler_coordinator = hass.data[DOMAIN][entry.entry_id].get(
                "boiler_coordinator"
            )

            if boiler_coordinator is None:
                _LOGGER.warning(
                    "Boiler coordinator not found in hass.data - skipping boiler sensors"
                )
            else:
                _LOGGER.info("🔥 Creating boiler sensors")

                from .boiler.sensors import get_boiler_sensors

                boiler_sensors = get_boiler_sensors(boiler_coordinator)

                if boiler_sensors:
                    _LOGGER.info(f"Registering {len(boiler_sensors)} boiler sensors")
                    all_sensors.extend(boiler_sensors)  # PERFORMANCE: Collect
                    _LOGGER.info(
                        f"Successfully registered {len(boiler_sensors)} boiler sensors"
                    )

                    # Debug log entity IDs
                    for sensor in boiler_sensors:
                        _LOGGER.debug(
                            f"🔥 Registered boiler sensor: {sensor.entity_id} (unique_id: {sensor.unique_id})"
                        )
                else:
                    _LOGGER.warning("No boiler sensors could be created")

        except ImportError as e:
            _LOGGER.error(f"Boiler sensors not available: {e}")
        except Exception as e:
            _LOGGER.error(f"Error initializing boiler sensors: {e}", exc_info=True)
    else:
        _LOGGER.info("🔥 Boiler module disabled - skipping boiler sensors")

    # ================================================================
    # PERFORMANCE FIX: Register all sensors at once instead of 17 separate calls
    # ================================================================
    if all_sensors:
        _LOGGER.info(
            f"🚀 Registering {len(all_sensors)} sensors in one batch (PERFORMANCE OPTIMIZATION)"
        )
        # Avoid update_before_add=True – it can trigger expensive first updates for hundreds
        # of entities and cause HA "setup taking over 10 seconds" warnings.
        async_add_entities(all_sensors, False)
        _LOGGER.info(f"✅ All {len(all_sensors)} sensors registered successfully")
    else:
        _LOGGER.warning("⚠️ No sensors were created during setup")

    _LOGGER.info("OIG Cloud sensor setup completed")


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry and clean up empty devices."""
    try:
        # Zkontrolujeme, zda máme data pro tuto config entry
        if DOMAIN not in hass.data:
            _LOGGER.debug(f"Domain {DOMAIN} not found in hass.data during unload")
            return True

        if config_entry.entry_id not in hass.data[DOMAIN]:
            _LOGGER.debug(
                f"Config entry {config_entry.entry_id} not found in domain data during unload"
            )
            return True

        domain_data = hass.data[DOMAIN][config_entry.entry_id]

        # Pokud máme coordinator, zastavíme ho
        if "coordinator" in domain_data:
            coordinator = domain_data["coordinator"]
            if hasattr(coordinator, "async_shutdown"):
                await coordinator.async_shutdown()
            _LOGGER.debug(f"Coordinator shut down for entry {config_entry.entry_id}")

        # Vyčistíme prázdná zařízení (použijeme novou interní funkci)
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        device_reg = dr.async_get(hass)
        entity_reg = er.async_get(hass)
        await _cleanup_empty_devices_internal(device_reg, entity_reg, config_entry)

        # Vyčistíme data pro tuto config entry
        del hass.data[DOMAIN][config_entry.entry_id]

        # Pokud to byla poslední config entry, vyčistíme i domain
        if not hass.data[DOMAIN]:
            del hass.data[DOMAIN]

        _LOGGER.debug(f"Successfully unloaded config entry {config_entry.entry_id}")
        return True
    except Exception as e:
        _LOGGER.error(f"Error unloading config entry {config_entry.entry_id}: {e}")
        return False


async def _cleanup_empty_devices(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Clean up devices that have no entities, including service devices."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers.device_registry import DeviceEntryType

    _LOGGER.info(
        f"Starting cleanup of empty devices for config entry {config_entry.entry_id}"
    )

    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    # Najdeme všechna zařízení pro tuto config entry
    devices = dr.async_entries_for_config_entry(device_reg, config_entry.entry_id)
    _LOGGER.debug(f"Found {len(devices)} devices for config entry")

    removed_count = 0
    kept_count = 0

    for device in devices:
        # Najdeme všechny entity pro toto zařízení
        entities = er.async_entries_for_device(entity_reg, device.id)
        device_type = (
            "service" if device.entry_type == DeviceEntryType.SERVICE else "device"
        )

        _LOGGER.debug(
            f"Checking {device_type}: {device.name} (ID: {device.id}) - {len(entities)} entities"
        )

        # Pokud zařízení nemá žádné entity, smažeme ho
        if not entities:
            _LOGGER.warning(
                f"Removing empty {device_type}: {device.name} ({device.id})"
            )
            try:
                device_reg.async_remove_device(device.id)
                removed_count += 1
                _LOGGER.info(f"Successfully removed empty {device_type}: {device.name}")
            except Exception as e:
                _LOGGER.error(f"Failed to remove {device_type} {device.name}: {e}")
        else:
            entity_names = [entity.entity_id for entity in entities]
            _LOGGER.debug(
                f"Keeping {device_type} {device.name} with entities: {entity_names}"
            )
            kept_count += 1

    _LOGGER.info(
        f"Device cleanup completed: removed {removed_count}, kept {kept_count} devices"
    )


# ============================================================================
# DEPRECATED CLEANUP FUNCTIONS - Kept for reference, replaced by new system
# ============================================================================
# The following 3 functions have been replaced by:
#   - _cleanup_all_orphaned_entities()
#   - _cleanup_renamed_sensors()
#   - _cleanup_removed_devices()
#   - _cleanup_empty_devices_internal()
# ============================================================================
