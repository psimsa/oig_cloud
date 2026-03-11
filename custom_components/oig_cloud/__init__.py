"""The OIG Cloud integration."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict

try:
    from homeassistant import config_entries, core
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import Platform
    from homeassistant.core import HomeAssistant
    from homeassistant.exceptions import ConfigEntryNotReady
    from homeassistant.helpers import config_validation as cv
except ModuleNotFoundError:  # pragma: no cover
    # Allow importing submodules (e.g., planner) outside a Home Assistant runtime.
    config_entries = None  # type: ignore[assignment]
    core = None  # type: ignore[assignment]
    ConfigEntry = Any  # type: ignore[misc,assignment]
    Platform = Any  # type: ignore[misc,assignment]
    HomeAssistant = Any  # type: ignore[misc,assignment]
    ConfigEntryNotReady = Exception  # type: ignore[assignment]

    class _CvStub:  # pragma: no cover - only used outside HA
        @staticmethod
        def config_entry_only_config_schema(_domain: str) -> object:
            return object()

    cv = _CvStub()  # type: ignore[assignment]

try:
    from .lib.oig_cloud_client.api.oig_cloud_api import OigCloudApi
except ModuleNotFoundError:  # pragma: no cover
    # Allow importing submodules outside HA / without runtime deps.
    OigCloudApi = Any  # type: ignore[misc,assignment]
from .const import (
    CONF_AUTO_MODE_SWITCH,
    CONF_EXTENDED_SCAN_INTERVAL,
    CONF_NO_TELEMETRY,
    CONF_PASSWORD,
    CONF_STANDARD_SCAN_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)

try:
    from .core.coordinator import OigCloudCoordinator
    from .core.data_source import (
        DATA_SOURCE_CLOUD_ONLY,
        DEFAULT_DATA_SOURCE_MODE,
        DEFAULT_LOCAL_EVENT_DEBOUNCE_MS,
        DEFAULT_PROXY_STALE_MINUTES,
        DataSourceController,
        get_data_source_state,
        init_data_source_state,
    )
except ModuleNotFoundError:  # pragma: no cover
    OigCloudCoordinator = Any  # type: ignore[misc,assignment]
    DataSourceController = Any  # type: ignore[misc,assignment]
    DATA_SOURCE_CLOUD_ONLY = "cloud_only"
    DEFAULT_DATA_SOURCE_MODE = "cloud_only"
    DEFAULT_PROXY_STALE_MINUTES = 15
    DEFAULT_LOCAL_EVENT_DEBOUNCE_MS = 250

    def get_data_source_state(*_args: Any, **_kwargs: Any) -> Any:  # type: ignore[misc]
        return None

    def init_data_source_state(*_args: Any, **_kwargs: Any) -> Any:  # type: ignore[misc]
        return None


# OPRAVA: Bezpečný import BalancingManager s try/except
try:
    from .battery_forecast.balancing import BalancingManager

    _LOGGER_TEMP = logging.getLogger(__name__)
    _LOGGER_TEMP.debug("oig_cloud: BalancingManager import OK")
except Exception as err:
    BalancingManager = None
    _LOGGER_TEMP = logging.getLogger(__name__)
    _LOGGER_TEMP.error(
        "oig_cloud: Failed to import BalancingManager: %s", err, exc_info=True
    )

_LOGGER = logging.getLogger(__name__)

if config_entries is None:  # pragma: no cover
    PLATFORMS = []
else:
    PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# OPRAVA: Definujeme všechny možné box modes pro konzistenci
ALL_BOX_MODES = ["Home 1", "Home 2", "Home 3", "Home UPS", "Home 5", "Home 6"]


def _read_manifest_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _ensure_data_source_option_defaults(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    defaults = {
        "data_source_mode": DEFAULT_DATA_SOURCE_MODE,
        "local_proxy_stale_minutes": DEFAULT_PROXY_STALE_MINUTES,
        "local_event_debounce_ms": DEFAULT_LOCAL_EVENT_DEBOUNCE_MS,
    }

    options = dict(entry.options)
    updated = False
    for key, default in defaults.items():
        if options.get(key) is None:
            options[key] = default
            updated = True

    if updated:
        hass.config_entries.async_update_entry(entry, options=options)


def _infer_box_id_from_local_entities(hass: HomeAssistant) -> str | None:
    """Best-effort inference of box_id from existing oig_local entity_ids.

    Expected local entity_id pattern: sensor.oig_local_<box_id>_<suffix>
    """
    try:
        from homeassistant.helpers import entity_registry as er

        reg = er.async_get(hass)
        ids: set[str] = set()
        pat = re.compile(r"^sensor\\.oig_local_(\\d+)_")
        for ent in reg.entities.values():
            m = pat.match(ent.entity_id)
            if m:
                ids.add(m.group(1))
        if len(ids) == 1:
            return next(iter(ids))
        return None
    except Exception:
        return None


def _ensure_planner_option_defaults(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ensure planner-related options exist on legacy config entries.

    Legacy multi-planner options were removed; only the single planner is supported.
    """

    defaults = {
        CONF_AUTO_MODE_SWITCH: False,
        # Planner parameters (percentages are of max capacity).
        "min_capacity_percent": 33.0,
        "target_capacity_percent": 80.0,
        # Hard cap for UPS charging (CZK/kWh).
        "max_ups_price_czk": 10.0,
        # AC charging power (kW) used for UPS mode simulation.
        "home_charge_rate": 2.8,
        # Used by balancer window selection.
        "cheap_window_percentile": 30,
    }

    options = dict(entry.options)
    # Migrate and purge removed/obsolete planner options.
    obsolete_keys = {
        "enable_cheap_window_ups",
        "cheap_window_max_intervals",
        "cheap_window_soc_guard_kwh",
        "enable_economic_charging",
        "min_savings_margin",
        "safety_margin_percent",
        "percentile_conf",
    }

    if "max_price_conf" in options and "max_ups_price_czk" not in options:
        try:
            options["max_ups_price_czk"] = float(options.get("max_price_conf", 10.0))
        except Exception:
            options["max_ups_price_czk"] = defaults["max_ups_price_czk"]
        options.pop("max_price_conf", None)

    removed = [k for k in list(options.keys()) if k in obsolete_keys]
    for k in removed:
        options.pop(k, None)

    missing_keys = [key for key in defaults.keys() if entry.options.get(key) is None]
    updated = False

    for key, default in defaults.items():
        if options.get(key) is None:
            options[key] = default
            updated = True

    if updated or removed:
        _LOGGER.info(
            "🔧 Injecting missing planner options for entry %s: %s",
            entry.entry_id,
            ", ".join(missing_keys) if missing_keys else "none",
        )
        hass.config_entries.async_update_entry(entry, options=options)


async def async_setup(hass: HomeAssistant, config: Dict[str, Any]) -> bool:
    """Set up OIG Cloud integration."""
    _ = config
    _LOGGER.debug("OIG Cloud setup: starting")

    # OPRAVA: Odstraníme neexistující import setup_telemetry
    # Initialize telemetry - telemetrie se inicializuje přímo v ServiceShield
    _LOGGER.debug("OIG Cloud setup: telemetry will be initialized in ServiceShield")

    # OPRAVA: ServiceShield se inicializuje pouze v async_setup_entry, ne zde
    # V async_setup pouze připravíme globální strukturu
    hass.data.setdefault(DOMAIN, {})
    _LOGGER.debug("OIG Cloud setup: global data structure prepared")

    # OPRAVA: Univerzální registrace statických cest pro všechny verze HA
    await _register_static_paths(hass)

    # OPRAVA: Odstranění volání _setup_frontend_panel z async_setup
    # Panel se registruje až v async_setup_entry kde máme přístup k entry
    # await _setup_frontend_panel(hass)  # ODSTRANĚNO

    _LOGGER.debug("OIG Cloud setup: completed")
    return True


