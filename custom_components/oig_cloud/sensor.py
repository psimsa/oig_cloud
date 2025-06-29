"""Platform pro OIG Cloud senzory."""

import logging
from typing import Any, Dict, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# OPRAVA: Import SENSOR_TYPES s detailním logováním pro diagnostiku
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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OIG Cloud sensors from a config entry."""
    _LOGGER.debug("Starting sensor setup with coordinator data")

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # OPRAVA: Kontrola dostupnosti dat před vytvořením senzorů
    if coordinator.data is None:
        _LOGGER.warning("Coordinator data is None during sensor setup, retrying...")
        await coordinator.async_request_refresh()

        if coordinator.data is None:
            _LOGGER.error("Still no data from coordinator after refresh")
            return

    _LOGGER.debug(
        f"Setting up sensors with coordinator data: {len(coordinator.data)} devices"
    )

    # Vyčistíme prázdná zařízení PŘED vytvořením nových senzorů
    await _cleanup_empty_devices(hass, entry)

    # 1. Basic sensors - only if data is available
    basic_sensors: List[Any] = []

    try:
        # OPRAVA: Pouze data senzory, ne extended
        data_sensors = {
            k: v
            for k, v in SENSOR_TYPES.items()
            if v.get("sensor_type_category") == "data"
        }
        _LOGGER.debug(f"Found {len(data_sensors)} data sensors to create")

        for sensor_type, config in data_sensors.items():
            try:
                from .oig_cloud_data_sensor import OigCloudDataSensor

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
            async_add_entities(basic_sensors, True)
        else:
            _LOGGER.warning("No basic sensors could be created")
    except Exception as e:
        _LOGGER.error(f"Error initializing basic sensors: {e}", exc_info=True)

    # 2. Computed sensors - with data check
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
                    from .oig_cloud_computed_sensor import OigCloudComputedSensor

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
                async_add_entities(computed_sensors, True)
            else:
                _LOGGER.debug("No computed sensors found")
        else:
            _LOGGER.debug("Coordinator data is None, skipping computed sensors")
    except Exception as e:
        _LOGGER.error(f"Error initializing computed sensors: {e}", exc_info=True)

    # 3. Extended sensors - only if enabled and data available
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
                        from .oig_cloud_data_sensor import OigCloudDataSensor

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
                    async_add_entities(extended_sensors, True)
                else:
                    _LOGGER.debug("No extended sensors found")
            else:
                _LOGGER.debug("Coordinator data is None, skipping extended sensors")
        except Exception as e:
            _LOGGER.error(f"Error initializing extended sensors: {e}", exc_info=True)
    else:
        _LOGGER.info("Extended sensors disabled - skipping creation")

    # 4. Statistics sensors - only if enabled and data available
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
                from .oig_cloud_statistics import OigCloudStatisticsSensor
                from .sensor_types import STATISTICS_SENSOR_TYPES

                statistics_sensors: List[Any] = []

                # **OPRAVA: Získat analytics_device_info z hass.data místo nedefinované proměnné**
                analytics_device_info = hass.data[DOMAIN][entry.entry_id].get(
                    "analytics_device_info",
                    {
                        "identifiers": {(DOMAIN, "analytics")},
                        "name": "Analytics & Predictions",
                        "manufacturer": "OIG Cloud",
                        "model": "Analytics Module",
                        "sw_version": "1.0",
                    },
                )

                for sensor_type, config in SENSOR_TYPES.items():
                    if config.get("sensor_type_category") == "statistics":
                        try:
                            _LOGGER.debug(f"Creating statistics sensor: {sensor_type}")

                            # Získáme inverter_sn ze správného místa
                            inverter_sn = "unknown"

                            # Zkusíme získat z coordinator.config_entry.data
                            if (
                                hasattr(coordinator, "config_entry")
                                and coordinator.config_entry.data
                            ):
                                inverter_sn = coordinator.config_entry.data.get(
                                    "inverter_sn", "unknown"
                                )
                                _LOGGER.debug(
                                    f"Got inverter_sn from config_entry: {inverter_sn}"
                                )

                            # Pokud stále unknown, zkusíme z coordinator.data
                            if inverter_sn == "unknown" and coordinator.data:
                                first_device_key = list(coordinator.data.keys())[0]
                                inverter_sn = first_device_key
                                _LOGGER.debug(
                                    f"Got inverter_sn from coordinator.data keys: {inverter_sn}"
                                )

                            # Pokud stále unknown, zkusíme z device_info v datech
                            if inverter_sn == "unknown" and coordinator.data:
                                first_device_key = list(coordinator.data.keys())[0]
                                first_device_data = coordinator.data[first_device_key]
                                if (
                                    isinstance(first_device_data, dict)
                                    and "device_info" in first_device_data
                                ):
                                    device_info_raw = first_device_data["device_info"]
                                    if (
                                        isinstance(device_info_raw, dict)
                                        and "identifiers" in device_info_raw
                                    ):
                                        for identifier_set in device_info_raw[
                                            "identifiers"
                                        ]:
                                            if len(identifier_set) > 1:
                                                inverter_sn = identifier_set[1]
                                                _LOGGER.debug(
                                                    f"Got inverter_sn from device_info identifiers: {inverter_sn}"
                                                )
                                                break

                            _LOGGER.debug(
                                f"Final inverter_sn for statistics: {inverter_sn}"
                            )

                            # Vytvoříme Analytics Module device_info
                            device_info: Dict[str, Any] = {
                                "identifiers": {("oig_cloud_analytics", inverter_sn)},
                                "name": f"Analytics & Predictions {inverter_sn}",
                                "manufacturer": "OIG",
                                "model": "Analytics Module",
                                "via_device": ("oig_cloud", inverter_sn),
                                "entry_type": "service",
                            }

                            sensor = OigCloudStatisticsSensor(
                                coordinator, sensor_type, device_info
                            )

                            # Detailní debug device_info
                            if hasattr(sensor, "device_info"):
                                device_info_result = sensor.device_info
                                _LOGGER.debug(
                                    f"Statistics sensor {sensor_type} device_info type: {type(device_info_result)}"
                                )
                                _LOGGER.debug(
                                    f"Statistics sensor {sensor_type} device_info content: {device_info_result}"
                                )

                                if device_info_result is not None and not isinstance(
                                    device_info_result, dict
                                ):
                                    _LOGGER.error(
                                        f"Statistics sensor {sensor_type} has invalid device_info type: {type(device_info_result)}, expected dict"
                                    )
                                    continue
                            else:
                                _LOGGER.warning(
                                    f"Statistics sensor {sensor_type} has no device_info attribute"
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
                    async_add_entities(statistics_sensors, True)
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

    # 5. Solar forecast sensors - only if enabled
    if entry.options.get("enable_solar_forecast", False):
        try:
            from .oig_cloud_solar_forecast import OigCloudSolarForecastSensor

            solar_sensors: List[Any] = []
            if SENSOR_TYPES:
                for sensor_type, config in SENSOR_TYPES.items():
                    if config.get("sensor_type_category") == "solar_forecast":
                        solar_sensors.append(
                            OigCloudSolarForecastSensor(coordinator, sensor_type, entry)
                        )

            if solar_sensors:
                _LOGGER.debug(
                    f"Registering {len(solar_sensors)} solar forecast sensors"
                )
                async_add_entities(solar_sensors, True)

                # Uložíme reference na solar forecast senzory pro službu
                hass.data[DOMAIN][entry.entry_id][
                    "solar_forecast_sensors"
                ] = solar_sensors
                _LOGGER.debug(f"Solar forecast sensors stored for service access")
            else:
                _LOGGER.debug(
                    "No solar forecast sensors found - this is normal if not configured"
                )
        except ImportError as e:
            _LOGGER.warning(f"Solar forecast sensors not available: {e}")
        except Exception as e:
            _LOGGER.error(f"Error initializing solar forecast sensors: {e}")

    # 6. ServiceShield sensors - vždy aktivní (nativní součást integrace)
    try:
        if coordinator.data is not None and SENSOR_TYPES:
            from .oig_cloud_shield_sensor import OigCloudShieldSensor

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
                async_add_entities(shield_sensors, True)
            else:
                _LOGGER.debug("No ServiceShield sensors found")
        else:
            _LOGGER.debug(
                "Coordinator data is None or SENSOR_TYPES empty, skipping ServiceShield sensors"
            )
    except Exception as e:
        _LOGGER.error(f"Error initializing ServiceShield sensors: {e}")

    # 7. Notification sensors - jednoduše jako ostatní senzory
    try:
        if coordinator.data is not None and SENSOR_TYPES:
            from .oig_cloud_data_sensor import OigCloudDataSensor

            # Notification senzory vytvoříme jednoduše, bez složitého setup
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
                async_add_entities(notification_sensors, True)
            else:
                _LOGGER.debug("No notification sensors found")
        else:
            _LOGGER.debug(
                "Coordinator data is None or SENSOR_TYPES empty, skipping notification sensors"
            )
    except Exception as e:
        _LOGGER.error(f"Error initializing notification sensors: {e}")

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

        # Vyčistíme prázdná zařízení
        await _cleanup_empty_devices(hass, config_entry)

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
    from homeassistant.helpers import device_registry as dr, entity_registry as er
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
