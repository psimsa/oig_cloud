"""OTE (Operator trhu s elektřinou) API pro stahování spotových cen elektřiny."""

import logging
import aiohttp
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date, time, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Any, TypedDict, cast
from decimal import Decimal
import asyncio

_LOGGER = logging.getLogger(__name__)

# SOAP query template pro elektřinu
QUERY_ELECTRICITY = """<?xml version="1.0" encoding="UTF-8" ?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:pub="http://www.ote-cr.cz/schema/service/public">
    <soapenv:Header/>
    <soapenv:Body>
        <pub:GetDamPriceE>
            <pub:StartDate>{start}</pub:StartDate>
            <pub:EndDate>{end}</pub:EndDate>
            <pub:InEur>{in_eur}</pub:InEur>
        </pub:GetDamPriceE>
    </soapenv:Body>
</soapenv:Envelope>
"""


class OTEFault(Exception):
    """Výjimka pro chyby OTE API."""

    pass


class InvalidDateError(Exception):
    """Exception raised for invalid date format in CNB API response."""

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
    rates: list[Rate]


class RateError(TypedDict):
    description: str
    errorCode: str
    happenedAt: str
    endPoint: str
    messageId: str


class CnbRate:
    """Třída pro získávání kurzů z ČNB API."""

    RATES_URL: str = "https://api.cnb.cz/cnbapi/exrates/daily"

    def __init__(self) -> None:
        self._timezone: ZoneInfo = ZoneInfo("Europe/Prague")
        self._rates: Dict[str, Decimal] = {}
        self._last_checked_date: Optional[date] = None

    async def download_rates(self, day: date) -> Rates:
        """Stažení kurzů pro daný den."""
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
        """Získání kurzů pro daný den."""
        rates: Dict[str, Decimal] = {
            "CZK": Decimal(1),
        }

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
        """Získání aktuálních kurzů."""
        now = datetime.now(timezone.utc)
        day = now.astimezone(self._timezone).date()

        # Update if needed
        if self._last_checked_date is None or day != self._last_checked_date:
            self._rates = await self.get_day_rates(day)
            self._last_checked_date = day

        return self._rates


