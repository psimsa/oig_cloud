"""Notification management for OIG Cloud integration."""

from __future__ import annotations

import logging
import re
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union, Tuple
from dataclasses import dataclass

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


@dataclass
class OigNotification:
    """Representation of OIG Cloud notification."""

    id: str
    type: str  # error, warning, info, debug
    message: str
    timestamp: datetime
    device_id: Optional[str] = None
    severity: int = 0
    read: bool = False
    raw_data: Optional[Dict[str, Any]] = None


class OigNotificationParser:
    """Parser for OIG Cloud notifications from JavaScript/JSON."""

    def __init__(self) -> None:
        """Initialize notification parser."""
        # OPRAVA: Aktualizované patterny pro HTML strukturu s escaped znaky
        self._html_notification_pattern = re.compile(
            r'<div class="folder">.*?<div class="point level-(\d+)">.*?</div>.*?<div class="date">([^<]+)</div>.*?<div class="row-2"><strong>([^<]+)</strong>\s*-\s*([^<]+)</div>.*?<div class="body"><p>([^<]*(?:<br[^>]*>[^<]*)*)</p></div>.*?</div>',
            re.DOTALL | re.MULTILINE,
        )

        # Původní patterny pro JSON (backup)
        self._js_function_pattern = re.compile(
            r"showNotifications\s*\(\s*([^)]+)\s*\)", re.MULTILINE | re.DOTALL
        )
        self._json_pattern = re.compile(
            r'(\{[^{}]*(?:"type"|"level"|"severity")\s*:\s*"(?:error|warning|info|debug|alert|notice)"[^{}]*\})',
            re.MULTILINE,
        )
        # Rozšířené patterny pro bypass detekci
        self._bypass_pattern = re.compile(
            r"(?:bypass|manual|maintenance|service).*?(?:true|false|on|off|enabled|disabled|zapnuto|vypnuto|active|inactive)",
            re.IGNORECASE,
        )

    def parse_from_controller_call(self, content: str) -> List[OigNotification]:
        """Parse notifications from Controller.Call.php content."""
        notifications = []

        try:
            _LOGGER.debug(f"Parsing notification content preview: {content[:500]}...")

            # NOVÉ: Zkusit parsovat JSON wrapper first
            html_content = self._extract_html_from_json_response(content)
            if html_content:
                _LOGGER.debug(
                    f"Extracted HTML from JSON wrapper, length: {len(html_content)}"
                )
                _LOGGER.debug(f"HTML content preview: {html_content[:300]}...")
                content = html_content

            # Nejdřív zkusíme parsovat HTML strukturu
            html_notifications = self._parse_html_notifications(content)
            notifications.extend(html_notifications)

            # Pokud nenajdeme HTML notifikace, zkusíme JSON
            if not html_notifications:
                json_notifications = self._parse_json_notifications(content)
                notifications.extend(json_notifications)

            # Odstranit duplicity podle ID
            unique_notifications = []
            seen_ids = set()
            for notification in notifications:
                if notification.id not in seen_ids:
                    unique_notifications.append(notification)
                    seen_ids.add(notification.id)

            _LOGGER.debug(
                f"Parsed {len(unique_notifications)} unique notifications from controller"
            )
            return unique_notifications

        except Exception as e:
            _LOGGER.error(f"Error parsing notifications: {e}")
            return []

    def _extract_html_from_json_response(self, content: str) -> Optional[str]:
        """Extract HTML content from JSON wrapper response."""
        try:
            # Zkusit parsovat jako JSON array: [[11,"ctrl-notifs"," HTML ",null]]
            import json

            data = json.loads(content)
            if isinstance(data, list) and len(data) > 0:
                first_item = data[0]
                if isinstance(first_item, list) and len(first_item) >= 3:
                    # Třetí element by měl být HTML obsah
                    html_content = first_item[2]
                    if isinstance(html_content, str) and len(html_content) > 10:
                        # NOVÉ: Unescape HTML entity pro správné parsování
                        import html

                        html_content = html.unescape(html_content)
                        _LOGGER.debug(
                            "Successfully extracted and unescaped HTML from JSON wrapper"
                        )
                        return html_content

            return None

        except (json.JSONDecodeError, IndexError, TypeError) as e:
            _LOGGER.debug(f"Content is not JSON wrapper format: {e}")
            return None
        except Exception as e:
            _LOGGER.warning(f"Error extracting HTML from JSON: {e}")
            return None

    def _parse_html_notifications(self, content: str) -> List[OigNotification]:
        """Parse HTML structured notifications."""
        notifications = []

        try:
            # Najít všechny HTML notifikace
            html_matches = self._html_notification_pattern.findall(content)
            _LOGGER.debug(f"Found {len(html_matches)} HTML notification matches")

            for match in html_matches:
                severity_level, date_str, device_id, short_message, full_message = match

                try:
                    notification = self._create_notification_from_html(
                        severity_level, date_str, device_id, short_message, full_message
                    )
                    if notification:
                        notifications.append(notification)
                except Exception as e:
                    _LOGGER.warning(f"Error creating notification from HTML match: {e}")
                    continue

        except Exception as e:
            _LOGGER.error(f"Error parsing HTML notifications: {e}")

        return notifications

    def _parse_json_notifications(self, content: str) -> List[OigNotification]:
        """Parse JSON structured notifications (fallback)."""
        notifications = []

        try:
            # Původní logika pro JSON
            js_matches = self._js_function_pattern.findall(content)
            _LOGGER.debug(f"Found {len(js_matches)} JS function matches")

            for js_match in js_matches:
                json_matches = self._json_pattern.findall(js_match)
                for json_str in json_matches:
                    notification = self._parse_single_notification(json_str)
                    if notification:
                        notifications.append(notification)

        except Exception as e:
            _LOGGER.error(f"Error parsing JSON notifications: {e}")

        return notifications

    def _parse_single_notification(self, json_str: str) -> Optional[OigNotification]:
        """Parse single notification from JSON string."""
        try:
            # Clean and parse JSON
            clean_json = self._clean_json_string(json_str)
            data = json.loads(clean_json)
            return self._create_notification_from_json(data)
        except (json.JSONDecodeError, ValueError) as e:
            _LOGGER.debug(f"Failed to parse JSON notification: {e}")
            return None
        except Exception as e:
            _LOGGER.warning(f"Error parsing single notification: {e}")
            return None

    def parse_notification(self, notif_data: Dict[str, Any]) -> OigNotification:
        """Parse notification from API response data."""
        try:
            return self._create_notification_from_json(notif_data)
        except Exception as e:
            _LOGGER.warning(f"Error parsing notification from API data: {e}")
            # Return fallback notification
            return OigNotification(
                id=f"fallback_{int(datetime.now().timestamp())}",
                type="info",
                message="Failed to parse notification",
                timestamp=datetime.now(),
                device_id=notif_data.get("device_id"),
                severity=1,
                read=False,
                raw_data=notif_data,
            )

    def _get_notification_severity(self, css_level: str) -> Tuple[str, int]:
        """Parse severity level from CSS class and return type and numeric severity."""
        # Rozšířené mapování všech možných úrovní
        severity_map = {
            "1": ("info", 1),  # Informační zprávy (stav baterie, denní výroba)
            "2": ("warning", 2),  # Varování
            "3": ("notice", 2),  # Upozornění (zapnutí/vypnutí) - považujeme za warning
            "4": ("error", 3),  # Chyby nebo důležité akce
            "5": ("critical", 4),  # Kritické stavy (pokud existují)
        }

        result = severity_map.get(css_level, ("info", 1))
        _LOGGER.debug(
            f"Mapped CSS level-{css_level} to severity: {result[0]} (numeric: {result[1]})"
        )
        return result

    def _create_notification_from_html(
        self,
        severity_level: str,
        date_str: str,
        device_id: str,
        short_message: str,
        full_message: str,
    ) -> Optional[OigNotification]:
        """Create notification object from HTML data."""
        try:
            # NOVÉ: Vyčistit HTML tagy z plné zprávy a device_id
            import html

            # Unescape HTML entities
            clean_message = html.unescape(full_message)
            clean_message = re.sub(r"<br\s*/?>", "\n", clean_message)
            clean_message = re.sub(r"<[^>]+>", "", clean_message).strip()

            # Extrahovat device ID z formátu "Box #2206237016"
            device_match = re.search(r"Box #(\w+)", device_id)
            extracted_device_id = device_match.group(1) if device_match else device_id

            # Parsovat datum - formát "28. 6. 2025 | 13:05"
            timestamp = self._parse_czech_datetime(date_str)

            # Vytvořit unikátní ID z kombinace času, zařízení a obsahu
            content_hash = hash(f"{extracted_device_id}_{clean_message}_{date_str}")
            notification_id = f"html_{abs(content_hash)}_{int(timestamp.timestamp())}"

            # Určit typ notifikace a severitu podle CSS level
            notification_type, severity = self._get_notification_severity(
                severity_level
            )

            # Pokud obsah zprávy obsahuje bypass, přednostně to označíme jako warning
            if "bypass" in clean_message.lower():
                notification_type = "warning"
                severity = 2

            return OigNotification(
                id=notification_id,
                type=notification_type,
                message=clean_message,
                timestamp=timestamp,
                device_id=extracted_device_id,
                severity=severity,
                read=False,
                raw_data={
                    "date_str": date_str,
                    "device_id": extracted_device_id,
                    "short_message": short_message,
                    "full_message": full_message,
                    "css_level": severity_level,
                    "source": "html",
                },
            )

        except Exception as e:
            _LOGGER.warning(f"Error creating HTML notification: {e}")
            return None

    def _parse_czech_datetime(self, date_str: str) -> datetime:
        """Parse Czech datetime format '25. 6. 2025 | 8:13'."""
        try:
            # Rozdělit datum a čas
            date_part, time_part = date_str.split(" | ")

            # Parsovat datum "25. 6. 2025"
            day, month, year = date_part.split(". ")
            day = int(day)
            month = int(month)
            year = int(year)

            # Parsovat čas "8:13"
            hour, minute = time_part.split(":")
            hour = int(hour)
            minute = int(minute)

            return datetime(year, month, day, hour, minute)

        except Exception as e:
            _LOGGER.warning(f"Error parsing datetime '{date_str}': {e}")
            return datetime.now()

    def detect_bypass_status(self, content: str) -> bool:
        """Detect bypass status from content."""
        try:
            # Nejdříve hledáme bypass zprávy v notifikacích
            bypass_messages = [
                r"automatický\s+BYPASS\s*-\s*Zapnut",
                r"automatic\s+BYPASS\s*-\s*ON",
                r"bypass.*zapnut",
                r"bypass.*enabled",
                r"bypass.*active",
            ]

            bypass_off_messages = [
                r"automatický\s+BYPASS\s*-\s*Vypnut",
                r"automatic\s+BYPASS\s*-\s*OFF",
                r"bypass.*vypnut",
                r"bypass.*disabled",
                r"bypass.*inactive",
            ]

            # Kontrola zpráv o bypass
            for pattern in bypass_messages:
                if re.search(pattern, content, re.IGNORECASE):
                    _LOGGER.debug(
                        f"Bypass detected as ON from message with pattern: {pattern}"
                    )
                    return True

            for pattern in bypass_off_messages:
                if re.search(pattern, content, re.IGNORECASE):
                    _LOGGER.debug(
                        f"Bypass detected as OFF from message with pattern: {pattern}"
                    )
                    return False

            # Rozšířené hledání indikátorů bypass stavu v HTML/JS obsahu
            bypass_indicators = [
                r"bypass.*?(?:true|on|enabled|zapnuto|active|1)",
                r"manual.*?mode.*?(?:true|on|enabled|zapnuto|active|1)",
                r"maintenance.*?(?:true|on|enabled|zapnuto|active|1)",
                r"service.*?mode.*?(?:true|on|enabled|zapnuto|active|1)",
                r'"bypass"\s*:\s*(?:true|1|"on"|"active")',
                r'"manual_mode"\s*:\s*(?:true|1|"on")',
                r"bypassEnabled.*?true",
                r"bypass_active.*?true",
                r"isManualMode.*?true",
            ]

            for pattern in bypass_indicators:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    _LOGGER.debug(
                        f"Bypass detected as ON with pattern: {pattern} -> {matches}"
                    )
                    return True

            # Negativní indikátory
            negative_indicators = [
                r"bypass.*?(?:false|off|disabled|vypnuto|inactive|0)",
                r"manual.*?mode.*?(?:false|off|disabled|vypnuto|inactive|0)",
                r'"bypass"\s*:\s*(?:false|0|"off"|"inactive")',
                r"bypassEnabled.*?false",
                r"bypass_active.*?false",
                r"isManualMode.*?false",
            ]

            for pattern in negative_indicators:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    _LOGGER.debug(
                        f"Bypass detected as OFF with pattern: {pattern} -> {matches}"
                    )
                    return False

            # Pokud nenajdeme žádný specifický indikátor, předpokládáme OFF
            _LOGGER.debug("No bypass indicators found, assuming OFF")
            return False

        except Exception as e:
            _LOGGER.error(f"Error detecting bypass status: {e}")
            return False

    def _determine_notification_type(
        self, message: str, severity_level: str = "1"
    ) -> str:
        """Determine notification type from message content and CSS severity level."""
        message_lower = message.lower()

        try:
            css_level = int(severity_level)
        except (ValueError, TypeError):
            css_level = 1

        # Nejdřív kontrola podle CSS level
        if css_level >= 3:
            return "error"
        elif css_level == 2:
            return "warning"

        # Pak kontrola podle obsahu zprávy
        error_keywords = ["chyba", "error", "failed", "neúspěšný", "problém"]
        warning_keywords = ["varování", "warning", "pozor", "upozornění", "bypass"]
        info_keywords = ["stav", "info", "baterii", "nabití", "dobrý den"]

        # Bypass notifikace považujeme za warning
        if "bypass" in message_lower:
            return "warning"

        for keyword in error_keywords:
            if keyword in message_lower:
                return "error"

        for keyword in warning_keywords:
            if keyword in message_lower:
                return "warning"

        for keyword in info_keywords:
            if keyword in message_lower:
                return "info"

        # Fallback podle CSS level
        if css_level == 1:
            return "info"
        else:
            return "warning"

    def _clean_json_string(self, json_str: str) -> str:
        """Clean and fix common JSON formatting issues."""
        # Odstranit JavaScript komentáře
        json_str = re.sub(r"//.*$", "", json_str, flags=re.MULTILINE)

        # Opravit apostrofy na uvozovky
        json_str = re.sub(r"'([^']*)':", r'"\1":', json_str)
        json_str = re.sub(r":\s*'([^']*)'", r': "\1"', json_str)

        # Odstranit trailing commas
        json_str = re.sub(r",\s*}", "}", json_str)
        json_str = re.sub(r",\s*]", "]", json_str)

        return json_str.strip()

    def _create_notification_from_json(
        self, data: Dict[str, Any]
    ) -> Optional[OigNotification]:
        """Create notification object from JSON data."""
        try:
            notification_type = data.get("type", "info")
            message = data.get("message", data.get("text", "Unknown notification"))

            # Generovat ID z obsahu nebo použít timestamp
            notification_id = data.get("id")
            if not notification_id:
                notification_id = f"{notification_type}_{hash(message)}_{int(datetime.now().timestamp())}"

            # Parsovat timestamp
            timestamp = datetime.now()
            if "timestamp" in data:
                try:
                    timestamp = datetime.fromisoformat(str(data["timestamp"]))
                except (ValueError, TypeError):
                    pass
            elif "time" in data:
                try:
                    timestamp = datetime.fromisoformat(str(data["time"]))
                except (ValueError, TypeError):
                    pass

            # Určit závažnost
            severity_map = {"error": 3, "warning": 2, "info": 1, "debug": 0}
            severity = severity_map.get(notification_type.lower(), 1)

            return OigNotification(
                id=str(notification_id),
                type=notification_type.lower(),
                message=str(message),
                timestamp=timestamp,
                device_id=data.get("device_id"),
                severity=severity,
                read=data.get("read", False),
                raw_data=data,
            )

        except Exception as e:
            _LOGGER.warning(f"Error creating notification from data {data}: {e}")
            return None

    def _parse_notifications_from_html(self, html_content: str) -> List[Dict[str, Any]]:
        """Parse notifications from HTML content - optimized version using only row-2."""
        notifications = []

        try:
            # Regex pattern pro folder div - používáme pouze row-2 pro obsah zprávy
            folder_pattern = re.compile(
                r'<div class="folder">.*?'
                r'<div class="point level-(\d+)"></div>.*?'  # priority level
                r'<div class="date">([^<]+)</div>.*?'  # date
                r'<div class="row-2">([^<]+)</div>.*?'  # message content (only source we need)
                r"</div>",
                re.DOTALL | re.MULTILINE,
            )

            matches = folder_pattern.findall(html_content)
            _LOGGER.debug(f"Found {len(matches)} HTML notification matches")

            for match in matches:
                try:
                    priority_level, date_text, message_text = match

                    # Clean up text content
                    date_text = self._clean_html_text(date_text)
                    message_text = self._clean_html_text(message_text)

                    # Parse message content for device ID
                    device_id = "unknown"
                    content = message_text

                    if " - " in message_text:
                        # Split only on first occurrence
                        device_part, content = message_text.split(" - ", 1)

                        # Extract device ID from "**Box #XXXXXXXX**" format
                        device_match = re.search(r"\*\*Box #(\w+)\*\*", device_part)
                        device_id = device_match.group(1) if device_match else "unknown"

                    # Parse priority level
                    try:
                        priority = int(priority_level)
                    except (ValueError, TypeError):
                        priority = 1

                    # Parse Czech date format: "25. 6. 2025 | 8:13"
                    try:
                        date_clean = date_text.replace(" | ", " ").strip()
                        parsed_date = datetime.strptime(date_clean, "%d. %m. %Y %H:%M")
                        iso_date = parsed_date.isoformat()
                    except ValueError as e:
                        _LOGGER.warning(f"Could not parse date '{date_text}': {e}")
                        parsed_date = datetime.now()
                        iso_date = parsed_date.isoformat()

                    notification = {
                        "id": f"{device_id}_{int(parsed_date.timestamp())}",
                        "device_id": device_id,
                        "date": iso_date,
                        "date_raw": date_text,
                        "message": content,
                        "priority": priority,
                        "priority_name": self._get_priority_name(priority),
                        "source": "html_regex_optimized",
                    }

                    notifications.append(notification)

                except Exception as e:
                    _LOGGER.warning(f"Error parsing individual notification: {e}")
                    continue

            _LOGGER.debug(f"Successfully parsed {len(notifications)} notifications")
            return notifications

        except Exception as e:
            _LOGGER.error(f"Error parsing notifications HTML: {e}")
            return []

    def _clean_html_text(self, text: str) -> str:
        """Clean HTML text content using regex."""
        if not text:
            return ""

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", text)

        # Replace HTML entities
        html_entities = {
            "&amp;": "&",
            "&lt;": "<",
            "&gt;": ">",
            "&quot;": '"',
            "&apos;": "'",
            "&nbsp;": " ",
            "<br>": "\n",
            "<br/>": "\n",
            "<br />": "\n",
        }

        for entity, replacement in html_entities.items():
            text = text.replace(entity, replacement)

        return text.strip()

    def _get_priority_name(self, priority: int) -> str:
        """Get priority name from level number."""
        priority_names = {1: "info", 2: "warning", 3: "error", 4: "critical"}
        return priority_names.get(priority, "info")