async def _register_static_paths(hass: HomeAssistant) -> None:
    """Registrace statických cest pro HA 2024.5+."""
    static_path = "/oig_cloud_static"
    directory = hass.config.path("custom_components/oig_cloud/www")

    _LOGGER.info("Registering static path: %s -> %s", static_path, directory)

    # OPRAVA: Pouze moderní metoda
    from homeassistant.components.http import StaticPathConfig

    static_config = StaticPathConfig(static_path, directory, cache_headers=False)
    await hass.http.async_register_static_paths([static_config])
    _LOGGER.info("✅ Static paths registered successfully")


async def _setup_frontend_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Nastavení frontend panelu (pouze když je povolen)."""
    try:
        # Unikátní ID panelu pro tuto instanci
        panel_id = f"oig_cloud_dashboard_{entry.entry_id}"

        # OPRAVA: inverter_sn musí být numerické box_id (nikdy ne helper klíče jako "spot_prices")
        inverter_sn = None
        try:
            opt_box = entry.options.get("box_id")
            if isinstance(opt_box, str) and opt_box.isdigit():
                inverter_sn = opt_box
        except Exception:
            inverter_sn = None

        coordinator_data = (
            hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("coordinator")
        )
        if inverter_sn is None and coordinator_data:
            try:
                from .entities.base_sensor import resolve_box_id

                resolved = resolve_box_id(coordinator_data)
                if isinstance(resolved, str) and resolved.isdigit():
                    inverter_sn = resolved
            except Exception:
                inverter_sn = None

        if inverter_sn is None:
            inverter_sn = "unknown"
            _LOGGER.warning(
                "Dashboard setup: Unable to resolve numeric inverter_sn/box_id, using 'unknown'"
            )
        else:
            _LOGGER.info("Dashboard setup: Using inverter_sn = %s", inverter_sn)

        panel_title = (
            f"OIG Dashboard ({inverter_sn})"
            if inverter_sn != "unknown"
            else "OIG Cloud Dashboard"
        )

        # Cache-busting: Přidat verzi + timestamp k URL pro vymazání browseru cache
        import json
        import os
        import time

        manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
        version = "unknown"
        try:
            # OPRAVA: Použít async file read místo blocking open()
            manifest_data = await hass.async_add_executor_job(
                _read_manifest_file, manifest_path
            )
            manifest = json.loads(manifest_data)
            version = manifest.get("version", "unknown")
        except Exception as e:
            _LOGGER.warning("Could not load version from manifest: %s", e)

        # Přidat timestamp pro cache-busting při každém restartu
        cache_bust = int(time.time())

        # OPRAVA: Přidat parametry včetně v= a t= pro cache-busting
        dashboard_url = f"/oig_cloud_static/dashboard.html?entry_id={entry.entry_id}&inverter_sn={inverter_sn}&v={version}&t={cache_bust}"

        _LOGGER.info("Dashboard URL: %s", dashboard_url)

        from homeassistant.components import frontend

        # Prevent reload errors ("Overwriting panel ...") by removing any existing panel first.
        if hasattr(frontend, "async_remove_panel") and callable(
            getattr(frontend, "async_remove_panel")
        ):
            try:
                frontend.async_remove_panel(hass, panel_id, warn_if_unknown=False)
            except Exception as err:
                try:
                    frontend.async_remove_panel(hass, panel_id)
                except Exception as fallback_err:
                    _LOGGER.debug(
                        "Failed to remove panel %s: %s (fallback: %s)",
                        panel_id,
                        err,
                        fallback_err,
                    )

        # OPRAVA: Kontrola existence funkce a její volání bez await pokud vrací None
        if hasattr(frontend, "async_register_built_in_panel"):
            register_func = getattr(frontend, "async_register_built_in_panel")
            if callable(register_func):
                try:
                    # OPRAVA: Použít keyword argumenty pro správné volání
                    # Signature: (hass, component_name, sidebar_title, sidebar_icon,
                    #             sidebar_default_visible, frontend_url_path, config, require_admin)
                    result = register_func(
                        hass,
                        "iframe",  # component_name
                        sidebar_title=panel_title,
                        sidebar_icon="mdi:solar-power",
                        frontend_url_path=panel_id,
                        config={"url": dashboard_url},
                        require_admin=False,
                    )

                    # Pokud funkce vrací coroutine, await it
                    if hasattr(result, "__await__"):
                        await result

                    _LOGGER.info("✅ Panel '%s' registered successfully", panel_title)
                except Exception as reg_error:
                    _LOGGER.error("Error during panel registration: %s", reg_error)
                    raise
            else:
                _LOGGER.warning("async_register_built_in_panel is not callable")
        else:
            _LOGGER.warning("Frontend async_register_built_in_panel not available")

        # OPRAVA: Debug logování dostupných entit
        coordinator = hass.data[DOMAIN][entry.entry_id].get("coordinator")
        if coordinator and coordinator.data:
            entity_count = len(
                [
                    k
                    for k in hass.states.async_entity_ids()
                    if k.startswith(f"sensor.oig_{inverter_sn}")
                ]
            )
            _LOGGER.info(
                f"Dashboard: Found {entity_count} OIG entities for inverter {inverter_sn}"
            )

            # Kontrola klíčových entit (pouze pokud jsou zapnuté v konfiguraci)
            key_entities = [
                f"sensor.oig_{inverter_sn}_remaining_usable_capacity",  # vždy
            ]

            # Přidat solar_forecast pouze pokud je zapnutý
            if entry.options.get("enable_solar_forecast", False):
                key_entities.append(f"sensor.oig_{inverter_sn}_solar_forecast")

            # Přidat battery_forecast pouze pokud je zapnutý
            if entry.options.get("enable_battery_prediction", False):
                key_entities.append(f"sensor.oig_{inverter_sn}_battery_forecast")

            for entity_id in key_entities:
                entity_state = hass.states.get(entity_id)
                if entity_state:
                    _LOGGER.debug(
                        f"Dashboard entity check: {entity_id} = {entity_state.state}"
                    )
                else:
                    # DEBUG místo WARNING - entity může chybět při startu (timing issue)
                    _LOGGER.debug("Dashboard entity not yet available: %s", entity_id)
        else:
            _LOGGER.warning("Dashboard: No coordinator data for entity checking")

    except Exception as e:
        _LOGGER.error("Failed to setup frontend panel: %s", e)


async def _remove_frontend_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Odebrání frontend panelu."""
    try:
        panel_id = f"oig_cloud_dashboard_{entry.entry_id}"

        from homeassistant.components import frontend

        # Pokus o odebrání panelu
        if hasattr(frontend, "async_remove_panel") and callable(
            getattr(frontend, "async_remove_panel")
        ):
            try:
                frontend.async_remove_panel(hass, panel_id, warn_if_unknown=False)
                _LOGGER.info("✅ Panel removed: %s", panel_id)
            except ValueError as ve:
                if "unknown panel" in str(ve).lower():
                    _LOGGER.debug(
                        f"Panel {panel_id} was already removed or never existed"
                    )
                else:
                    _LOGGER.warning("Error removing panel %s: {ve}", panel_id)
            except Exception as re:
                try:
                    frontend.async_remove_panel(hass, panel_id)
                except Exception:
                    _LOGGER.debug("Panel removal handled (panel may not exist): %s", re)
        else:
            _LOGGER.debug("async_remove_panel not available")

    except Exception as e:
        # OPRAVA: Všechny chyby logujeme jako debug, protože jsou očekávané
        _LOGGER.debug("Panel removal handled gracefully: %s", e)