class OteApi:
    """API pro stahování dat z OTE."""

    OTE_PUBLIC_URL = "https://www.ote-cr.cz/services/PublicDataService"

    def __init__(self) -> None:
        """Inicializace OTE API."""
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_data: Dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None
        self._eur_czk_rate: Optional[float] = None
        self._rate_cache_time: Optional[datetime] = None
        self.timezone = ZoneInfo("Europe/Prague")
        self.utc = ZoneInfo("UTC")
        self._cnb_rate = CnbRate()

    def _is_cache_valid(self) -> bool:
        """Kontrola platnosti cache - data jsou platná do večera."""
        if not self._cache_time or not self._last_data:
            return False

        now = datetime.now()
        cache_date = self._cache_time.date()
        current_date = now.date()

        # Cache je platný celý den
        if cache_date == current_date:
            # Po 13:00 zkontrolujeme, jestli máme zítřejší data
            if now.hour >= 13:
                tomorrow_available = bool(self._last_data.get("tomorrow_stats"))
                if not tomorrow_available:
                    _LOGGER.debug("Cache invalid - no tomorrow data after 13:00")
                    return False
            return True

        return False

    def _is_rate_cache_valid(self) -> bool:
        """Kontrola platnosti cache kurzů."""
        if not self._rate_cache_time or not self._eur_czk_rate:
            return False

        now = datetime.now()
        cache_date = self._rate_cache_time.date()
        current_date = now.date()

        return cache_date == current_date

    def _get_electricity_query(self, start: date, end: date, in_eur: bool) -> str:
        """Vytvoření SOAP query pro elektřinu."""
        return QUERY_ELECTRICITY.format(
            start=start.isoformat(),
            end=end.isoformat(),
            in_eur="true" if in_eur else "false",
        )

    async def _download_soap(self, query: str) -> str:
        """Stažení dat přes SOAP."""
        try:
            async with self._get_session() as session:
                async with session.post(self.OTE_PUBLIC_URL, data=query) as response:
                    if response.status == 200:
                        return await response.text()
                    else:
                        raise OTEFault(
                            f"SOAP request failed with status {response.status}"
                        )
        except aiohttp.ClientError as e:
            raise OTEFault(f"Unable to download rates: {e}")

    def _parse_soap_response(self, text: str) -> ET.Element:
        """Parsování SOAP odpovědi."""
        try:
            root = ET.fromstring(text)

            # Kontrola na SOAP chyby
            fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
            if fault:
                faultstring = fault.find("faultstring")
                error = "Unknown SOAP error"
                if faultstring is not None:
                    error = faultstring.text or error
                raise OTEFault(error)

            return root

        except ET.ParseError as e:
            if "Application is not available" in text:
                raise OTEFault("OTE Portal is currently not available!") from e
            raise OTEFault("Failed to parse SOAP response.") from e

    async def get_cnb_exchange_rate(self) -> Optional[float]:
        """Získání kurzu EUR/CZK z ČNB API."""
        if self._is_rate_cache_valid():
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
            else:
                _LOGGER.warning("EUR rate not found in CNB response")

        except Exception as e:
            _LOGGER.warning(f"Error fetching CNB rate: {e}")

        return None

    async def get_current_spot_price(self) -> Optional[float]:
        """Získání aktuální spotové ceny pro současnou hodinu."""
        data = await self.get_spot_prices()
        if not data or "prices_czk_kwh" not in data:
            return None

        now = datetime.now()
        current_hour_key = f"{now.strftime('%Y-%m-%d')}T{now.hour:02d}:00:00"

        return data["prices_czk_kwh"].get(current_hour_key)

    async def get_spot_prices(self, date: Optional[datetime] = None) -> Dict[str, Any]:
        """Stažení spotových cen pro daný den z OTE SOAP API."""
        if date is None:
            date = datetime.now(tz=self.timezone)

        # Cache kontrola
        if self._is_cache_valid():
            _LOGGER.debug("Using cached spot prices from OTE SOAP API")
            return self._last_data

        try:
            # Získáme kurz EUR/CZK
            eur_czk_rate = await self.get_cnb_exchange_rate()
            if not eur_czk_rate:
                _LOGGER.warning("No CNB rate available, using default 25.0")
                eur_czk_rate = 25.0

            # Stáhneme data pro včera, dnes a zítra
            start_date = date.date() - timedelta(days=1)
            end_date = date.date() + timedelta(days=1)

            _LOGGER.info(
                f"Fetching spot prices from OTE SOAP API for {start_date} to {end_date}"
            )

            # Získáme data v EUR
            query = self._get_electricity_query(start_date, end_date, in_eur=True)
            soap_response = await self._download_soap(query)
            root = self._parse_soap_response(soap_response)

            # Parsujeme hodinové ceny
            rates_eur = await self._parse_electricity_rates(root, unit="kWh")

            # Převedeme na CZK
            rates_czk = {}
            for dt, price_eur in rates_eur.items():
                rates_czk[dt] = float(price_eur) * eur_czk_rate

            # Zpracujeme data do našeho formátu
            data = await self._format_spot_data(
                rates_czk, rates_eur, eur_czk_rate, date
            )

            if data:
                self._last_data = data
                self._cache_time = datetime.now()
                hours_count = data.get("hours_count", 0)
                tomorrow_available = bool(data.get("tomorrow_stats"))
                _LOGGER.info(
                    f"Successfully fetched spot prices: {hours_count} hours, tomorrow data: {'yes' if tomorrow_available else 'no'}"
                )
                return data

        except Exception as e:
            _LOGGER.error(f"Error fetching spot prices: {e}", exc_info=True)

        return {}

    async def _parse_electricity_rates(
        self, root: ET.Element, unit: str
    ) -> Dict[datetime, Decimal]:
        """Parsování hodinových cen z SOAP odpovědi."""
        result: Dict[datetime, Decimal] = {}

        for item in root.findall(".//{http://www.ote-cr.cz/schema/service/public}Item"):
            date_el = item.find("{http://www.ote-cr.cz/schema/service/public}Date")
            if date_el is None or date_el.text is None:
                continue

            current_date = date.fromisoformat(date_el.text)

            hour_el = item.find("{http://www.ote-cr.cz/schema/service/public}Hour")
            if hour_el is None or hour_el.text is None:
                current_hour = 0
            else:
                current_hour = (
                    int(hour_el.text) - 1
                )  # OTE používá 1-24, my potřebujeme 0-23

            price_el = item.find("{http://www.ote-cr.cz/schema/service/public}Price")
            if price_el is None or price_el.text is None:
                continue

            current_price = Decimal(price_el.text)

            if unit == "kWh":
                # API vrací cenu za MWh, převedeme na kWh
                current_price /= Decimal(1000)

            # Převedeme na datetime s timezone
            start_of_day = datetime.combine(current_date, time(0), tzinfo=self.timezone)
            dt = start_of_day.astimezone(self.utc) + timedelta(hours=current_hour)

            result[dt] = current_price

        return result

    async def _format_spot_data(
        self,
        rates_czk: Dict[datetime, float],
        rates_eur: Dict[datetime, Decimal],
        eur_czk_rate: float,
        reference_date: datetime,
    ) -> Dict[str, Any]:
        """Formátování dat do našeho standardního formátu."""
        today = reference_date.date()
        tomorrow = today + timedelta(days=1)

        hourly_prices_czk_kwh = {}
        hourly_prices_eur_mwh = {}

        today_prices_czk = []
        tomorrow_prices_czk = []

        for dt, price_czk in rates_czk.items():
            # Převedeme UTC datetime na lokální čas pro klíč
            local_dt = dt.astimezone(self.timezone)
            price_date = local_dt.date()

            time_key = f"{price_date.strftime('%Y-%m-%d')}T{local_dt.hour:02d}:00:00"

            # Cena v CZK/kWh
            hourly_prices_czk_kwh[time_key] = round(price_czk, 4)

            # Cena v EUR/MWh (zpětný převod)
            price_eur_mwh = float(rates_eur[dt]) * 1000.0  # EUR/kWh -> EUR/MWh
            hourly_prices_eur_mwh[time_key] = round(price_eur_mwh, 2)

            # Statistiky podle dnů
            if price_date == today:
                today_prices_czk.append(price_czk)
            elif price_date == tomorrow:
                tomorrow_prices_czk.append(price_czk)

        if not today_prices_czk:
            return {}

        # Sestavíme výsledek
        all_prices_czk = today_prices_czk + tomorrow_prices_czk

        result = {
            "date": today.strftime("%Y-%m-%d"),
            "prices_czk_kwh": hourly_prices_czk_kwh,
            "prices_eur_mwh": hourly_prices_eur_mwh,
            "eur_czk_rate": eur_czk_rate,
            "rate_source": "ČNB",
            "average_price_czk": round(sum(all_prices_czk) / len(all_prices_czk), 4),
            "min_price_czk": round(min(all_prices_czk), 4),
            "max_price_czk": round(max(all_prices_czk), 4),
            "source": "OTE SOAP API + ČNB kurz",
            "updated": datetime.now().isoformat(),
            "hours_count": len(hourly_prices_czk_kwh),
            "date_range": {
                "from": (
                    min(hourly_prices_czk_kwh.keys()) if hourly_prices_czk_kwh else None
                ),
                "to": (
                    max(hourly_prices_czk_kwh.keys()) if hourly_prices_czk_kwh else None
                ),
            },
            "today_stats": {
                "avg_czk": round(sum(today_prices_czk) / len(today_prices_czk), 4),
                "min_czk": round(min(today_prices_czk), 4),
                "max_czk": round(max(today_prices_czk), 4),
            },
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

        return result

    async def _get_session(self) -> aiohttp.ClientSession:
        """Získání HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60),
                headers={
                    "User-Agent": "HomeAssistant OIG Cloud Integration",
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": "",
                },
            )
        return self._session

    async def close(self) -> None:
        """Uzavření session."""
        if self._session and not self._session.closed:
            await self._session.close()
