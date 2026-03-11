# OTE (Operator trhu s elektřinou) – zjednodušené API:
# Pouze DAM Period (PT15M) + agregace na hodiny průměrem.
# Důležité: OTE SOAP endpoint je HTTP a vyžaduje správnou SOAPAction.

import asyncio
import json
import logging
import os
import xml.etree.ElementTree as ET  # nosec B314
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, TypedDict, cast
from zoneinfo import ZoneInfo

import aiohttp
from homeassistant.helpers.update_coordinator import UpdateFailed

_LOGGER = logging.getLogger(__name__)

# --- NAMESPACE & SOAP ---
NAMESPACE = (
    "http://www.ote-cr.cz/schema/service/public"  # NOSONAR - XML namespace identifier
)
SOAPENV = (
    "http://schemas.xmlsoap.org/soap/envelope/"  # NOSONAR - XML namespace identifier
)

# OTE endpoint podporuje HTTPS (viz WSDL soap:address) - preferujeme zabezpečenou variantu
OTE_PUBLIC_URL = "https://www.ote-cr.cz/services/PublicDataService"

SOAP_ACTIONS = {
    "GetDamPricePeriodE": f"{NAMESPACE}/GetDamPricePeriodE",
}


def _soap_headers(action: str) -> Dict[str, str]:
    return {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{SOAP_ACTIONS[action]}"',
    }


QUERY_DAM_PERIOD_E = """<?xml version="1.0" encoding="UTF-8" ?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:pub="http://www.ote-cr.cz/schema/service/public">
  <soapenv:Header/>
  <soapenv:Body>
    <pub:GetDamPricePeriodE>
      <pub:StartDate>{start}</pub:StartDate>
      <pub:EndDate>{end}</pub:EndDate>
      <pub:PeriodResolution>PT15M</pub:PeriodResolution>
      {range_parts}
    </pub:GetDamPricePeriodE>
  </soapenv:Body>
</soapenv:Envelope>
"""

# ---------- ČNB kurzy ----------


class OTEFault(Exception):
    pass


class InvalidDateError(Exception):
    pass


class Rate(TypedDict):
    validFor: str
    order: int
    country: str
    currency: str
    amount: int
    currencyCode: str
    rate: float


class Rates(TypedDict):
    rates: List[Rate]


class RateError(TypedDict):
    description: str
    errorCode: str
    happenedAt: str
    endPoint: str
    messageId: str


class CnbRate:
    RATES_URL: str = "https://api.cnb.cz/cnbapi/exrates/daily"

    def __init__(self) -> None:
        self._timezone: ZoneInfo = ZoneInfo("Europe/Prague")
        self._rates: Dict[str, Decimal] = {}
        self._last_checked_date: Optional[date] = None

    async def download_rates(self, day: date) -> Rates:
        params = {"date": day.isoformat()}
        async with aiohttp.ClientSession() as session:
            async with session.get(self.RATES_URL, params=params) as response:
                if response.status > 299:
                    if response.status == 400:
                        error = cast(RateError, await response.json())
                        if error.get("errorCode") == "VALIDATION_ERROR":
                            raise InvalidDateError(f"Invalid date format: {day}")
                    raise Exception(f"Error {response.status} while downloading rates")
                text = cast(Rates, await response.json())
        return text

    async def get_day_rates(self, day: date) -> Dict[str, Decimal]:
        rates: Dict[str, Decimal] = {"CZK": Decimal(1)}
        cnb_rates: Optional[Rates] = None
        for previous_day in range(0, 7):
            try:
                cnb_rates = await self.download_rates(
                    day - timedelta(days=previous_day)
                )
                break
            except InvalidDateError:
                continue
        if not cnb_rates:
            raise Exception("Could not download CNB rates for last 7 days")
        for rate in cnb_rates["rates"]:
            rates[rate["currencyCode"]] = Decimal(rate["rate"])
        return rates

    async def get_current_rates(self) -> Dict[str, Decimal]:
        now = datetime.now(timezone.utc)
        day = now.astimezone(self._timezone).date()
        if self._last_checked_date is None or day != self._last_checked_date:
            self._rates = await self.get_day_rates(day)
            self._last_checked_date = day
        return self._rates


# ---------- OTE API ----------