class OigNotificationManager:
    """Manager for OIG Cloud notifications."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: Union["OigCloudApi", aiohttp.ClientSession],
        base_url: str,
    ) -> None:
        """Initialize notification manager."""
        self.hass = hass
        self._api = api
        self._base_url = base_url
        self._parser = OigNotificationParser()
        self._notifications: List[OigNotification] = []
        self._bypass_status: bool = False
        self._storage_key = "oig_notifications"
        self._max_notifications = 100
        self._device_id: Optional[str] = None
        _LOGGER.debug(
            f"NotificationManager initialized: base_url={base_url}, api_type={type(api)}"
        )

    def set_device_id(self, device_id: str) -> None:
        """Set device ID for notification requests."""
        self._device_id = device_id
        # Aktualizovat storage key s device_id
        self._storage_key = f"oig_notifications_{device_id}"
        _LOGGER.debug(f"Set device_id to {device_id} for notification manager")

    def get_device_id(self) -> Optional[str]:
        """Get current device ID."""
        return self._device_id

    def _generate_nonce(self) -> str:
        """Generate nonce for request."""
        import time

        return str(int(time.time() * 1000))

    async def _save_notifications_to_storage(
        self, notifications: List[OigNotification]
    ) -> None:
        """Save notifications to storage."""
        try:
            store = Store(self.hass, 1, self._storage_key)

            # Převést notifikace na dict pro storage
            notifications_data = []
            for notif in notifications[: self._max_notifications]:  # Omezit počet
                notifications_data.append(
                    {
                        "id": notif.id,
                        "type": notif.type,
                        "message": notif.message,
                        "timestamp": notif.timestamp.isoformat(),
                        "device_id": notif.device_id,
                        "severity": notif.severity,
                        "read": notif.read,
                        "raw_data": notif.raw_data,
                    }
                )

            await store.async_save(
                {
                    "notifications": notifications_data,
                    "bypass_status": self._bypass_status,
                    "last_update": dt_util.now().isoformat(),
                }
            )

            _LOGGER.debug(f"Saved {len(notifications_data)} notifications to storage")

        except Exception as e:
            _LOGGER.error(f"Error saving notifications to storage: {e}")

    async def _load_notifications_from_storage(self) -> List[OigNotification]:
        """Load notifications from storage."""
        try:
            store = Store(self.hass, 1, self._storage_key)
            data = await store.async_load()

            if not data or "notifications" not in data:
                return []

            notifications = []
            for notif_data in data["notifications"]:
                try:
                    # Převést zpět na OigNotification objekt
                    timestamp = datetime.fromisoformat(notif_data["timestamp"])
                    notification = OigNotification(
                        id=notif_data["id"],
                        type=notif_data["type"],
                        message=notif_data["message"],
                        timestamp=timestamp,
                        device_id=notif_data.get("device_id"),
                        severity=notif_data.get("severity", 1),
                        read=notif_data.get("read", False),
                        raw_data=notif_data.get("raw_data"),
                    )
                    notifications.append(notification)
                except Exception as e:
                    _LOGGER.warning(f"Error loading notification from storage: {e}")
                    continue

            # Obnovit bypass status pokud je k dispozici
            if "bypass_status" in data:
                self._bypass_status = data["bypass_status"]

            _LOGGER.debug(f"Loaded {len(notifications)} notifications from storage")
            return notifications

        except Exception as e:
            _LOGGER.warning(f"Error loading notifications from storage: {e}")
            return []

    async def refresh_data(self) -> bool:
        """Alias for update_from_api to maintain compatibility with coordinator."""
        _LOGGER.debug("refresh_data called - redirecting to update_from_api")
        return await self.update_from_api()

    async def update_from_api(self) -> bool:
        """Update notifications directly from API - simplified method."""
        if not self._device_id:
            _LOGGER.warning("Device ID not set for notification fetching, skipping")
            return False

        try:
            _LOGGER.debug(f"Updating notifications for device: {self._device_id}")
            _LOGGER.debug(f"API object type: {type(self._api)}")
            _LOGGER.debug(
                f"API object methods: {[method for method in dir(self._api) if not method.startswith('_')]}"
            )

            # OPRAVA: Použít API metodu přímo
            if hasattr(self._api, "get_notifications"):
                _LOGGER.debug("API object has get_notifications method, calling...")
                result = await self._api.get_notifications(self._device_id)

                if result.get("status") == "success" and "content" in result:
                    content = result["content"]
                    _LOGGER.debug(
                        f"Fetched notification content length: {len(content)}"
                    )

                    # Parsovat notifikace
                    notifications = self._parser.parse_from_controller_call(content)
                    filtered_notifications = []
                    for notif in notifications:
                        if (
                            notif.device_id == self._device_id
                            or notif.device_id is None
                        ):
                            filtered_notifications.append(notif)

                    bypass_status = self._parser.detect_bypass_status(content)
                    await self._update_notifications(filtered_notifications)
                    self._bypass_status = bypass_status

                    _LOGGER.info(
                        f"Successfully updated {len(self._notifications)} notifications, bypass: {bypass_status}"
                    )
                    return True

                elif result.get("error"):
                    error = result["error"]
                    _LOGGER.warning(f"API returned error: {error}")

                    # Načíst z cache při chybě
                    cached_notifications = await self._load_notifications_from_storage()
                    if cached_notifications:
                        _LOGGER.info(
                            f"Using {len(cached_notifications)} cached notifications due to API error: {error}"
                        )
                        self._notifications = cached_notifications
                        return True

                    return False
                else:
                    _LOGGER.warning("API returned unexpected response format")
                    return False
            else:
                # ROZŠÍŘENÁ diagnostika
                available_methods = [
                    method
                    for method in dir(self._api)
                    if callable(getattr(self._api, method))
                    and not method.startswith("_")
                ]
                _LOGGER.error(
                    f"API object {type(self._api)} doesn't have get_notifications method"
                )
                _LOGGER.error(f"Available callable methods: {available_methods}")

                # Zkusit najít podobné metody
                notification_methods = [
                    method
                    for method in available_methods
                    if "notification" in method.lower()
                ]
                if notification_methods:
                    _LOGGER.info(
                        f"Found notification-related methods: {notification_methods}"
                    )

                # Fallback na cache
                cached_notifications = await self._load_notifications_from_storage()
                if cached_notifications:
                    _LOGGER.info(
                        f"Using {len(cached_notifications)} cached notifications due to missing API method"
                    )
                    self._notifications = cached_notifications
                    return True

                return False

        except Exception as e:
            _LOGGER.error(f"Error in update_from_api: {e}")

            # Při chybě zkusit načíst z cache
            try:
                cached_notifications = await self._load_notifications_from_storage()
                if cached_notifications:
                    _LOGGER.info(
                        f"Using {len(cached_notifications)} cached notifications due to exception"
                    )
                    self._notifications = cached_notifications
                    return True
            except Exception as cache_error:
                _LOGGER.warning(f"Error loading cached notifications: {cache_error}")

            return False

    async def get_notifications_and_status(self) -> Tuple[List[OigNotification], bool]:
        """Get current notifications and bypass status."""
        await self.update_from_api()
        return self._notifications, self._bypass_status

    async def _update_notifications(self, notifications: List[OigNotification]) -> None:
        """Update internal notification list and handle storage."""
        try:
            # Uložit notifikace do storage
            await self._save_notifications_to_storage(notifications)

            # Aktualizovat interní seznam notifikací
            self._notifications = notifications

            _LOGGER.info(
                f"Updated notifications: {len(notifications)} loaded, {self._bypass_status=}"
            )

        except Exception as e:
            _LOGGER.error(f"Error updating notifications: {e}")

    def get_latest_notification_message(self) -> str:
        """Get latest notification message."""
        if not self._notifications:
            return "No notifications"
        return self._notifications[0].message

    def get_bypass_status(self) -> str:
        """Get bypass status."""
        return "on" if self._bypass_status else "off"

    def get_notification_count(self, notification_type: str) -> int:
        """Get count of notifications by type."""
        if notification_type == "error":
            return len([n for n in self._notifications if n.type == "error"])
        elif notification_type == "warning":
            return len([n for n in self._notifications if n.type == "warning"])
        return 0

    def get_unread_count(self) -> int:
        """Get count of unread notifications."""
        return len([n for n in self._notifications if not n.read])

    def get_latest_notification(self) -> Optional[OigNotification]:
        """Get latest notification object."""
        if not self._notifications:
            return None
        return self._notifications[0]
