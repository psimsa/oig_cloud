"""Shared logging utilities for OIG Cloud."""

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional

import aiohttp
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

from ..const import OT_ENDPOINT, OT_HEADERS, OT_INSECURE
from .shared import get_resource


class RestLogHandler(logging.Handler):
    """Custom log handler pro odesílání logů přes REST API na New Relic.

    POUŽITÍ: Pouze pro ServiceShield telemetrii - bezpečnostní události.
    Ostatní komponenty používají lokální logování.
    """

    def __init__(
        self,
        endpoint: str,
        headers: Dict[str, str],
        email_hash: str,
        hass_id: str,
        level: int = logging.NOTSET,
    ) -> None:
        super().__init__(level)
        self.endpoint = endpoint
        self.headers = headers
        self.email_hash = email_hash
        self.hass_id = hass_id
        self.session: Optional[aiohttp.ClientSession] = None
        # OPRAVA: Přidáme cache pro prevenci duplicitního odesílání
        self._sent_records: Dict[str, float] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        """Získá nebo vytvoří aiohttp session."""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(ssl=not OT_INSECURE)
            self.session = aiohttp.ClientSession(connector=connector)
        return self.session

    def emit(self, record: logging.LogRecord) -> None:
        """Odešle log záznam asynchronně."""
        try:
            # OPRAVA: Zabránit nekonečné smyčce - nelogovat vlastní telemetrické zprávy
            if record.name.startswith("custom_components.oig_cloud.shared.logging"):
                return

            asyncio.create_task(self._async_emit(record))
        except Exception as e:
            # OPRAVA: Nelogovat chyby z handleru, aby se předešlo smyčce
            pass

    def _should_send_to_telemetry(self, record: logging.LogRecord) -> bool:
        """Determine if log record should be sent to telemetry."""
        # OPRAVA: Nelogovat vlastní telemetry zprávy - způsobuje smyčku
        if record.name.startswith("custom_components.oig_cloud.shared.logging"):
            return False

        # OPRAVA: Pouze záznamy s shield_data nebo security eventi
        is_telemetry = hasattr(record, "shield_data") or record.name.endswith(
            ".security"
        )

        return is_telemetry

    def _generate_record_id(self, record: logging.LogRecord) -> str:
        """Generuje jedinečné ID pro log record pro prevenci duplicit."""
        if hasattr(record, "shield_data"):
            # Pro shield_data použijeme event_type + service_name + timestamp
            shield_data = record.shield_data
            return f"{shield_data.get('event_type')}_{shield_data.get('service_name')}_{shield_data.get('timestamp')}"
        else:
            # Pro security eventy použijeme message + timestamp
            return f"{record.getMessage()}_{int(record.created * 1000)}"

    async def _async_emit(self, record: logging.LogRecord) -> None:
        """Asynchronně odešle log záznam na New Relic."""
        try:
            if not self._should_send_to_telemetry(record):
                return

            # OPRAVA: Prevence duplicitního odesílání
            record_id = self._generate_record_id(record)
            current_time = time.time()

            # Pokud jsme už tento record odeslali v posledních 5 sekundách, přeskočíme
            if record_id in self._sent_records:
                if current_time - self._sent_records[record_id] < 5.0:
                    return

            # Označíme record jako odeslaný
            self._sent_records[record_id] = current_time

            # Vyčistíme staré záznamy (starší než 60 sekund)
            cutoff_time = current_time - 60.0
            self._sent_records = {
                rid: timestamp
                for rid, timestamp in self._sent_records.items()
                if timestamp > cutoff_time
            }

            session = await self._get_session()

            # Vytvoření log záznamu v New Relic formátu
            log_data = {
                "timestamp": int(time.time() * 1000),  # milliseconds
                "message": self.format(record),
                "level": record.levelname,
                "logger": record.name,
                "attributes": {
                    "service.name": "oig_cloud",
                    "service.version": "1.0.0",
                    "user.email_hash": self.email_hash,
                    "hass.id": self.hass_id,
                    "log.level": record.levelname,
                    "log.logger": record.name,
                    "log.pathname": record.pathname,
                    "log.lineno": record.lineno,
                    "log.funcName": record.funcName,
                },
            }

            # OPRAVA: Přidání shield_data z extra pokud existuje
            if hasattr(record, "shield_data"):
                log_data["attributes"]["shield_data"] = record.shield_data

            # Přidání exception info pokud existuje
            if record.exc_info:
                log_data["attributes"]["exception.type"] = (
                    record.exc_info[0].__name__ if record.exc_info[0] else None
                )
                log_data["attributes"]["exception.message"] = (
                    str(record.exc_info[1]) if record.exc_info[1] else None
                )

            # Payload pro New Relic Logs API
            payload = [
                {
                    "common": {"attributes": log_data["attributes"]},
                    "logs": [log_data],
                }
            ]

            headers = dict(self.headers)
            headers["Content-Type"] = "application/json"

            url = f"{self.endpoint}/v1/logs"

            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                # OPRAVA: Logujeme pouze výsledek, ne celý proces
                if response.status not in [200, 202]:
                    response_text = await response.text()
                    # Pouze logujeme chyby
                    pass
                # Úspěch nelogujeme, aby se předešlo spamu

        except Exception as e:
            # Tiché selhání
            pass

    async def close(self) -> None:
        """Uzavře HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()


def setup_otel_logging(email_hash: str, hass_id: str) -> Any:
    """Nastaví REST logging handler pro odesílání na New Relic.

    POUŽITÍ: Pouze pro ServiceShield - nikoli pro obecné logování integrace.
    """
    try:
        # OPRAVA: Odstraněno debug logování, které by mohlo způsobit smyčku

        # Převedení headers z tuple na dict
        headers_dict = dict(OT_HEADERS)

        logging_handler = RestLogHandler(
            endpoint=OT_ENDPOINT,
            headers=headers_dict,
            email_hash=email_hash,
            hass_id=hass_id,
            level=logging.INFO,  # OPRAVA: Nastavit na INFO místo NOTSET
        )

        return logging_handler

    except Exception as e:
        # OPRAVA: Tiché selhání - nelogovat chyby při setupu
        return logging.NullHandler()


def get_telemetry_logger(hass: HomeAssistant) -> logging.Logger:
    """Get telemetry logger instance."""
    # OPRAVA: Použijeme logger místo print
    _LOGGER.info("[GET_TELEMETRY_LOGGER] Creating telemetry logger")

    # OPRAVA: Používáme speciální logger pro telemetrii
    logger = logging.getLogger("custom_components.oig_cloud.telemetry")

    # OPRAVA: Používáme RestLogHandler místo neexistujícího TelemetryHandler
    handlers = [h for h in logger.handlers if isinstance(h, RestLogHandler)]
    _LOGGER.info(f"[GET_TELEMETRY_LOGGER] Found {len(handlers)} telemetry handlers")

    if not handlers:
        _LOGGER.info(
            "[GET_TELEMETRY_LOGGER] No telemetry handler found, checking parent loggers"
        )
        # Pokud nemá vlastní handler, zkusíme parent
        parent = logger.parent
        while parent and parent.name != "root":
            parent_handlers = [
                h for h in parent.handlers if isinstance(h, RestLogHandler)
            ]
            _LOGGER.info(
                f"[GET_TELEMETRY_LOGGER] Parent {parent.name} has {len(parent_handlers)} telemetry handlers"
            )
            if parent_handlers:
                break
            parent = parent.parent

    # OPRAVA: Pokud nemáme handler, zkusíme ho najít v ServiceShield loggeru
    if not handlers:
        shield_logger = logging.getLogger("custom_components.oig_cloud.service_shield")
        shield_handlers = [
            h for h in shield_logger.handlers if isinstance(h, RestLogHandler)
        ]
        _LOGGER.info(
            f"[GET_TELEMETRY_LOGGER] Found {len(shield_handlers)} handlers in shield logger"
        )

        # Pokud ServiceShield má handler, zkopírujeme ho
        if shield_handlers:
            for handler in shield_handlers:
                logger.addHandler(handler)
                _LOGGER.info("[GET_TELEMETRY_LOGGER] Copied handler from shield logger")

    return logger