class OteApi:
    """Pouze DAM Period (PT15M) + agregace na hodiny průměrem."""

    def __init__(self, cache_path: Optional[str] = None) -> None:
        self._last_data: Dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None
        self._eur_czk_rate: Optional[float] = None
        self._rate_cache_time: Optional[datetime] = None
        self.timezone = ZoneInfo("Europe/Prague")
        self.utc = ZoneInfo("UTC")
        self._cnb_rate = CnbRate()
        self._cache_path: Optional[str] = cache_path

    async def close(self) -> None:
        """Compatibility no-op for sensors calling close() on removal.

        OteApi does not keep a persistent aiohttp session, so there is nothing to close.
        """
        return

    def _load_cached_spot_prices_sync(self) -> None:
        if not self._cache_path:
            return
        try:
            with open(self._cache_path, "r", encoding="utf-8") as cache_file:
                payload = json.load(cache_file)
            data = payload.get("last_data")
            cache_time = payload.get("cache_time")
            if data:
                self._last_data = data
            if cache_time:
                self._cache_time = datetime.fromisoformat(cache_time)
            _LOGGER.info("Loaded cached OTE spot prices (%s)", self._cache_path)
        except FileNotFoundError:
            return
        except Exception as err:
            _LOGGER.warning("Failed to load cached OTE spot prices: %s", err)

    async def async_load_cached_spot_prices(self) -> None:
        """Load cache from disk without blocking the event loop."""
        try:
            await asyncio.to_thread(self._load_cached_spot_prices_sync)
        except Exception as err:
            _LOGGER.debug("Async cache load failed: %s", err)

    def _persist_cache_sync(self) -> None:
        if not self._cache_path or not self._last_data:
            return
        try:
            directory = os.path.dirname(self._cache_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            payload = {
                "last_data": self._last_data,
                "cache_time": (
                    self._cache_time.isoformat() if self._cache_time else None
                ),
            }
            with open(self._cache_path, "w", encoding="utf-8") as cache_file:
                json.dump(payload, cache_file)
        except Exception as err:
            _LOGGER.warning("Failed to persist OTE cache: %s", err)

    async def async_persist_cache(self) -> None:
        """Persist cache to disk without blocking the event loop."""
        try:
            await asyncio.to_thread(self._persist_cache_sync)
        except Exception as err:
            _LOGGER.debug("Async cache persist failed: %s", err)

    # ---------- interní utilitky ----------

    def _has_data_for_date(self, target_date: date) -> bool:
        """Kontroluje, zda cache obsahuje data pro daný den."""
        if not self._last_data:
            return False

        prices = self._last_data.get("prices_czk_kwh", {})
        if not prices:
            return False

        date_prefix = target_date.strftime("%Y-%m-%d")
        return any(key.startswith(date_prefix) for key in prices.keys())

    def _is_cache_valid(self) -> bool:
        """Cache je validní pokud obsahuje požadovaná data.

        - Před 13h: musí mít data pro dnešek
        - Po 13h: musí mít data pro dnešek A zítřek
        """
        if not self._cache_time or not self._last_data:
            return False

        now = datetime.now(self.timezone)
        today = now.date()

        # Vždy musíme mít data pro dnešek
        if not self._has_data_for_date(today):
            return False

        # Po 13h musíme mít i data pro zítřek
        if now.hour >= 13:
            tomorrow = today + timedelta(days=1)
            if not self._has_data_for_date(tomorrow):
                return False

        return True

    def _should_fetch_new_data(self) -> bool:
        """Rozhodne, jestli máme stahovat nová data z OTE.

        Stahujeme pokud cache není validní:
        - Nemáme cache nebo nemá dnešní data
        - Po 13h a nemáme zítřejší data
        - Po půlnoci a nemáme data pro nový dnešek
        """
        return not self._is_cache_valid()

    def _dam_period_query(
        self,
        start: date,
        end: date,
        start_period: Optional[int] = None,
        end_period: Optional[int] = None,
    ) -> str:
        parts: List[str] = []
        if start_period is not None:
            parts.append(f"<pub:StartPeriod>{start_period}</pub:StartPeriod>")
        if end_period is not None:
            parts.append(f"<pub:EndPeriod>{end_period}</pub:EndPeriod>")
        return QUERY_DAM_PERIOD_E.format(
            start=start.isoformat(),
            end=end.isoformat(),
            range_parts="".join(parts),
        )

    async def _download_soap(self, body_xml: str, action: str) -> str:
        _LOGGER.debug(f"Sending SOAP request to {OTE_PUBLIC_URL} action={action}")
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    OTE_PUBLIC_URL, data=body_xml, headers=_soap_headers(action)
                ) as response:
                    text = await response.text()
                    _LOGGER.debug(f"SOAP Response status: {response.status}")
                    if response.status != 200:
                        raise aiohttp.ClientError(
                            f"HTTP {response.status}: {text[:500]}"
                        )
                    return text
        except aiohttp.ClientError as e:
            raise OTEFault(f"Unable to download OTE data: {e}")

    def _parse_soap_response(self, soap_response: str) -> ET.Element:
        try:
            root = ET.fromstring(soap_response)  # nosec B314
        except Exception as e:
            if "Application is not available" in soap_response:
                raise UpdateFailed("OTE Portal is currently not available!") from e
            raise UpdateFailed("Failed to parse query response.") from e

        fault = root.find(f".//{{{SOAPENV}}}Fault")
        if fault is not None:
            faultstring = fault.find("faultstring")
            error = faultstring.text if faultstring is not None else "Unknown error"
            raise OTEFault(error)

        return root

    def _parse_period_interval(self, date_obj: date, period_interval: str) -> datetime:
        """
        Parsuje PeriodInterval text (např. "23:45-24:00" nebo "02a:00-02a:15").

        DST handling:
        - "02a:00" = první výskyt hodiny 02:00 (před posunem času)
        - "02b:00" = druhý výskyt hodiny 02:00 (po posunu času)
        - Druhý výskyt posuneme o +1 minutu pro vizuální rozlišení v grafech
        """
        # Formát: "HH:MM-HH:MM" nebo "HHa:MM-HHa:MM" nebo "HHb:MM-HHb:MM"
        start_time = period_interval.split("-")[0].strip()

        # Detekce DST suffixu (a/b)
        is_second_occurrence = "b" in start_time

        # Odstranění suffixu a parsování času
        clean_time = start_time.replace("a", "").replace("b", "")
        hour, minute = map(int, clean_time.split(":"))

        # Pro druhý výskyt (b) přidáme +1 minutu
        if is_second_occurrence:
            minute += 1
            # Overflow check (pokud je 59+1 = 60)
            if minute >= 60:
                minute = 0
                hour += 1

        local_dt = datetime.combine(date_obj, time(hour, minute), tzinfo=self.timezone)
        return local_dt.astimezone(self.utc)

    def _aggregate_quarter_to_hour(
        self, qh_map: Dict[datetime, Decimal]
    ) -> Dict[datetime, Decimal]:
        buckets: Dict[datetime, List[Decimal]] = {}
        for dt_utc, val in qh_map.items():
            hkey = dt_utc.replace(minute=0, second=0, microsecond=0)
            buckets.setdefault(hkey, []).append(val)
        # prostý průměr ze 4 kvartálů (nebo 3/5 v DST dnech)
        return {k: (sum(v) / Decimal(len(v))) for k, v in buckets.items() if v}

    async def _get_dam_period_prices(
        self, start_day: date, end_day: date
    ) -> Dict[datetime, Decimal]:
        """Stáhne DAM PT15M (EUR/kWh interně)."""
        query = self._dam_period_query(start_day, end_day)
        xml = await self._download_soap(query, action="GetDamPricePeriodE")
        root = self._parse_soap_response(xml)

        result: Dict[datetime, Decimal] = {}
        for item in root.findall(".//{http://www.ote-cr.cz/schema/service/public}Item"):
            d_el = item.find("{http://www.ote-cr.cz/schema/service/public}Date")
            pinterval_el = item.find(
                "{http://www.ote-cr.cz/schema/service/public}PeriodInterval"
            )
            pres_el = item.find(
                "{http://www.ote-cr.cz/schema/service/public}PeriodResolution"
            )
            price_el = item.find("{http://www.ote-cr.cz/schema/service/public}Price")
            if not (
                d_el is not None
                and pinterval_el is not None
                and pres_el is not None
                and price_el is not None
            ):
                continue
            if not (d_el.text and pinterval_el.text and pres_el.text and price_el.text):
                continue
            if pres_el.text != "PT15M":
                # bezpečnostně ignorujeme jiné periody
                continue

            d = date.fromisoformat(d_el.text)
            price_eur_mwh = Decimal(price_el.text)  # EUR/MWh

            dt_utc = self._parse_period_interval(d, pinterval_el.text)
            result[dt_utc] = price_eur_mwh / Decimal(1000)  # EUR/kWh

        return result

    async def get_cnb_exchange_rate(self) -> Optional[float]:
        if self._rate_cache_time and self._eur_czk_rate:
            now = datetime.now()
            if self._rate_cache_time.date() == now.date():
                return self._eur_czk_rate

        try:
            _LOGGER.debug("Fetching CNB exchange rate from API")
            rates = await self._cnb_rate.get_current_rates()
            eur_rate = rates.get("EUR")
            if eur_rate:
                rate_float = float(eur_rate)
                self._eur_czk_rate = rate_float
                self._rate_cache_time = datetime.now()
                _LOGGER.info(f"Successfully fetched CNB rate: {rate_float}")
                return rate_float
            _LOGGER.warning("EUR rate not found in CNB response")
        except Exception as e:
            _LOGGER.warning(f"Error fetching CNB rate: {e}")

        return None

    # ---------- veřejné API ----------

    @staticmethod
    def get_current_15min_interval(now: datetime) -> int:
        """
        Vrátí index 15min intervalu (0-95) pro daný čas.

        Interval 0 = 00:00-00:15
        Interval 1 = 00:15-00:30
        ...
        Interval 95 = 23:45-24:00
        """
        hour: int = now.hour
        minute: int = now.minute

        # Zaokrouhlit dolů na nejbližších 15 min
        quarter: int = minute // 15

        return (hour * 4) + quarter

    @staticmethod
    def get_15min_price_for_interval(
        interval_index: int,
        spot_data: Dict[str, Any],
        target_date: Optional[date] = None,
    ) -> Optional[float]:
        """
        Vrátí spotovou cenu pro daný 15min interval z dat.

        Args:
            interval_index: Index intervalu 0-95
            spot_data: Data z get_spot_prices()
            target_date: Datum pro které hledat cenu (default = dnes)

        Returns:
            Cena v CZK/kWh nebo None pokud není dostupná
        """
        if not spot_data or "prices15m_czk_kwh" not in spot_data:
            return None

        if target_date is None:
            target_date = datetime.now().date()

        # Vypočítat hodinu a minutu z indexu
        hour: int = interval_index // 4
        minute: int = (interval_index % 4) * 15

        # Sestavit klíč pro vyhledání v datech
        time_key: str = f"{target_date.strftime('%Y-%m-%d')}T{hour:02d}:{minute:02d}:00"

        prices_15m: Dict[str, float] = spot_data["prices15m_czk_kwh"]
        return prices_15m.get(time_key)

    async def get_spot_prices(
        self, date: Optional[datetime] = None, force_today_only: bool = False
    ) -> Dict[str, Any]:
        """
        Stáhne DAM PT15M, agreguje na hodiny průměrem.
        - Před 13:00 (nebo force_today_only) bere jen dnešek.
        - Po 13:00 bere včera/dnes/zítra.
        """
        if date is None:
            date = datetime.now(tz=self.timezone)

        # Pokud máme validní cache (dnešek + případně zítřek po 13h), použij ji
        if self._is_cache_valid():
            _LOGGER.debug(
                "Using cached spot prices (valid for today%s)",
                " and tomorrow" if datetime.now(self.timezone).hour >= 13 else "",
            )
            return self._last_data

        # Cache není validní - chybí data, musíme stáhnout z OTE
        _LOGGER.info(
            "Cache missing required data - fetching from OTE (hour=%d)",
            datetime.now(self.timezone).hour,
        )

        try:
            eur_czk_rate = await self.get_cnb_exchange_rate()
            if not eur_czk_rate:
                _LOGGER.warning("No CNB rate available, using default 25.0")
                eur_czk_rate = 25.0

            now = datetime.now(tz=self.timezone)
            if force_today_only or now.hour < 13:
                start_date = date.date()
                end_date = date.date()
                _LOGGER.info(f"Fetching PT15M prices for today only: {start_date}")
            else:
                start_date = date.date() - timedelta(days=1)
                end_date = date.date() + timedelta(days=1)
                _LOGGER.info(f"Fetching PT15M prices for {start_date} to {end_date}")

            # 1) stáhni 15m a připrav i agregované hodiny
            qh_eur_kwh = await self._get_dam_period_prices(start_date, end_date)
            if not qh_eur_kwh:
                _LOGGER.warning("No DAM PT15M data found.")
                return {}

            hourly_eur_kwh = self._aggregate_quarter_to_hour(qh_eur_kwh)

            # 2) přepočty na CZK/kWh
            qh_czk_kwh: Dict[datetime, float] = {
                dt: float(val) * eur_czk_rate for dt, val in qh_eur_kwh.items()
            }
            hourly_czk_kwh: Dict[datetime, float] = {
                dt: float(val) * eur_czk_rate for dt, val in hourly_eur_kwh.items()
            }

            # 3) formát výsledku (primárně hodinové klíče; 15m přidány aditivně)
            data = await self._format_spot_data(
                hourly_czk_kwh,
                hourly_eur_kwh,
                eur_czk_rate,
                date,
                qh_rates_czk=qh_czk_kwh,
                qh_rates_eur=qh_eur_kwh,
            )

            if data:
                self._last_data = data
                self._cache_time = datetime.now(self.timezone)
                await self.async_persist_cache()
                return data

        except Exception as e:
            _LOGGER.error(f"Error fetching spot prices from OTE: {e}", exc_info=True)
            # Fallback na cached data pokud existují
            if self._last_data:
                _LOGGER.warning(
                    "OTE nedostupné - používám cached data z %s",
                    self._cache_time.isoformat() if self._cache_time else "unknown",
                )
                return self._last_data

        return {}

    async def _format_spot_data(
        self,
        hourly_czk: Dict[datetime, float],
        hourly_eur_kwh: Dict[datetime, Decimal],
        eur_czk_rate: float,
        reference_date: datetime,
        qh_rates_czk: Optional[Dict[datetime, float]] = None,
        qh_rates_eur: Optional[Dict[datetime, Decimal]] = None,
    ) -> Dict[str, Any]:
        """Sestaví výsledek – hlavní výstup jsou hodinové ceny; 15m jsou přiloženy aditivně."""
        today = reference_date.date()
        tomorrow = today + timedelta(days=1)

        prices_czk_kwh: Dict[str, float] = {}
        prices_eur_mwh: Dict[str, float] = {}

        today_prices_czk: List[float] = []
        tomorrow_prices_czk: List[float] = []

        for dt, price_czk in hourly_czk.items():
            local_dt = dt.astimezone(self.timezone)
            price_date = local_dt.date()

            time_key = f"{price_date.strftime('%Y-%m-%d')}T{local_dt.hour:02d}:00:00"

            prices_czk_kwh[time_key] = round(price_czk, 4)
            prices_eur_mwh[time_key] = round(float(hourly_eur_kwh[dt]) * 1000.0, 2)

            if price_date == today:
                today_prices_czk.append(price_czk)
            elif price_date == tomorrow:
                tomorrow_prices_czk.append(price_czk)

        if not prices_czk_kwh:
            return {}

        all_prices_czk = today_prices_czk + tomorrow_prices_czk

        result: Dict[str, Any] = {
            "date": today.strftime("%Y-%m-%d"),
            "prices_czk_kwh": prices_czk_kwh,  # agregované hodiny v CZK/kWh
            "prices_eur_mwh": prices_eur_mwh,  # agregované hodiny v EUR/MWh
            "eur_czk_rate": eur_czk_rate,
            "rate_source": "ČNB",
            "average_price_czk": (
                round(sum(all_prices_czk) / len(all_prices_czk), 4)
                if all_prices_czk
                else None
            ),
            "min_price_czk": round(min(all_prices_czk), 4) if all_prices_czk else None,
            "max_price_czk": round(max(all_prices_czk), 4) if all_prices_czk else None,
            "source": "OTE SOAP API (DAM PT15M) + ČNB kurz",
            "updated": datetime.now().isoformat(),
            "hours_count": len(prices_czk_kwh),
            "date_range": {
                "from": (min(prices_czk_kwh.keys()) if prices_czk_kwh else None),
                "to": (max(prices_czk_kwh.keys()) if prices_czk_kwh else None),
            },
            "today_stats": (
                {
                    "avg_czk": round(sum(today_prices_czk) / len(today_prices_czk), 4),
                    "min_czk": round(min(today_prices_czk), 4),
                    "max_czk": round(max(today_prices_czk), 4),
                }
                if today_prices_czk
                else None
            ),
            "tomorrow_stats": (
                {
                    "avg_czk": round(
                        sum(tomorrow_prices_czk) / len(tomorrow_prices_czk), 4
                    ),
                    "min_czk": round(min(tomorrow_prices_czk), 4),
                    "max_czk": round(max(tomorrow_prices_czk), 4),
                }
                if tomorrow_prices_czk
                else None
            ),
        }

        # aditivně přidáme 15m (můžeš klidně smazat, pokud nechceš)
        if qh_rates_czk and qh_rates_eur:
            qh_prices_czk_kwh: Dict[str, float] = {}
            qh_prices_eur_mwh: Dict[str, float] = {}

            for dt, price_czk in qh_rates_czk.items():
                local_dt = dt.astimezone(self.timezone)
                price_date = local_dt.date()

                time_key = f"{price_date.strftime('%Y-%m-%d')}T{local_dt.hour:02d}:{local_dt.minute:02d}:00"
                qh_prices_czk_kwh[time_key] = round(price_czk, 4)
                qh_prices_eur_mwh[time_key] = round(float(qh_rates_eur[dt]) * 1000.0, 2)

            result["prices15m_czk_kwh"] = qh_prices_czk_kwh
            result["prices15m_eur_mwh"] = qh_prices_eur_mwh

        return result