async def _migrate_entity_unique_ids(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:  # noqa: C901
    """Migrace unique_id a cleanup duplicitních entit s _2, _3, atd."""
    _LOGGER.info("🔍 Starting _migrate_entity_unique_ids function...")
    import re

    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)

    # Najdeme všechny OIG entity pro tento config entry
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    _LOGGER.info(f"📊 Found {len(entities)} entities for config entry")

    migrated_count = 0
    skipped_count = 0
    removed_count = 0
    enabled_count = 0
    renamed_count = 0

    # Projdeme všechny entity a upravíme je
    for entity in entities:
        old_unique_id = entity.unique_id
        entity_id = entity.entity_id
        duplicate_pattern = re.compile(r"^(.+?)(_\d+)$")

        # OPRAVA: Přeskočit bojler senzory - mají vlastní formát unique_id bez oig_cloud_ prefixu
        # Formát: {entry_id}_boiler_{sensor_type}
        if "_boiler_" in old_unique_id:
            skipped_count += 1
            _LOGGER.debug("Skipping boiler sensor (correct format): %s", entity_id)
            continue

        # 1. Pokud má entita správný formát unique_id (oig_cloud_*):
        if old_unique_id.startswith("oig_cloud_"):
            # Zkontrolujeme, jestli entity_id má příponu, ale unique_id ne
            entity_id_match = duplicate_pattern.match(entity_id)
            if entity_id_match:
                suffix = entity_id_match.group(2)
                base_entity_id = entity_id_match.group(1)

                # Pokud unique_id nemá příponu, ale entity_id ano, přejmenujeme
                if not old_unique_id.endswith(suffix):
                    try:
                        # Zkusíme přejmenovat entity_id (odstraníme příponu)
                        entity_registry.async_update_entity(
                            entity_id, new_entity_id=base_entity_id
                        )
                        renamed_count += 1
                        _LOGGER.info(
                            f"🔄 Renamed entity: {entity_id} -> {base_entity_id}"
                        )
                        entity_id = base_entity_id  # Aktualizujeme pro další kontroly
                    except Exception:
                        _LOGGER.warning("⚠️ Failed to rename %s: {e}", entity_id)

            # Pokud je disabled, enable ji
            if entity.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
                try:
                    entity_registry.async_update_entity(entity_id, disabled_by=None)
                    enabled_count += 1
                    _LOGGER.info("✅ Re-enabled correct entity: %s", entity_id)
                except Exception:
                    _LOGGER.warning("⚠️ Failed to enable %s: {e}", entity_id)

            skipped_count += 1
            continue

        # 2. Má starý formát unique_id - potřebuje migraci
        # Zjistíme, jestli entity_id má příponu _X (znamená duplicitu)
        entity_id_match = duplicate_pattern.match(entity_id)

        if entity_id_match:
            suffix = entity_id_match.group(2)  # např. "_2", "_3"

            # Pokud unique_id nemá příponu, ale entity_id ano = duplicita
            # Tyto entity SMAŽEME (ne jen disable)
            if not old_unique_id.endswith(suffix):
                try:
                    entity_registry.async_remove(entity_id)
                    removed_count += 1
                    _LOGGER.info(
                        f"🗑️ Removed duplicate entity: {entity_id} "
                        f"(unique_id={old_unique_id} doesn't match entity_id suffix)"
                    )
                    continue
                except Exception:
                    _LOGGER.warning("⚠️ Failed to remove %s: {e}", entity_id)
                    continue

        # 3. Migrace unique_id na nový formát
        if old_unique_id.startswith("oig_") and not old_unique_id.startswith(
            "oig_cloud_"
        ):
            # Formát oig_{boxId}_{sensor} -> oig_cloud_{boxId}_{sensor}
            new_unique_id = f"oig_cloud_{old_unique_id[4:]}"
        else:
            # Formát {boxId}_{sensor} -> oig_cloud_{boxId}_{sensor}
            new_unique_id = f"oig_cloud_{old_unique_id}"

        try:
            entity_registry.async_update_entity(entity_id, new_unique_id=new_unique_id)
            migrated_count += 1
            _LOGGER.info(
                f"✅ Migrated entity {entity_id}: {old_unique_id} -> {new_unique_id}"
            )
        except Exception:
            _LOGGER.warning("⚠️ Failed to migrate %s: {e}", entity_id)

        # Přeskočíme entity, které už mají správný formát
        if old_unique_id.startswith("oig_cloud_"):
            skipped_count += 1
            continue

        # Migrace formátů unique_id
        if old_unique_id.startswith("oig_") and not old_unique_id.startswith(
            "oig_cloud_"
        ):
            # Formát oig_{boxId}_{sensor} -> oig_cloud_{boxId}_{sensor}
            new_unique_id = f"oig_cloud_{old_unique_id[4:]}"
        else:
            # Formát {boxId}_{sensor} -> oig_cloud_{boxId}_{sensor}
            new_unique_id = f"oig_cloud_{old_unique_id}"

        try:
            entity_registry.async_update_entity(
                entity.entity_id, new_unique_id=new_unique_id
            )
            migrated_count += 1
            _LOGGER.info(
                f"✅ Migrated entity {entity.entity_id}: {old_unique_id} -> {new_unique_id}"
            )
        except Exception:
            _LOGGER.warning("⚠️ Failed to migrate %s: {e}", entity_id)

    # Summary
    _LOGGER.info(
        f"📊 Migration summary: migrated={migrated_count}, removed={removed_count}, "
        f"renamed={renamed_count}, enabled={enabled_count}, skipped={skipped_count}"
    )

    if removed_count > 0 or migrated_count > 0 or renamed_count > 0:
        message_parts = []

        if renamed_count > 0:
            message_parts.append(
                f"**Přejmenováno {renamed_count} entit**\n"
                f"Entity s příponami (_2, _3) byly přejmenovány na správné názvy.\n\n"
            )

        if removed_count > 0:
            message_parts.append(
                f"**Odstraněno {removed_count} duplicitních entit**\n"
                f"Byly to staré kolize s nesprávným unique_id.\n\n"
            )

        if migrated_count > 0:
            message_parts.append(
                f"**Migrováno {migrated_count} entit na nový formát unique_id**\n"
                f"Všechny OIG entity nyní používají standardní formát `oig_cloud_*`.\n\n"
            )

        if enabled_count > 0:
            message_parts.append(
                f"**Povoleno {enabled_count} správných entit**\n"
                f"Entity s novým formátem byly znovu aktivovány.\n\n"
            )

        message_parts.append(
            "**Co se stalo:**\n"
            "- Staré entity se přeregistrovaly s novým unique_id\n"
            "- Duplicity byly odstraněny\n"
            "- Všechny entity by měly fungovat normálně\n\n"
            "**Pokud něco nefunguje:**\n"
            "Reload integrace v Nastavení → Zařízení & Služby → OIG Cloud\n\n"
            "Toto je jednorázová migrace po aktualizaci integrace."
        )

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "OIG Cloud: Migrace entit dokončena",
                "message": "".join(message_parts),
                "notification_id": "oig_cloud_migration_complete",
            },
        )

    if renamed_count > 0:
        _LOGGER.info("🔄 Renamed %s entities to correct entity_id", renamed_count)
    if migrated_count > 0:
        _LOGGER.info("🔄 Migrated %s entities to new unique_id format", migrated_count)
    if removed_count > 0:
        _LOGGER.warning("🗑️ Removed %s duplicate entities", removed_count)
    if enabled_count > 0:
        _LOGGER.info("✅ Re-enabled %s correct entities", enabled_count)
    if skipped_count > 0:
        _LOGGER.debug(
            "⏭️ Skipped %s entities (already in correct format)", skipped_count
        )


