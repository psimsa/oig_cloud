import asyncio
import logging
import hashlib

try:
    from opentelemetry import trace

    tracer = trace.get_tracer(__name__)
    _has_opentelemetry = True
except ImportError:
    tracer = None  # type: ignore
    _has_opentelemetry = False
    _LOGGER = logging.getLogger(__name__)
    _LOGGER.warning(
        "OpenTelemetry není nainstalován. Pro povolení telemetrie je nutné ručně nainstalovat balíček: pip install opentelemetry-exporter-otlp-proto-grpc==1.31.0"
    )

from homeassistant import config_entries, core
from homeassistant.exceptions import ConfigEntryNotReady

from .api.oig_cloud_api import OigCloudApi
from .const import (
    CONF_NO_TELEMETRY,
    CONF_USERNAME,
    CONF_PASSWORD,
    DOMAIN,
    CONF_STANDARD_SCAN_INTERVAL,
    CONF_EXTENDED_SCAN_INTERVAL,
)
from .services import async_setup_entry_services
from .shared.tracing import setup_tracing
from .shared.logging import setup_otel_logging
from .service_shield import ServiceShield

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: core.HomeAssistant, config: dict):
    hass.data.setdefault(DOMAIN, {})

    # 🛡️ Inicializace ServiceShieldu (ochrana volání služeb)
    shield = ServiceShield(hass)
    await shield.start()

    # Uložení pro použití ve services.py
    hass.data[DOMAIN]["shield"] = shield

    return True


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
    try:
        username = entry.data[CONF_USERNAME]
        password = entry.data[CONF_PASSWORD]
        no_telemetry = entry.data.get(CONF_NO_TELEMETRY, False)

        standard_scan_interval = entry.data.get(CONF_STANDARD_SCAN_INTERVAL, 30)
        extended_scan_interval = entry.data.get(CONF_EXTENDED_SCAN_INTERVAL, 300)

        if not no_telemetry and _has_opentelemetry:
            email_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()
            hass_id = hashlib.sha256(hass.data["core.uuid"].encode("utf-8")).hexdigest()

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, setup_tracing, email_hash, hass_id)

            api_logger = logging.getLogger(
                "custom_components.oig_cloud.api.oig_cloud_api"
            )
            otel_logging_handler = await loop.run_in_executor(
                None, setup_otel_logging, email_hash, hass_id
            )
            api_logger.addHandler(otel_logging_handler)

            _LOGGER.info(
                f"Telemetry enabled: Account hash {email_hash}, HA ID {hass_id}"
            )
        elif not no_telemetry and not _has_opentelemetry:
            _LOGGER.warning(
                "Telemetrie je povolena, ale OpenTelemetry není nainstalován. Telemetrie bude vypnuta."
            )

        oig_api = OigCloudApi(username, password, no_telemetry, hass)

        _LOGGER.debug("Authenticating with OIG Cloud")
        await oig_api.authenticate()

        hass.data[DOMAIN][entry.entry_id] = {
            "api": oig_api,
            "standard_scan_interval": standard_scan_interval,
            "extended_scan_interval": extended_scan_interval,
        }

        await hass.config_entries.async_forward_entry_setups(
            entry, ["sensor", "binary_sensor"]
        )
        await async_setup_entry_services(hass, entry)

        # Přidáme listener pro změny konfigurace
        entry.async_on_unload(entry.add_update_listener(async_update_options))

        _LOGGER.debug("OIG Cloud integration setup complete")
        return True

    except Exception as e:
        _LOGGER.error(f"Error initializing OIG Cloud: {e}", exc_info=True)
        raise ConfigEntryNotReady(f"Error initializing OIG Cloud: {e}") from e


async def async_update_options(
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry
) -> None:
    """Update options."""
    _LOGGER.info("Config options updated, reloading integration")
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
    await hass.config_entries.async_unload_platforms(entry, ["sensor", "binary_sensor"])
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True


async def async_reload_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
    """Reload OIG Cloud config entry when options are updated."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
