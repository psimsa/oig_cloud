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


class SimpleTelemetry:
    """Jednoduchá telemetrie bez logging handleru."""

    def __init__(self, url: str, headers: Dict[str, str]) -> None:
        self.url = url
        self.headers = headers
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Získá nebo vytvoří aiohttp session."""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(ssl=not OT_INSECURE)
            self.session = aiohttp.ClientSession(connector=connector)
        return self.session

    async def send_event(
        self, event_type: str, service_name: str, data: Dict[str, Any]
    ) -> bool:
        """Pošle telemetrickou událost přímo do New Relic."""
        try:
            payload = {
                "timestamp": int(time.time() * 1000),
                "message": f"ServiceShield {event_type}: {service_name}",
                "level": "INFO",
                "logger": "custom_components.oig_cloud.telemetry",
                "event_type": event_type,
                "service_name": service_name,
                "component": "service_shield",
                **data,
            }

            # LOGOVÁNÍ: Co odesíláme a kam
            _LOGGER.debug(
                f"[TELEMETRY] Sending {event_type} for {service_name} to {self.url}"
            )
            _LOGGER.debug(f"[TELEMETRY] Payload size: {len(json.dumps(payload))} bytes")
            _LOGGER.debug(
                f"[TELEMETRY] Payload preview: {payload.get('message', 'N/A')}"
            )

            session = await self._get_session()

            async with session.post(
                self.url,
                json=payload,
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response_text = await response.text()

                # LOGOVÁNÍ: Co se vrátilo
                _LOGGER.debug(f"[TELEMETRY] Response: HTTP {response.status}")
                _LOGGER.debug(f"[TELEMETRY] Response body: {response_text[:200]}...")

                if response.status in [200, 202]:
                    _LOGGER.debug(
                        f"[TELEMETRY] Successfully sent {event_type} for {service_name}"
                    )
                    return True
                else:
                    _LOGGER.warning(
                        f"[TELEMETRY] Failed to send {event_type}: HTTP {response.status} - {response_text[:100]}"
                    )
                    return False

        except Exception as e:
            _LOGGER.error(
                f"[TELEMETRY] Exception while sending {event_type} for {service_name}: {e}",
                exc_info=True,
            )
            return False

    async def close(self) -> None:
        """Uzavře HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()


def setup_simple_telemetry(email_hash: str, hass_id: str) -> Optional[SimpleTelemetry]:
    """Setup jednoduché telemetrie."""
    try:
        url = f"{OT_ENDPOINT}/log/v1"
        headers = {"Content-Type": "application/json", "X-Event-Source": "logs"}

        for header_name, header_value in OT_HEADERS:
            headers[header_name] = header_value

        return SimpleTelemetry(url, headers)

    except Exception as e:
        _LOGGER.error(f"Failed to setup telemetry: {e}")
        return None