async def _cleanup_invalid_empty_devices(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove clearly-invalid devices (e.g., 'spot_prices', 'unknown') with no entities.

    This is a targeted/safe cleanup to get rid of stale registry entries created by
    older versions when box_id resolution was unstable.
    """
    try:
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)

        def _strip_known_suffixes(value: str) -> str:
            for suffix in ("_analytics", "_shield"):
                if value.endswith(suffix):
                    return value[: -len(suffix)]
            return value

        # Non-numeric identifiers used by this integration that are still valid.
        allowlisted_bases = {"oig_bojler"}

        devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
        removed: list[str] = []

        for device in devices:
            # Never remove devices that still have entities.
            if er.async_entries_for_device(entity_registry, device.id):
                continue

            id_values = [
                identifier[1]
                for identifier in device.identifiers
                if identifier and identifier[0] == DOMAIN and len(identifier) > 1
            ]
            if not id_values:
                continue

            bases = {_strip_known_suffixes(v) for v in id_values if isinstance(v, str)}
            if not bases:
                continue

            if any(base in allowlisted_bases for base in bases):
                continue

            # If every base is numeric, the device id is valid.
            if all(isinstance(base, str) and base.isdigit() for base in bases):
                continue

            device_registry.async_remove_device(device.id)
            removed.append(device.name or device.id)

        if removed:
            _LOGGER.info(
                "Removed %d stale OIG devices without entities: %s",
                len(removed),
                ", ".join(removed),
            )
    except Exception as err:
        _LOGGER.debug("Device registry cleanup failed (non-critical): %s", err)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:  # noqa: C901
    """Set up OIG Cloud from a config entry."""
    _LOGGER.info("oig_cloud: async_setup_entry started for entry_id=%s", entry.entry_id)
    _LOGGER.info(f"Setting up OIG Cloud entry: {entry.title}")
    _LOGGER.debug(f"Config data keys: {list(entry.data.keys())}")
    _LOGGER.debug(f"Config options keys: {list(entry.options.keys())}")

    # Inject defaults for new planner/autonomy options so legacy setups keep working
    _ensure_planner_option_defaults(hass, entry)
    _ensure_data_source_option_defaults(hass, entry)

    # MIGRACE 1: enable_spot_prices -> enable_pricing
    if "enable_spot_prices" in entry.options:
        _LOGGER.info("🔄 Migrating enable_spot_prices to enable_pricing")
        new_options = dict(entry.options)

        # Pokud enable_spot_prices byl True, zapneme enable_pricing
        if new_options.get("enable_spot_prices", False):
            new_options["enable_pricing"] = True
            _LOGGER.info("✅ Migrated: enable_spot_prices=True -> enable_pricing=True")

        # Odstraníme starý flag
        new_options.pop("enable_spot_prices", None)

        # Aktualizujeme entry
        hass.config_entries.async_update_entry(entry, options=new_options)
        _LOGGER.info("✅ Migration completed - enable_spot_prices removed from config")

    # POZN: Automatická migrace entity/device registry při startu je riziková (může mazat/rozbíjet entity).
    # Pokud je potřeba cleanup/migrace, dělejme ji explicitně (script / servis), ne automaticky v setupu.

    # Inicializace hass.data struktury pro tento entry PŘED použitím
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})

    # Initialize data source state early so coordinator setup can respect local/hybrid modes.
    # Also try to infer box_id from local entities so local mapping works without cloud.
    init_data_source_state(hass, entry)
    try:
        options = dict(entry.options)
        if not options.get("box_id"):
            # Prefer explicit proxy box id sensor (most reliable)
            proxy_box = hass.states.get(
                "sensor.oig_local_oig_proxy_proxy_status_box_device_id"
            )
            if (
                proxy_box
                and isinstance(proxy_box.state, str)
                and proxy_box.state.isdigit()
            ):
                options["box_id"] = proxy_box.state
                hass.config_entries.async_update_entry(entry, options=options)
                _LOGGER.info("Inferred box_id=%s from proxy sensor", proxy_box.state)
            else:
                inferred = _infer_box_id_from_local_entities(hass)
                if inferred:
                    options["box_id"] = inferred
                    hass.config_entries.async_update_entry(entry, options=options)
                    _LOGGER.info("Inferred box_id=%s from local entities", inferred)
    except Exception as err:
        _LOGGER.debug(
            "Inferring box_id from local entities failed (non-critical): %s", err
        )

    # OPRAVA: Inicializujeme service_shield jako None před try blokem
    service_shield = None

    try:
        # Inicializujeme ServiceShield s entry parametrem
        from .shield.core import ServiceShield

        service_shield = ServiceShield(hass, entry)
        await service_shield.start()

        hass.data[DOMAIN][entry.entry_id]["service_shield"] = service_shield

        _LOGGER.info("ServiceShield inicializován a spuštěn")
    except Exception as e:
        _LOGGER.error("ServiceShield není dostupný - obecná chyba: %s", e)
        # Pokračujeme bez ServiceShield
        hass.data[DOMAIN][entry.entry_id]["service_shield"] = None
        # OPRAVA: Ujistíme se, že service_shield je None
        service_shield = None

    try:
        # Načtení konfigurace z entry.data nebo entry.options
        username = entry.data.get(CONF_USERNAME) or entry.options.get(CONF_USERNAME)
        password = entry.data.get(CONF_PASSWORD) or entry.options.get(CONF_PASSWORD)

        # Debug log pro diagnostiku
        _LOGGER.debug(f"Username: {'***' if username else 'MISSING'}")
        _LOGGER.debug(f"Password: {'***' if password else 'MISSING'}")

        if not username or not password:
            _LOGGER.error("Username or password is missing from configuration")
            return False

        no_telemetry = entry.data.get(CONF_NO_TELEMETRY, False) or entry.options.get(
            CONF_NO_TELEMETRY, False
        )

        # OPRAVA: Preferuj options před data, jen pokud options neexistují, použij data nebo default
        standard_scan_interval = entry.options.get(
            "standard_scan_interval"
        ) or entry.data.get(CONF_STANDARD_SCAN_INTERVAL, 30)
        extended_scan_interval = entry.options.get(
            "extended_scan_interval"
        ) or entry.data.get(CONF_EXTENDED_SCAN_INTERVAL, 300)

        _LOGGER.debug(
            f"Using intervals: standard={standard_scan_interval}s, extended={extended_scan_interval}s"
        )

        # DEBUG: DOČASNĚ ZAKÁZAT telemetrii kvůli problémům s výkonem
        # OPRAVA: Telemetrie způsobovala nekonečnou smyčku
        # if not no_telemetry:
        #     _LOGGER.debug("Telemetry enabled, setting up...")
        #     await _setup_telemetry(hass, username)
        # else:
        #     _LOGGER.debug("Telemetry disabled by configuration")

        _LOGGER.debug("Telemetry handled only by ServiceShield, not main module")

        # NOVÉ: Vytvoření OigCloudApi a zabalení do SessionManageru
        oig_api = OigCloudApi(username, password, no_telemetry)

        _LOGGER.debug("Creating session manager wrapper")
        from .api.oig_cloud_session_manager import OigCloudSessionManager

        session_manager = OigCloudSessionManager(oig_api)

        # Respect local/hybrid mode: if local proxy is healthy, do not hit cloud during setup.
        # Session manager will authenticate on-demand if we later fall back to cloud.
        state = get_data_source_state(hass, entry.entry_id)
        should_check_cloud_now = state.effective_mode == DATA_SOURCE_CLOUD_ONLY

        if should_check_cloud_now:
            _LOGGER.debug("Initial authentication via session manager")
            # Session manager zavolá authenticate() při prvním požadavku,
            # ale provedeme to i zde pro kontrolu přihlašovacích údajů
            await session_manager._ensure_auth()

            # CRITICAL: Check if live data is enabled (actual element present in API response)
            # Stats structure: { "box_id": { "actual": {...}, "settings": {...} } }
            _LOGGER.debug(
                "Kontrola, zda jsou v aplikaci OIG Cloud zapnutá 'Živá data'..."
            )
            try:
                test_stats = await oig_api.get_stats()
                if test_stats:
                    # Get first device data
                    first_device = (
                        next(iter(test_stats.values())) if test_stats else None
                    )
                    if not first_device or "actual" not in first_device:
                        _LOGGER.error(
                            "❌ KRITICKÁ CHYBA: V aplikaci OIG Cloud nejsou zapnutá 'Živá data'! "
                            "API odpověď neobsahuje element 'actual'. "
                            "Uživatel musí v mobilní aplikaci zapnout: Nastavení → Přístup k datům → Živá data"
                        )
                        raise ConfigEntryNotReady(
                            "V aplikaci OIG Cloud nejsou zapnutá 'Živá data'. "
                            "Zapněte je v mobilní aplikaci OIG Cloud (Nastavení → Přístup k datům → Živá data) "
                            "a restartujte Home Assistant."
                        )
                    _LOGGER.info(
                        "✅ Kontrola živých dat úspěšná - element 'actual' nalezen v API odpovědi"
                    )
                else:
                    _LOGGER.warning(
                        "API vrátilo prázdnou odpověď, přeskakuji kontrolu živých dat"
                    )
            except ConfigEntryNotReady:
                raise
            except Exception as e:
                _LOGGER.warning("Nelze ověřit stav živých dat: %s", e)
                # Pokračujeme i tak - může jít o dočasný problém s API
        else:
            _LOGGER.info(
                "Local telemetry mode active (configured=%s, local_ok=%s) – skipping initial cloud authentication and live-data check",
                state.configured_mode,
                state.local_available,
            )

        # Inicializace koordinátoru - použijeme session_manager.api (wrapper)
        coordinator = OigCloudCoordinator(
            hass, session_manager, standard_scan_interval, extended_scan_interval, entry
        )

        # OPRAVA: Počkej na první data před vytvořením senzorů
        _LOGGER.debug("Waiting for initial coordinator data...")
        await coordinator.async_config_entry_first_refresh()

        if coordinator.data is None:
            _LOGGER.error("Failed to get initial data from coordinator")
            raise ConfigEntryNotReady("No data received from OIG Cloud API")

        _LOGGER.debug(f"Coordinator data received: {len(coordinator.data)} devices")

        # Persist box_id once so sensors can be initialized without relying on coordinator.data order
        try:
            options = dict(entry.options)
            if not options.get("box_id") and coordinator.data:
                box_id = next(
                    (str(k) for k in coordinator.data.keys() if str(k).isdigit()),
                    None,
                )
                if box_id:
                    options["box_id"] = box_id
                    hass.config_entries.async_update_entry(entry, options=options)
                    _LOGGER.info(
                        "Persisted box_id=%s into config entry options", box_id
                    )
        except Exception as err:
            _LOGGER.debug("Persisting box_id failed (non-critical): %s", err)

        # OPRAVA: Inicializace notification manageru se správným error handling
        notification_manager = None
        enable_cloud_notifications = entry.options.get(
            "enable_cloud_notifications", True
        )
        cloud_active_for_setup = (
            get_data_source_state(hass, entry.entry_id).effective_mode
            == DATA_SOURCE_CLOUD_ONLY
        )
        if enable_cloud_notifications and cloud_active_for_setup:
            try:
                _LOGGER.debug("Initializing notification manager...")
                from .core.oig_cloud_notification import OigNotificationManager

                # PROBLÉM: Ověříme, že používáme správný objekt
                _LOGGER.debug(f"Using API object: {type(oig_api)}")
                _LOGGER.debug(
                    f"API has get_notifications: {hasattr(oig_api, 'get_notifications')}"
                )

                # OPRAVA: Použít oig_api objekt (OigCloudApi) místo jakéhokoliv jiného
                # NOVÉ: Použít session_manager.api pro přístup k underlying API
                notification_manager = OigNotificationManager(
                    hass, session_manager.api, "https://portal.oigpower.cz/"
                )

                # Nastavíme device_id deterministicky (numerický box_id)
                device_id = None
                try:
                    opt_box = entry.options.get("box_id")
                    if isinstance(opt_box, str) and opt_box.isdigit():
                        device_id = opt_box
                except Exception:
                    device_id = None
                if (
                    device_id is None
                    and coordinator.data
                    and isinstance(coordinator.data, dict)
                ):
                    device_id = next(
                        (str(k) for k in coordinator.data.keys() if str(k).isdigit()),
                        None,
                    )
                if device_id:
                    notification_manager.set_device_id(device_id)
                    _LOGGER.debug(
                        "Set notification manager device_id to: %s", device_id
                    )

                    # Inicializace Mode Transition Tracker
                    if service_shield:
                        try:
                            from .shield.core import ModeTransitionTracker

                            service_shield.mode_tracker = ModeTransitionTracker(
                                hass, device_id
                            )
                            await service_shield.mode_tracker.async_setup()
                            _LOGGER.info(
                                f"Mode Transition Tracker inicializován pro box {device_id}"
                            )
                        except Exception as tracker_error:
                            _LOGGER.warning(
                                f"Failed to initialize Mode Transition Tracker: {tracker_error}"
                            )
                            # Pokračujeme bez trackeru

                    # OPRAVA: Použít nový API přístup místo fetch_notifications_and_status
                    try:
                        await notification_manager.update_from_api()
                        _LOGGER.debug("Initial notification data loaded successfully")
                    except Exception as fetch_error:
                        _LOGGER.warning(
                            f"Failed to fetch initial notifications (API endpoint may not exist): {fetch_error}"
                        )
                        # Pokračujeme bez počátečních notifikací - API endpoint možná neexistuje

                    # Připoj notification manager ke koordinátoru i když fetch selhal
                    # Manager může fungovat později pokud se API opraví
                    coordinator.notification_manager = notification_manager
                    _LOGGER.info(
                        "Notification manager created and attached to coordinator (may not have data yet)"
                    )
                else:
                    _LOGGER.warning(
                        "No device data available, notification manager not initialized"
                    )
                    notification_manager = None

            except Exception as e:
                _LOGGER.warning(
                    f"Failed to setup notification manager (API may not be available): {e}"
                )
                # Pokračujeme bez notification manageru - API endpoint možná neexistuje nebo je nedostupný
                notification_manager = None
        else:
            _LOGGER.debug(
                "Cloud notifications disabled or cloud not active - skipping notification manager"
            )

        # Inicializace solar forecast (pokud je povolená)
        solar_forecast = None
        if entry.options.get("enable_solar_forecast", False):
            try:
                _LOGGER.debug("Initializing solar forecast functionality")
                # Solar forecast se inicializuje přímo v sensorech, ne zde
                solar_forecast = {"enabled": True, "config": entry.options}
            except Exception as e:
                _LOGGER.error("Chyba při inicializaci solární předpovědi: %s", e)
                solar_forecast = {"enabled": False, "error": str(e)}

        # **OPRAVA: Správné nastavení statistics pro reload**
        statistics_enabled = entry.options.get("enable_statistics", True)
        _LOGGER.debug("Statistics enabled: %s", statistics_enabled)

        # Analytics device info (service device linked to the main box device)
        # NOTE: box_id musí být numerické a stabilní i v local_only režimu (bez cloud dat).
        try:
            from .entities.base_sensor import resolve_box_id

            box_id_for_devices = resolve_box_id(coordinator)
        except Exception:
            box_id_for_devices = entry.options.get("box_id")
        if not (isinstance(box_id_for_devices, str) and box_id_for_devices.isdigit()):
            box_id_for_devices = "unknown"

        analytics_device_info = {
            "identifiers": {(DOMAIN, f"{box_id_for_devices}_analytics")},
            "name": f"Analytics & Predictions {box_id_for_devices}",
            "manufacturer": "OIG",
            "model": "Analytics Module",
            "via_device": (DOMAIN, box_id_for_devices),
            "entry_type": "service",
        }

        # NOVÉ: Podpora pro OTE API a spotové ceny
        ote_api = None
        if entry.options.get("enable_pricing", False):
            try:
                _LOGGER.debug("Initializing OTE API for spot prices")
                from .api.ote_api import OteApi

                ote_api = OteApi()
                # OPRAVA: Odstraněno volání fetch_spot_prices - data už jsou v coordinatoru
                _LOGGER.info("OTE API successfully initialized")
            except Exception as e:
                _LOGGER.error("Failed to initialize OTE API: %s", e)
                if ote_api:
                    await ote_api.close()
                ote_api = None
        else:
            _LOGGER.debug("Pricing disabled - skipping OTE API initialization")

        # NOVÉ: Bojlerový modul (pokud je povolen)
        boiler_coordinator = None
        if entry.options.get("enable_boiler", False):
            try:
                _LOGGER.debug("Initializing Boiler module")
                from .boiler.coordinator import BoilerCoordinator

                # Kombinace entry.data a entry.options pro config
                boiler_config = {**entry.data, **entry.options}

                boiler_coordinator = BoilerCoordinator(hass, boiler_config)

                # První refresh
                await boiler_coordinator.async_config_entry_first_refresh()

                _LOGGER.info("Boiler coordinator successfully initialized")
            except Exception as e:
                _LOGGER.error("Failed to initialize Boiler coordinator: %s", e)
                boiler_coordinator = None
        else:
            _LOGGER.debug("Boiler module disabled")

        # NOVÉ: Podmíněné nastavení dashboard podle konfigurace
        dashboard_enabled = entry.options.get(
            "enable_dashboard", False
        )  # OPRAVA: default False místo True
        # OPRAVA: Dashboard registrujeme AŽ PO vytvoření senzorů

        # PHASE 3: Inicializace Balancing Manager (refactored - no physics)
        balancing_enabled = entry.options.get("balancing_enabled", True)
        _LOGGER.info("oig_cloud: balancing_enabled=%s", balancing_enabled)

        balancing_manager = None
        if balancing_enabled and BalancingManager is not None:
            try:
                _LOGGER.info("oig_cloud: Initializing BalancingManager")
                # Get box_id deterministicky (entry.options → coordinator numeric keys)
                box_id = None
                try:
                    opt_box = entry.options.get("box_id")
                    if isinstance(opt_box, str) and opt_box.isdigit():
                        box_id = opt_box
                except Exception:
                    box_id = None

                if (
                    box_id is None
                    and coordinator.data
                    and isinstance(coordinator.data, dict)
                ):
                    box_id = next(
                        (str(k) for k in coordinator.data.keys() if str(k).isdigit()),
                        None,
                    )

                if not box_id:
                    _LOGGER.warning(
                        "oig_cloud: No box_id available for BalancingManager"
                    )

                storage_path = hass.config.path(".storage")

                balancing_manager = BalancingManager(hass, box_id, storage_path, entry)
                await balancing_manager.async_setup()

                _LOGGER.info("oig_cloud: BalancingManager successfully initialized")

                # Periodické volání balancingu (check every 30min)
                from datetime import timedelta

                from homeassistant.helpers.event import (
                    async_call_later,
                    async_track_time_interval,
                )

                async def update_balancing(_now: Any) -> None:
                    """Periodická kontrola balancingu."""
                    _LOGGER.debug("BalancingManager: periodic check_balancing()")
                    try:
                        await balancing_manager.check_balancing()
                    except Exception as e:
                        _LOGGER.error(f"Error checking balancing: {e}", exc_info=True)

                # Aktualizace každých 30 minut
                entry.async_on_unload(
                    async_track_time_interval(
                        hass, update_balancing, timedelta(minutes=30)
                    )
                )

                # První volání hned při startu (po delay aby forecast měl čas se inicializovat)
                async def initial_balancing_check(_now: Any) -> None:
                    """Počáteční kontrola balancingu po startu."""
                    _LOGGER.debug("BalancingManager: initial check_balancing()")
                    try:
                        result = await balancing_manager.check_balancing()
                        if result:
                            _LOGGER.info(
                                f"✅ Initial check created plan: {result.mode.name}"
                            )
                        else:
                            _LOGGER.debug("Initial check: no plan needed yet")
                    except Exception as e:
                        _LOGGER.error(
                            f"Error in initial balancing check: {e}", exc_info=True
                        )

                # První kontrola za 2 minuty (aby forecast měl čas se inicializovat)
                async_call_later(hass, 120, initial_balancing_check)

            except Exception as err:
                _LOGGER.error(
                    "oig_cloud: Failed to initialize BalancingManager: %s",
                    err,
                    exc_info=True,
                )
                balancing_manager = None
        else:
            if not balancing_enabled:
                _LOGGER.info("oig_cloud: BalancingManager disabled via config options")
            if BalancingManager is None:
                _LOGGER.warning(
                    "oig_cloud: BalancingManager not available (import failed)"
                )

        # Uložení dat do hass.data
        # Local telemetry store (cloud-shaped payload for coordinator.data in local mode)
        telemetry_store = None
        try:
            from .core.telemetry_store import TelemetryStore
            from .entities.base_sensor import resolve_box_id

            store_box_id = entry.options.get("box_id") or entry.data.get("box_id")
            if not (isinstance(store_box_id, str) and store_box_id.isdigit()):
                store_box_id = resolve_box_id(coordinator)
            if isinstance(store_box_id, str) and store_box_id.isdigit():
                telemetry_store = TelemetryStore(hass, box_id=store_box_id)
                # Expose on coordinator for other modules (optional)
                setattr(coordinator, "telemetry_store", telemetry_store)
        except Exception:
            telemetry_store = None

        hass.data[DOMAIN][entry.entry_id] = {
            "coordinator": coordinator,
            "session_manager": session_manager,  # NOVÉ: Uložit session manager
            "notification_manager": notification_manager,
            "data_source_controller": None,
            "data_source_state": get_data_source_state(hass, entry.entry_id),
            "telemetry_store": telemetry_store,
            "solar_forecast": solar_forecast,
            "statistics_enabled": statistics_enabled,
            "analytics_device_info": analytics_device_info,
            "service_shield": service_shield,
            "ote_api": ote_api,
            "boiler_coordinator": boiler_coordinator,  # NOVÉ: Boiler coordinator
            "balancing_manager": balancing_manager,  # PHASE 3: Refactored Balancing Manager
            "dashboard_enabled": dashboard_enabled,  # NOVÉ: stav dashboard
            "config": {
                "enable_statistics": statistics_enabled,
                "enable_pricing": entry.options.get("enable_pricing", False),
                "enable_boiler": entry.options.get("enable_boiler", False),  # NOVÉ
                "enable_dashboard": dashboard_enabled,  # NOVÉ
            },
        }

        # Data source controller (cloud/hybrid/local with proxy health fallback)
        try:
            data_source_controller = DataSourceController(
                hass,
                entry,
                coordinator,
                telemetry_store=hass.data[DOMAIN][entry.entry_id].get(
                    "telemetry_store"
                ),
            )
            await data_source_controller.async_start()
            hass.data[DOMAIN][entry.entry_id][
                "data_source_controller"
            ] = data_source_controller
        except Exception as err:
            _LOGGER.warning("DataSourceController start failed (non-critical): %s", err)

        # OPRAVA: Přidání ServiceShield dat do globálního úložiště pro senzory
        if service_shield:
            # Vytvoříme globální odkaz na ServiceShield pro senzory
            hass.data[DOMAIN]["shield"] = service_shield

            # Vytvoříme device info pro ServiceShield (per-box service device)
            try:
                from .entities.base_sensor import resolve_box_id

                shield_box_id = resolve_box_id(coordinator)
            except Exception:
                shield_box_id = entry.options.get("box_id")
            if not (isinstance(shield_box_id, str) and shield_box_id.isdigit()):
                shield_box_id = "unknown"
            shield_device_info = {
                "identifiers": {(DOMAIN, f"{shield_box_id}_shield")},
                "name": f"ServiceShield {shield_box_id}",
                "manufacturer": "OIG",
                "model": "Shield",
                "via_device": (DOMAIN, shield_box_id),
                "entry_type": "service",
            }
            hass.data[DOMAIN][entry.entry_id]["shield_device_info"] = shield_device_info

            _LOGGER.debug("ServiceShield data prepared for sensors")

            # OPRAVA: Přidání debug logování pro ServiceShield stav
            _LOGGER.info(f"ServiceShield status: {service_shield.get_shield_status()}")
            _LOGGER.info(f"ServiceShield queue info: {service_shield.get_queue_info()}")

        # POZN: Plná migrace/cleanup device registry je riziková (může rozbít entity).
        # Děláme jen bezpečný úklid prázdných zařízení s neplatným box_id (např. spot_prices/unknown).

        # Vždy registrovat sensor platform
        await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

        # Targeted cleanup for stale/invalid devices (e.g., 'spot_prices', 'unknown')
        # that can be left behind after unique_id/device_id stabilization.
        hass.async_create_task(_cleanup_invalid_empty_devices(hass, entry))

        # OPRAVA: Dashboard registrujeme až TERAZ - po vytvoření všech senzorů A POUZE pokud je enabled
        if dashboard_enabled:
            await _setup_frontend_panel(hass, entry)
            _LOGGER.info("OIG Cloud Dashboard panel enabled and registered")
        else:
            await _remove_frontend_panel(hass, entry)
            _LOGGER.info(
                "OIG Cloud Dashboard panel disabled - panel not registered"
            )  # OPRAVA: lepší log message

        # Přidáme listener pro změny konfigurace - OPRAVEN callback na async funkci
        entry.async_on_unload(entry.add_update_listener(async_update_options))

        # Async importy pro vyhnání se blokování event loopu
        from .services import (
            async_setup_entry_services_with_shield,
            async_setup_services,
        )

        # Setup základních služeb (pouze jednou pro celou integraci)
        if len([k for k in hass.data[DOMAIN].keys() if k != "shield"]) == 1:
            await async_setup_services(hass)

        # Setup entry-specific služeb s shield ochranou
        # OPRAVA: Předání service_shield přímo, ne z hass.data
        await async_setup_entry_services_with_shield(hass, entry, service_shield)

        # NOVÉ: Registrace HTTP API endpointů pro boiler
        if boiler_coordinator:
            from .boiler.api_views import register_boiler_api_views

            register_boiler_api_views(hass)
            _LOGGER.info("Boiler API endpoints registered")

        # NOVÉ: Registrace Planning API endpointů
        from .api.planning_api import setup_planning_api_views

        setup_planning_api_views(hass)
        _LOGGER.info("Planning API endpoints registered")

        # NOVÉ: Registrace OIG Cloud REST API endpointů pro heavy data
        # (timeline, spot prices, analytics)
        try:
            from .api.ha_rest_api import setup_api_endpoints

            setup_api_endpoints(hass)
            _LOGGER.info("✅ OIG Cloud REST API endpoints registered successfully")
        except Exception as e:
            _LOGGER.error(
                f"Failed to register OIG Cloud REST API endpoints: {e}", exc_info=True
            )
            # Pokračujeme i bez API - senzory budou fungovat s attributes

        # OPRAVA: Zajistit, že ServiceShield je připojený k volání služeb
        if service_shield:
            _LOGGER.info(
                "ServiceShield je aktivní a připravený na interceptování služeb"
            )
            # Test interceptu - simulace volání pro debug
            _LOGGER.debug(f"ServiceShield pending: {len(service_shield.pending)}")
            _LOGGER.debug(f"ServiceShield queue: {len(service_shield.queue)}")
            _LOGGER.debug(f"ServiceShield running: {service_shield.running}")

            # OPRAVA: Explicitní spuštění monitorování
            _LOGGER.debug("Ověřuji, že ServiceShield monitoring běží...")

            # Přidáme test callback pro ověření funkčnosti
            async def test_shield_monitoring(_now: Any) -> None:
                status = service_shield.get_shield_status()
                queue_info = service_shield.get_queue_info()
                _LOGGER.debug(
                    f"[OIG Shield] Test monitoring tick - pending: {len(service_shield.pending)}, queue: {len(service_shield.queue)}, running: {service_shield.running}"
                )
                _LOGGER.debug("[OIG Shield] Status: %s", status)
                _LOGGER.debug("[OIG Shield] Queue info: %s", queue_info)

                # OPRAVA: Debug telemetrie - ukážeme co by se odesílalo
                if service_shield.telemetry_handler:
                    _LOGGER.debug("[OIG Shield] Telemetry handler je aktivní")
                    if hasattr(service_shield, "_log_telemetry"):
                        _LOGGER.debug(
                            "[OIG Shield] Telemetry logging metoda je dostupná"
                        )
                else:
                    _LOGGER.debug("[OIG Shield] Telemetry handler není aktivní")

            # Registrujeme test callback na kratší interval pro debug
            from datetime import timedelta

            from homeassistant.helpers.event import async_track_time_interval

            entry.async_on_unload(
                async_track_time_interval(
                    hass, test_shield_monitoring, timedelta(seconds=30)
                )
            )

        else:
            _LOGGER.warning("ServiceShield není dostupný - služby nebudou chráněny")

        # OPRAVA: ODSTRANĚNÍ duplicitní registrace služeb - způsobovala přepsání správného schématu
        # Služby se už registrovaly výše v async_setup_entry_services_with_shield
        # await services.async_setup_services(hass)  # ODSTRANĚNO
        # await services.async_setup_entry_services(hass, entry)  # ODSTRANĚNO

        _LOGGER.debug("OIG Cloud integration setup complete")
        return True

    except Exception as e:
        _LOGGER.error(f"Error initializing OIG Cloud: {e}", exc_info=True)
        raise ConfigEntryNotReady(f"Error initializing OIG Cloud: {e}") from e


async def _setup_telemetry(hass: core.HomeAssistant, username: str) -> None:
    """Setup telemetry if enabled."""
    try:
        _LOGGER.debug("Starting telemetry setup...")

        email_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()
        hass_id = hashlib.sha256(hass.data["core.uuid"].encode("utf-8")).hexdigest()

        _LOGGER.debug(
            f"Telemetry identifiers - Email hash: {email_hash[:16]}..., HASS ID: {hass_id[:16]}..."
        )

        from .shared.logging import setup_simple_telemetry

        telemetry = setup_simple_telemetry(email_hash, hass_id)
        if telemetry:
            hass.data.setdefault(DOMAIN, {})["telemetry"] = telemetry
            _LOGGER.info("Telemetry initialized (simple mode)")
        else:
            _LOGGER.debug("Telemetry initialization skipped (no handler)")

    except Exception as e:
        _LOGGER.warning(f"Failed to setup telemetry: {e}", exc_info=True)
        # Pokračujeme bez telemetrie


async def async_unload_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    # Odebrání dashboard panelu při unload
    await _remove_frontend_panel(hass, entry)

    # PHASE 3: Cleanup Balancing Manager (no async_shutdown needed - just storage)

    # NOVÉ: Cleanup session manageru
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        data_source_controller = hass.data[DOMAIN][entry.entry_id].get(
            "data_source_controller"
        )
        if data_source_controller:
            try:
                await data_source_controller.async_stop()
            except Exception as err:
                _LOGGER.debug("DataSourceController stop failed: %s", err)

        session_manager = hass.data[DOMAIN][entry.entry_id].get("session_manager")
        if session_manager:
            _LOGGER.debug("Closing session manager")
            await session_manager.close()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: Any
) -> bool:
    """Allow removing stale devices created by this integration.

    Home Assistant calls this when the user tries to delete a device from the UI.
    We only allow removing devices that have no entities.
    """
    _ = config_entry
    try:
        from homeassistant.helpers import entity_registry as er

        entity_registry = er.async_get(hass)
        if er.async_entries_for_device(entity_registry, device_entry.id):
            return False
        # Allow removal for both current and legacy identifier domains.
        # Legacy versions used separate identifier domains:
        # - "oig_cloud_analytics"
        # - "oig_cloud_shield"
        allowed_domains = {DOMAIN, f"{DOMAIN}_analytics", f"{DOMAIN}_shield"}
        return any(
            identifier[0] in allowed_domains for identifier in device_entry.identifiers
        )
    except Exception:
        return False


async def async_reload_entry(config_entry: config_entries.ConfigEntry) -> None:
    """Reload config entry."""
    hass = config_entry.hass
    await async_unload_entry(hass, config_entry)
    await async_setup_entry(hass, config_entry)


async def async_update_options(
    hass: HomeAssistant, config_entry: config_entries.ConfigEntry
) -> None:
    """Update options with dashboard management."""
    old_options = config_entry.options
    new_options = dict(config_entry.options)

    # Kontrola změny dashboard nastavení
    old_dashboard_enabled = old_options.get("enable_dashboard", False)
    new_dashboard_enabled = new_options.get("enable_dashboard", False)

    _LOGGER.debug(
        f"Dashboard options update: old={old_dashboard_enabled}, new={new_dashboard_enabled}"
    )

    if old_dashboard_enabled != new_dashboard_enabled:
        _LOGGER.info(
            f"Dashboard setting changed: {old_dashboard_enabled} -> {new_dashboard_enabled}"
        )

        if new_dashboard_enabled:
            # Zapnutí dashboard
            await _setup_frontend_panel(hass, config_entry)
            _LOGGER.info("Dashboard panel enabled")
        else:
            # Vypnutí dashboard
            await _remove_frontend_panel(hass, config_entry)
            _LOGGER.info("Dashboard panel disabled")

        # Aktualizace dat v hass.data
        if DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]:
            hass.data[DOMAIN][config_entry.entry_id][
                "dashboard_enabled"
            ] = new_dashboard_enabled
            hass.data[DOMAIN][config_entry.entry_id]["config"][
                "enable_dashboard"
            ] = new_dashboard_enabled
    else:
        # PŘIDÁNO: I když se hodnota nezměnila, ujistíme se že panel není registrován pokud je disabled
        if not new_dashboard_enabled:
            await _remove_frontend_panel(hass, config_entry)
            _LOGGER.debug("Ensuring dashboard panel is not registered (disabled)")

    # Pokud byla označena potřeba reload, proveď ho
    if new_options.get("_needs_reload"):
        new_options.pop("_needs_reload", None)
        hass.config_entries.async_update_entry(config_entry, options=new_options)
        hass.async_create_task(hass.config_entries.async_reload(config_entry.entry_id))
    else:
        hass.config_entries.async_update_entry(config_entry, options=new_options)


async def _cleanup_unused_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Vyčištění nepoužívaných zařízení."""
    try:
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)

        # Najdeme všechna zařízení pro tuto integraci
        devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)

        devices_to_remove = []
        for device in devices:
            device_name = device.name or ""
            should_keep = True

            # Definujeme pravidla pro zachování zařízení
            keep_patterns = [
                "OIG.*Statistics",  # Staré statistiky (regex pattern)
                "ČEZ Battery Box",
                "OIG Cloud Home",
                "Analytics & Predictions",
                "ServiceShield",
            ]
            for pattern in keep_patterns:
                if pattern in device_name:
                    should_keep = True
                    break
            else:
                # Pokud neodpovídá keep patterns, zkontrolujeme remove patterns

                # Zkontrolujeme, jestli zařízení odpovídá keep patterns
                for pattern in keep_patterns:
                    if re.search(pattern, device_name):
                        should_keep = False
                        break
                else:
                    # Pokud nemá žádné entity, můžeme smazat
                    device_entities = er.async_entries_for_device(
                        entity_registry, device.id
                    )
                    if not device_entities:
                        should_keep = False

            if not should_keep:
                devices_to_remove.append(device)
                _LOGGER.info(
                    f"Marking device for removal: {device.name} (ID: {device.id})"
                )
            else:
                _LOGGER.debug(f"Keeping device: {device.name} (ID: {device.id})")

        # Smažeme nepoužívaná zařízení
        for device in devices_to_remove:
            try:
                _LOGGER.info(f"Removing unused device: {device.name} (ID: {device.id})")
                device_registry.async_remove_device(device.id)
            except Exception as e:
                _LOGGER.warning("Error removing device {device.id}: %s", e)

        if devices_to_remove:
            _LOGGER.info(f"Removed {len(devices_to_remove)} unused devices")
        else:
            _LOGGER.debug("No unused devices found to remove")
    except Exception as e:
        _LOGGER.warning("Error cleaning up devices: %s", e)
