"""
ČHMÚ (Český hydrometeorologický ústav) CAP XML API klient.

Stahuje a parsuje CAP (Common Alerting Protocol) XML bulletiny s meteorologickými varováními.
Filtruje varování podle GPS souřadnic (point-in-polygon/circle).
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import aiohttp
import async_timeout

_LOGGER = logging.getLogger(__name__)

# --- CAP 1.2 Namespace ---
CAP_NS = "{urn:oasis:names:tc:emergency:cap:1.2}"

# ČHMÚ CAP XML feed:
# Původní URL (www.chmi.cz/.../XOCZ50_OKPR.xml) je nově 404; ČHMÚ přesunulo CAP do open data.
# Autoindex obsahuje historické soubory + timestampy, vybereme nejnovější.
CHMU_CAP_BASE_URL = "https://opendata.chmi.cz/meteorology/weather/alerts/cap/"

# Severity mapping podle CAP 1.2 standardu
SEVERITY_MAP: Dict[str, int] = {
    "Minor": 1,  # Žluté varování
    "Moderate": 2,  # Oranžové varování
    "Severe": 3,  # Červené varování
    "Extreme": 4,  # Fialové varování
}

# Fallback: ČHMÚ awareness level (pokud severity chybí)
AWARENESS_LEVEL_MAP: Dict[str, int] = {
    "2; yellow": 1,
    "3; orange": 2,
    "4; red": 3,
}


class ChmuApiError(Exception):
    """Chyba při komunikaci s ČHMÚ API."""

    pass


class ChmuApi:
    """API klient pro ČHMÚ CAP XML bulletiny."""

    _AUTO_INDEX_RE = re.compile(
        r'href="(?P<file>alert_cap_(?P<series>\d+)_\d+\.xml)".*?\s(?P<dt>\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2})\s+\d+',
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self._last_data: Dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None
        self.timezone = ZoneInfo("Europe/Prague")
        self._session: Optional[aiohttp.ClientSession] = None

    # ---------- Cache management ----------

    def _is_cache_valid(self) -> bool:
        """Kontrola validity cache (1 hodina)."""
        if not self._cache_time or not self._last_data:
            return False
        now = datetime.now(timezone.utc)
        return (now - self._cache_time) < timedelta(hours=1)

    def _invalidate_cache(self) -> None:
        """Invalidace cache."""
        self._cache_time = None
        self._last_data = {}

    # ---------- HTTP fetch ----------

    async def _fetch_cap_xml(self, session: aiohttp.ClientSession) -> str:
        """
        Stažení CAP XML z ČHMÚ.

        Args:
            session: aiohttp session

        Returns:
            XML string

        Raises:
            ChmuApiError: Při chybě HTTP requestu
        """
        try:
            async with async_timeout.timeout(30):
                cap_url = await self._resolve_latest_cap_url(session)
                async with session.get(cap_url) as response:
                    if response.status != 200:
                        raise ChmuApiError(
                            f"HTTP {response.status} při stahování CAP XML ({cap_url})"
                        )

                    text = await response.text()

                    if not text or len(text) < 100:
                        raise ChmuApiError("Prázdný nebo neplatný CAP XML response")

                    _LOGGER.debug(f"CAP XML úspěšně staženo ({len(text)} znaků)")
                    return text

        except asyncio.TimeoutError:
            raise ChmuApiError("Timeout při stahování CAP XML (30s)")
        except aiohttp.ClientError as e:
            raise ChmuApiError(f"HTTP chyba při stahování CAP XML: {e}")

    async def _resolve_latest_cap_url(self, session: aiohttp.ClientSession) -> str:
        """Resolve the most recent CAP XML URL from ČHMÚ open data directory listing."""
        try:
            async with async_timeout.timeout(15):
                async with session.get(CHMU_CAP_BASE_URL) as response:
                    if response.status != 200:
                        raise ChmuApiError(
                            f"HTTP {response.status} při načítání indexu CAP ({CHMU_CAP_BASE_URL})"
                        )
                    index_html = await response.text()

            def _parse_index_dt(value: str) -> Optional[datetime]:
                try:
                    return datetime.strptime(value, "%d-%b-%Y %H:%M")
                except Exception as err:
                    _LOGGER.debug("Skipping CAP index entry '%s': %s", value, err)
                    return None

            items: list[tuple[datetime, str, str]] = []
            for m in self._AUTO_INDEX_RE.finditer(index_html):
                dt = _parse_index_dt(m.group("dt"))
                if dt is None:
                    continue
                items.append((dt, m.group("series"), m.group("file")))

            if not items:
                raise ChmuApiError("CAP index neobsahuje žádné alert_cap_*.xml soubory")

            preferred = [it for it in items if it[1] == "50"]
            dt, series, fname = max(preferred or items, key=lambda x: x[0])
            url = f"{CHMU_CAP_BASE_URL}{fname}"
            _LOGGER.debug(
                "ČHMÚ CAP resolved: series=%s file=%s ts=%s",
                series,
                fname,
                dt.isoformat(),
            )
            return url
        except ChmuApiError:
            raise
        except Exception as e:
            raise ChmuApiError(f"Chyba při výběru nejnovějšího CAP souboru: {e}")

    # ---------- XML parsing ----------

    def _parse_cap_xml(self, xml_text: str) -> List[Dict[str, Any]]:
        """
        Parsování CAP XML do seznamu varování.

        Args:
            xml_text: XML string

        Returns:
            Seznam varování (raw data z XML)
        """
        try:
            root = ET.fromstring(xml_text)  # nosec B314
        except ET.ParseError as e:
            _LOGGER.error(f"Chyba parsování CAP XML: {e}")
            return []

        alerts = []

        # Root je přímo <alert> element (ne document s více alerts)
        # CAP 1.2 má strukturu: <alert><info>...</info></alert>

        # Pokud root je alert element
        if root.tag == f"{CAP_NS}alert":
            # Každý alert může mít více <info> bloků (různé jazyky a události)
            for info_elem in root.findall(f"{CAP_NS}info"):
                try:
                    alert_data = self._parse_info_block(root, info_elem)
                    if alert_data:
                        alerts.append(alert_data)
                except Exception as e:
                    _LOGGER.warning(f"Chyba při parsování info bloku: {e}")
                    continue

        _LOGGER.info(f"Naparsováno {len(alerts)} varování z CAP XML")
        return alerts

    def _parse_info_block(
        self, alert_elem: ET.Element, info_elem: ET.Element
    ) -> Optional[Dict[str, Any]]:
        """
        Parsování jednoho <info> bloku.

        Args:
            alert_elem: <alert> element (pro sent, identifier, atd.)
            info_elem: <info> element

        Returns:
            Dict s daty varování nebo None
        """
        # Jazyk
        language = self._get_text(info_elem, "language", "cs")

        # Pouze cs nebo en
        if language not in ["cs", "en"]:
            return None

        # Event (typ varování)
        event = self._get_text(info_elem, "event")
        if not event:
            return None

        # Severity
        severity_text = self._get_text(info_elem, "severity", "Minor")
        severity_level = SEVERITY_MAP.get(severity_text, 0)

        # Fallback: awareness level (ČHMÚ specifické)
        if severity_level == 0:
            awareness_level = self._get_text(
                info_elem, "parameter[valueName='awareness_level']/value", ""
            )
            severity_level = AWARENESS_LEVEL_MAP.get(awareness_level, 0)

        # Urgency & Certainty
        urgency = self._get_text(info_elem, "urgency", "Unknown")
        certainty = self._get_text(info_elem, "certainty", "Unknown")

        # Časové údaje
        sent = self._get_text(alert_elem, "sent")
        effective = self._get_text(info_elem, "effective")
        onset = self._get_text(info_elem, "onset")
        expires = self._get_text(info_elem, "expires")

        # Popis a instrukce
        description = self._get_text(info_elem, "description", "")
        instruction = self._get_text(info_elem, "instruction", "")

        # Oblasti a geometrie
        areas = self._parse_areas(info_elem)

        # Status (active/upcoming/expired)
        status = self._determine_status(effective, onset, expires)

        # ETA (estimated time to arrival) v hodinách
        eta_hours = self._calculate_eta(onset)

        return {
            "language": language,
            "event": event,
            "severity": severity_text,
            "severity_level": severity_level,
            "urgency": urgency,
            "certainty": certainty,
            "sent": sent,
            "effective": effective,
            "onset": onset,
            "expires": expires,
            "description": description,
            "instruction": instruction,
            "areas": areas,
            "status": status,
            "eta_hours": eta_hours,
        }

    def _parse_areas(self, info_elem: ET.Element) -> List[Dict[str, Any]]:
        """
        Parsování <area> elementů s geometrií.

        Returns:
            Seznam oblastí s geometrií
        """
        areas = []

        for area_elem in info_elem.findall(f"{CAP_NS}area"):
            area_desc = self._get_text(area_elem, "areaDesc", "")

            # Polygon (seznam souřadnic lat,lon)
            polygon_text = self._get_text(area_elem, "polygon", "")
            polygon = self._parse_polygon(polygon_text) if polygon_text else None

            # Circle (lat,lon radius_km)
            circle_text = self._get_text(area_elem, "circle", "")
            circle = self._parse_circle(circle_text) if circle_text else None

            # Geocode (ORP/NUTS kódy)
            geocodes = []
            for geocode_elem in area_elem.findall(f"{CAP_NS}geocode"):
                value_name = self._get_text(geocode_elem, "valueName", "")
                value = self._get_text(geocode_elem, "value", "")
                if value_name and value:
                    geocodes.append({"name": value_name, "value": value})

            areas.append(
                {
                    "description": area_desc,
                    "polygon": polygon,
                    "circle": circle,
                    "geocodes": geocodes,
                }
            )

        return areas

    def _parse_polygon(self, polygon_text: str) -> Optional[List[Tuple[float, float]]]:
        """
        Parsování polygon stringu (CAP formát: "lat1,lon1 lat2,lon2 ...").

        Returns:
            Seznam (lat, lon) tuple nebo None
        """
        try:
            points = []
            for pair in polygon_text.strip().split():
                lat_str, lon_str = pair.split(",")
                lat = float(lat_str)
                lon = float(lon_str)
                points.append((lat, lon))

            return points if len(points) >= 3 else None
        except (ValueError, IndexError):
            _LOGGER.warning(f"Neplatný polygon formát: {polygon_text}")
            return None

    def _parse_circle(self, circle_text: str) -> Optional[Dict[str, float]]:
        """
        Parsování circle stringu (CAP formát: "lat,lon radius_km").

        Returns:
            Dict s center (lat, lon) a radius nebo None
        """
        try:
            parts = circle_text.strip().split()
            if len(parts) != 2:
                return None

            lat_str, lon_str = parts[0].split(",")
            lat = float(lat_str)
            lon = float(lon_str)
            radius_km = float(parts[1])

            return {
                "center_lat": lat,
                "center_lon": lon,
                "radius_km": radius_km,
            }
        except (ValueError, IndexError):
            _LOGGER.warning(f"Neplatný circle formát: {circle_text}")
            return None

    def _get_text(self, elem: ET.Element, tag: str, default: str = "") -> str:
        """
        Získání textu z XML elementu (s namespace).

        Args:
            elem: Parent element
            tag: Tag name (bez namespace)
            default: Default hodnota

        Returns:
            Text nebo default
        """
        # Pokud tag obsahuje XPath (např. "parameter[valueName='...']/value")
        if "[" in tag or "/" in tag:
            # Složitější XPath - použijeme find s plným namespace
            # Pro jednoduchost to neimplementujeme, vrátíme default
            return default

        child = elem.find(f"{CAP_NS}{tag}")
        if child is not None and child.text:
            return child.text.strip()

        return default

    def _determine_status(
        self, effective: Optional[str], onset: Optional[str], expires: Optional[str]
    ) -> str:
        """
        Určení statusu varování (active/upcoming/expired).

        Args:
            effective: Effective datetime
            onset: Onset datetime
            expires: Expires datetime

        Returns:
            "active", "upcoming", nebo "expired"
        """
        now = datetime.now(timezone.utc)

        # Parse datetimes
        expires_dt = self._parse_iso_datetime(expires)
        if expires_dt and expires_dt < now:
            return "expired"

        onset_dt = self._parse_iso_datetime(onset)
        if onset_dt and onset_dt > now:
            return "upcoming"

        effective_dt = self._parse_iso_datetime(effective)
        if effective_dt and effective_dt > now:
            return "upcoming"

        return "active"

    def _calculate_eta(self, onset: Optional[str]) -> float:
        """
        Výpočet ETA (estimated time to arrival) v hodinách.

        Args:
            onset: Onset datetime string

        Returns:
            Počet hodin do onset (0 pokud už nastal nebo chybí)
        """
        if not onset:
            return 0.0

        onset_dt = self._parse_iso_datetime(onset)
        if not onset_dt:
            return 0.0

        now = datetime.now(timezone.utc)
        delta = onset_dt - now

        hours = delta.total_seconds() / 3600
        return max(0.0, hours)

    def _parse_iso_datetime(self, dt_string: Optional[str]) -> Optional[datetime]:
        """
        Parsování ISO datetime stringu.

        Args:
            dt_string: ISO datetime (např. "2025-10-24T14:00:00+02:00")

        Returns:
            datetime objekt (UTC) nebo None
        """
        if not dt_string:
            return None

        try:
            # Python 3.11+ podporuje fromisoformat přímo
            dt = datetime.fromisoformat(dt_string)
            # Konverze na UTC
            return dt.astimezone(timezone.utc)
        except (ValueError, AttributeError):
            return None

    # ---------- Geometrické filtrování ----------

    def _filter_by_location(
        self, alerts: List[Dict[str, Any]], latitude: float, longitude: float
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Filtrování varování podle GPS souřadnic.

        Args:
            alerts: Seznam všech varování
            latitude: GPS latitude
            longitude: GPS longitude

        Returns:
            (filtered_alerts, filter_method)
            filter_method: "polygon_match", "circle_match", "geocode_fallback", nebo "no_filter"
        """
        local_alerts = []
        filter_method = "no_filter"

        for alert in alerts:
            # Zkusíme všechny oblasti
            matched = False
            for area in alert.get("areas", []):
                # 1. Polygon match
                if area.get("polygon"):
                    if self._point_in_polygon((latitude, longitude), area["polygon"]):
                        local_alerts.append(alert)
                        filter_method = "polygon_match"
                        matched = True
                        break

                # 2. Circle match
                if not matched and area.get("circle"):
                    circle = area["circle"]
                    if self._point_in_circle(
                        (latitude, longitude),
                        (circle["center_lat"], circle["center_lon"]),
                        circle["radius_km"],
                    ):
                        local_alerts.append(alert)
                        filter_method = "circle_match"
                        matched = True
                        break

                # 3. Geocode fallback (jednoduché substring match)
                # NOTE: Implementovat přesnější geocode matching s databází ORP/NUTS
                if not matched and area.get("geocodes"):
                    # Prozatím vše prochází (fallback)
                    # V produkci by zde bylo mapování GPS -> ORP/NUTS kód
                    local_alerts.append(alert)
                    filter_method = "geocode_fallback"
                    matched = True
                    break

            # Pokračujeme dále - chceme projít VŠECHNY výstrahy, ne jen první match

        return local_alerts, filter_method

    def _point_in_polygon(
        self, point: Tuple[float, float], polygon: List[Tuple[float, float]]
    ) -> bool:
        """
        Ray casting algoritmus pro point-in-polygon test.

        Args:
            point: (latitude, longitude)
            polygon: Seznam (latitude, longitude) bodů

        Returns:
            True pokud bod je uvnitř polygonu
        """
        lat, lon = point
        n = len(polygon)
        inside = False

        p1_lat, p1_lon = polygon[0]
        for i in range(1, n + 1):
            p2_lat, p2_lon = polygon[i % n]

            if lon > min(p1_lon, p2_lon):
                if lon <= max(p1_lon, p2_lon):
                    if lat <= max(p1_lat, p2_lat):
                        x_intersection = None
                        if p1_lon != p2_lon:
                            x_intersection = (lon - p1_lon) * (p2_lat - p1_lat) / (
                                p2_lon - p1_lon
                            ) + p1_lat
                        if p1_lat == p2_lat or (
                            x_intersection and lat <= x_intersection
                        ):
                            inside = not inside

            p1_lat, p1_lon = p2_lat, p2_lon

        return inside

    def _point_in_circle(
        self, point: Tuple[float, float], center: Tuple[float, float], radius_km: float
    ) -> bool:
        """
        Point-in-circle test pomocí Haversine vzdálenosti.

        Args:
            point: (latitude, longitude)
            center: (latitude, longitude)
            radius_km: Poloměr v kilometrech

        Returns:
            True pokud bod je uvnitř kruhu
        """
        distance_km = self._haversine_distance(point, center)
        return distance_km <= radius_km

    def _haversine_distance(
        self, point1: Tuple[float, float], point2: Tuple[float, float]
    ) -> float:
        """
        Haversine formule pro výpočet vzdálenosti mezi dvěma GPS body.

        Args:
            point1: (latitude, longitude)
            point2: (latitude, longitude)

        Returns:
            Vzdálenost v kilometrech
        """
        lat1, lon1 = point1
        lat2, lon2 = point2

        # Převod na radiány
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

        # Haversine formule
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))

        # Poloměr Země v km
        radius_earth_km = 6371.0

        return radius_earth_km * c

    # ---------- Alert selection ----------

    def _select_top_alert(
        self, alerts: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Výběr "top" varování podle severity a ETA.

        Args:
            alerts: Seznam varování

        Returns:
            Top varování nebo None
        """
        if not alerts:
            return None

        # Filtr: pouze active nebo upcoming
        relevant = [a for a in alerts if a.get("status") in ["active", "upcoming"]]

        if not relevant:
            return None

        # Sort: 1) severity DESC, 2) ETA ASC
        sorted_alerts = sorted(
            relevant,
            key=lambda x: (-x.get("severity_level", 0), x.get("eta_hours", 999)),
        )

        return sorted_alerts[0]

    def _prefer_czech_language(
        self, alerts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Preferování českých varování, fallback na anglické.

        Pokud existuje stejné varování v cs i en, ponechat pouze cs.
        """
        # Grupování podle event + onset (unikátní varování)
        seen = {}
        result = []

        for alert in alerts:
            key = f"{alert.get('event', '')}_{alert.get('onset', '')}"
            lang = alert.get("language", "en")

            if key not in seen:
                seen[key] = alert
                result.append(alert)
            elif lang == "cs" and seen[key].get("language") == "en":
                # Nahradit anglické českým
                result.remove(seen[key])
                seen[key] = alert
                result.append(alert)

        return result

    # ---------- Public API ----------

    async def get_warnings(
        self,
        latitude: float,
        longitude: float,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> Dict[str, Any]:
        """
        Stažení a zpracování ČHMÚ varování.

        Args:
            latitude: GPS latitude
            longitude: GPS longitude
            session: aiohttp session (pokud None, vytvoří se nový)

        Returns:
            Dict s daty:
            {
                "all_warnings": [...],  # Všechna varování v ČR
                "local_warnings": [...],  # Varování pro vaši lokalitu
                "top_local_warning": {...},  # Top lokální varování
                "severity_level": 0-4,  # Max severity pro lokalitu
                "all_warnings_count": 15,
                "local_warnings_count": 2,
                "highest_severity_cz": 3,
                "gps_location": {"latitude": ..., "longitude": ...},
                "filter_method": "polygon_match",
                "last_update": "2025-10-24T10:15:23+02:00",
                "source": "ČHMÚ CAP Feed",
            }
        """
        # Cache check
        if self._is_cache_valid():
            _LOGGER.debug("Používám cachovaná data")
            return self._last_data

        # HTTP session
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        try:
            # 1. Fetch CAP XML
            xml_text = await self._fetch_cap_xml(session)

            # 2. Parse XML
            all_alerts = self._parse_cap_xml(xml_text)

            # 3. Preferovat české jazykové verze
            all_alerts = self._prefer_czech_language(all_alerts)

            # 4. Filtrovat podle lokality
            local_alerts, filter_method = self._filter_by_location(
                all_alerts, latitude, longitude
            )

            # 5. Vybrat top lokální varování
            top_local = self._select_top_alert(local_alerts)

            all_warnings_count = len(all_alerts)
            local_warnings_count = len(local_alerts)
            severity_level = top_local.get("severity_level", 0) if top_local else 0
            highest_severity = max(
                (a.get("severity_level", 0) for a in all_alerts), default=0
            )

            # 6. Sestavit výsledek
            result = {
                "all_warnings": all_alerts,
                "local_warnings": local_alerts,
                "top_local_warning": top_local,
                "severity_level": severity_level,
                "all_warnings_count": all_warnings_count,
                "local_warnings_count": local_warnings_count,
                "highest_severity_cz": highest_severity,
                "gps_location": {
                    "latitude": latitude,
                    "longitude": longitude,
                },
                "filter_method": filter_method,
                "last_update": datetime.now(self.timezone).isoformat(),
                "source": "ČHMÚ CAP Feed",
            }

            # Cache update
            self._last_data = result
            self._cache_time = datetime.now(timezone.utc)

            _LOGGER.info(
                "ČHMÚ data aktualizována: %s celkem, %s lokálních, severity=%s",
                all_warnings_count,
                local_warnings_count,
                severity_level,
            )

            return result

        finally:
            if close_session:
                await session.close()
