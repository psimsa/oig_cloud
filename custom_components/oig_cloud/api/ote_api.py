"""OTE (Operator trhu s elektřinou) API pro stahování spotových cen elektřiny."""

import logging
import aiohttp
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

_LOGGER = logging.getLogger(__name__)


class OteApi:
    """API pro stahování dat z OTE."""

    BASE_URL = "https://spotovaelektrina.cz/api/v1/price/get-prices-json"

    def __init__(self) -> None:
        """Inicializace OTE API."""
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_data: Dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None

    def _is_cache_valid(self) -> bool:
        """Kontrola platnosti cache - data jsou platná do večera."""
        if not self._cache_time or not self._last_data:
            return False

        now = datetime.now()
        cache_date = self._cache_time.date()
        current_date = now.date()

        # Cache je platný celý den
        if cache_date == current_date:
            # Dodatečná kontrola - pokud je po 13:00 a data nejsou kompletní, invalidovat cache
            if now.hour >= 13:
                hours_count = self._last_data.get("hours_count", 0)
                if (
                    hours_count < 24
                ):  # Očekáváme 24 hodin (dnes) nebo více (dnes + zítřek)
                    _LOGGER.debug(f"Cache invalid - insufficient hours: {hours_count}")
                    return False
            return True

        # Pokud je nový den, cache není platný
        return False

    async def get_spot_prices(self, date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Stažení spotových cen pro daný den.

        Args:
            date: Datum pro které chceme data (ignorováno - API vrací vždy aktuální data)

        Returns:
            Dict s hodinovými cenami v CZK/kWh a EUR/MWh
        """
        # Cache - pokud máme čerstvá data pro dnešek
        if self._is_cache_valid():
            _LOGGER.debug("Using cached spot prices from spotovaelektrina.cz")
            return self._last_data

        try:
            _LOGGER.info(f"Fetching spot prices from: {self.BASE_URL}")

            async with self._get_session() as session:
                async with session.get(self.BASE_URL) as response:
                    if response.status == 200:
                        content = await response.text()
                        data = self._parse_spot_data(content)

                        if data:
                            self._last_data = data
                            self._cache_time = datetime.now()
                            hours_count = data.get("hours_count", 0)
                            tomorrow_available = bool(data.get("tomorrow_stats"))
                            _LOGGER.info(
                                f"Successfully fetched spot prices: {hours_count} hours, tomorrow data: {'yes' if tomorrow_available else 'no'}"
                            )
                            return data
                    else:
                        _LOGGER.error(f"Spot API returned status {response.status}")

        except Exception as e:
            _LOGGER.error(f"Error fetching spot prices: {e}", exc_info=True)

        return {}

    def _parse_spot_data(self, content: str) -> Dict[str, Any]:
        """
        Parsování JSON dat ze spotovaelektrina.cz API.

        Returns:
            Dict s hodinovými cenami a metadata
        """
        try:
            data = json.loads(content)

            # Konverze na náš formát
            hourly_prices_czk_kwh = {}
            hourly_prices_eur_mwh = {}

            # Zpracování dnešních hodin
            today = datetime.now().date()
            today_prices_czk = []
            today_prices_eur = []

            if "hoursToday" in data:
                for hour_data in data["hoursToday"]:
                    hour = hour_data["hour"]
                    # OPRAVA: priceCZK je už v halířích -> převod na CZK/kWh
                    price_czk = hour_data["priceCZK"] / 1000.0  # halíře -> CZK/kWh
                    # OPRAVA: priceEur je v EUR/MWh -> převod na EUR/kWh
                    price_eur_kwh = hour_data["priceEur"] / 1000.0  # EUR/MWh -> EUR/kWh
                    price_eur_mwh = hour_data["priceEur"]  # Původní hodnota v EUR/MWh

                    time_key = f"{today.strftime('%Y-%m-%d')}T{hour:02d}:00:00"
                    hourly_prices_czk_kwh[time_key] = round(price_czk, 4)
                    hourly_prices_eur_mwh[time_key] = round(price_eur_mwh, 2)

                    today_prices_czk.append(price_czk)
                    today_prices_eur.append(price_eur_kwh)

            # Zpracování zítřejších hodin
            tomorrow = today + timedelta(days=1)
            tomorrow_prices_czk = []
            tomorrow_prices_eur = []

            if "hoursTomorrow" in data:
                for hour_data in data["hoursTomorrow"]:
                    hour = hour_data["hour"]
                    price_czk = hour_data["priceCZK"] / 1000.0
                    price_eur_kwh = hour_data["priceEur"] / 1000.0  # EUR/MWh -> EUR/kWh
                    price_eur_mwh = hour_data["priceEur"]  # Původní hodnota v EUR/MWh

                    time_key = f"{tomorrow.strftime('%Y-%m-%d')}T{hour:02d}:00:00"
                    hourly_prices_czk_kwh[time_key] = round(price_czk, 4)
                    hourly_prices_eur_mwh[time_key] = round(price_eur_mwh, 2)

                    tomorrow_prices_czk.append(price_czk)
                    tomorrow_prices_eur.append(price_eur_kwh)

            # Výpočet statistik (v kWh jednotkách)
            all_prices_czk = today_prices_czk + tomorrow_prices_czk
            all_prices_eur = today_prices_eur + tomorrow_prices_eur

            if not all_prices_czk:
                return {}

            result = {
                "date": today.strftime("%Y-%m-%d"),
                "prices_czk_kwh": hourly_prices_czk_kwh,
                "prices_eur_mwh": hourly_prices_eur_mwh,  # Zachováváme původní MWh pro referenci
                "average_price_czk": round(
                    sum(all_prices_czk) / len(all_prices_czk), 4
                ),
                "average_price_eur_kwh": round(
                    sum(all_prices_eur) / len(all_prices_eur), 4
                ),
                "min_price_czk": round(min(all_prices_czk), 4),
                "max_price_czk": round(max(all_prices_czk), 4),
                "min_price_eur_kwh": round(min(all_prices_eur), 4),
                "max_price_eur_kwh": round(max(all_prices_eur), 4),
                "source": "spotovaelektrina.cz",
                "updated": datetime.now().isoformat(),
                "hours_count": len(hourly_prices_czk_kwh),
                "date_range": {
                    "from": (
                        min(hourly_prices_czk_kwh.keys())
                        if hourly_prices_czk_kwh
                        else None
                    ),
                    "to": (
                        max(hourly_prices_czk_kwh.keys())
                        if hourly_prices_czk_kwh
                        else None
                    ),
                },
                "today_stats": {
                    "avg_czk": (
                        round(sum(today_prices_czk) / len(today_prices_czk), 4)
                        if today_prices_czk
                        else 0
                    ),
                    "min_czk": (
                        round(min(today_prices_czk), 4) if today_prices_czk else 0
                    ),
                    "max_czk": (
                        round(max(today_prices_czk), 4) if today_prices_czk else 0
                    ),
                },
                "tomorrow_stats": (
                    {
                        "avg_czk": (
                            round(
                                sum(tomorrow_prices_czk) / len(tomorrow_prices_czk), 4
                            )
                            if tomorrow_prices_czk
                            else 0
                        ),
                        "min_czk": (
                            round(min(tomorrow_prices_czk), 4)
                            if tomorrow_prices_czk
                            else 0
                        ),
                        "max_czk": (
                            round(max(tomorrow_prices_czk), 4)
                            if tomorrow_prices_czk
                            else 0
                        ),
                    }
                    if tomorrow_prices_czk
                    else None
                ),
            }

            # Přidat level informace z API
            result["hourly_levels"] = {}
            if "hoursToday" in data:
                for hour_data in data["hoursToday"]:
                    hour = hour_data["hour"]
                    time_key = f"{today.strftime('%Y-%m-%d')}T{hour:02d}:00:00"
                    result["hourly_levels"][time_key] = {
                        "level": hour_data["level"],
                        "level_num": hour_data["levelNum"],
                    }

            if "hoursTomorrow" in data:
                for hour_data in data["hoursTomorrow"]:
                    hour = hour_data["hour"]
                    time_key = f"{tomorrow.strftime('%Y-%m-%d')}T{hour:02d}:00:00"
                    result["hourly_levels"][time_key] = {
                        "level": hour_data["level"],
                        "level_num": hour_data["levelNum"],
                    }

            _LOGGER.debug(
                f"Parsed {len(hourly_prices_czk_kwh)} hourly prices from spot API"
            )
            _LOGGER.debug(
                f"Sample price conversion: API={data['hoursToday'][0]['priceCZK']} halíře/MWh -> {hourly_prices_czk_kwh[list(hourly_prices_czk_kwh.keys())[0]]} CZK/kWh"
            )
            return result

        except Exception as e:
            _LOGGER.error(f"Error parsing spot data: {e}", exc_info=True)
            return {}

    async def _get_session(self) -> aiohttp.ClientSession:
        """Získání HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "HomeAssistant OIG Cloud Integration"},
            )
        return self._session

    async def close(self) -> None:
        """Uzavření session."""
        if self._session and not self._session.closed:
            await self._session.close()
