"""Analytics senzor pro spotové ceny a další analytické funkce."""

import logging
from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional, List, Tuple, Union  # PŘIDÁNO: Union

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .oig_cloud_sensor import OigCloudSensor

_LOGGER = logging.getLogger(__name__)


class OigCloudAnalyticsSensor(OigCloudSensor):
    """Analytics senzor pro spotové ceny a analytické funkce."""

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        entry: ConfigEntry,
        device_info: Dict[str, Any],  # PŘIDÁNO: přebíráme device_info jako parametr
    ) -> None:
        """Initialize the analytics sensor."""
        super().__init__(coordinator, sensor_type)
        self._entry = entry
        self._device_info = device_info  # OPRAVA: použijeme předané device_info

        # Debug logování při inicializaci
        _LOGGER.debug(f"💰 Initializing analytics sensor: {sensor_type}")

        # OPRAVA: Získáme inverter_sn ze správného místa (stejně jako solar forecast)
        inverter_sn = "unknown"

        # Zkusíme získat z coordinator.config_entry.data
        if hasattr(coordinator, "config_entry") and coordinator.config_entry.data:
            inverter_sn = coordinator.config_entry.data.get("inverter_sn", "unknown")

        # Pokud stále unknown, zkusíme z coordinator.data
        if inverter_sn == "unknown" and coordinator.data:
            first_device_key = list(coordinator.data.keys())[0]
            inverter_sn = first_device_key

        # OPRAVA: Nastavit _box_id a entity_id podle vzoru z computed sensors
        self._box_id = inverter_sn
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"

        # OPRAVA: Přímý import SENSOR_TYPES_SPOT (ale používáme SENSOR_TYPES pattern)
        from .sensors.SENSOR_TYPES_SPOT import SENSOR_TYPES_SPOT

        sensor_config = SENSOR_TYPES_SPOT.get(sensor_type, {})

        name_cs = sensor_config.get("name_cs")
        name_en = sensor_config.get("name")

        # Preferujeme český název, fallback na anglický, fallback na sensor_type
        self._attr_name = name_cs or name_en or sensor_type

    @property
    def device_info(self) -> Optional[Dict[str, Any]]:
        """Return device info."""
        return self._device_info

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        # OPRAVA: Kontrola dostupnosti na začátku
        if not self.available:
            _LOGGER.debug(f"💰 [{self.entity_id}] Not available, returning None")
            return None

        # Debug - zkontrolujme coordinator data
        _LOGGER.debug(
            f"💰 [{self.entity_id}] Coordinator data keys: {list(self.coordinator.data.keys()) if self.coordinator.data else 'None'}"
        )

        # Pro tarifní senzor
        if self._sensor_type == "current_tariff":
            return self._calculate_current_tariff()

        # OPRAVA: Načíst spotové ceny z coordinator.data místo ote_api.spot_data
        if self.coordinator.data and "spot_prices" in self.coordinator.data:
            spot_data = self.coordinator.data["spot_prices"]
            _LOGGER.debug(
                f"💰 [{self.entity_id}] Spot data keys: {list(spot_data.keys()) if spot_data else 'None'}"
            )
            return self._get_spot_price_value(spot_data)
        else:
            _LOGGER.debug(f"💰 [{self.entity_id}] No spot_prices in coordinator data")

        return None

    def _parse_tariff_times(self, time_str: str) -> List[int]:
        """Parse tariff time string into list of hours."""
        if not time_str.strip():
            return []
        try:
            return [int(h.strip()) for h in time_str.split(",") if h.strip()]
        except (ValueError, AttributeError):
            return []

    def _calculate_current_tariff(self) -> str:
        """Calculate current tariff based on time and day."""
        # Pokud není dvoutarifní sazba povolena, vždy vracíme VT
        dual_tariff_enabled = self._entry.options.get("dual_tariff_enabled", True)
        if not dual_tariff_enabled:
            return "VT"

        current_time = dt_util.now()
        is_weekend = current_time.weekday() >= 5  # sobota=5, neděle=6
        options = self._entry.options

        # Získání tarifních časů
        if is_weekend:
            nt_times = self._parse_tariff_times(
                options.get("tariff_nt_start_weekend", "0")
            )
            vt_times = self._parse_tariff_times(
                options.get("tariff_vt_start_weekend", "")
            )
        else:
            nt_times = self._parse_tariff_times(
                options.get("tariff_nt_start_weekday", "22,2")
            )
            vt_times = self._parse_tariff_times(
                options.get("tariff_vt_start_weekday", "6")
            )

        current_hour = current_time.hour

        # Najdi poslední platnou změnu tarifu
        last_tariff = "NT"  # Default
        last_hour = -1

        # Zkontroluj změny dnes
        all_changes: List[Tuple[int, str]] = []
        for hour in nt_times:
            all_changes.append((hour, "NT"))
        for hour in vt_times:
            all_changes.append((hour, "VT"))

        all_changes.sort(reverse=True)  # Od největší hodiny

        for hour, tariff in all_changes:
            if hour <= current_hour and hour > last_hour:
                last_tariff = tariff
                last_hour = hour

        # Pokud žádná změna dnes, zkontroluj včerejšek
        if last_hour == -1:
            yesterday = current_time.date() - timedelta(days=1)
            is_yesterday_weekend = yesterday.weekday() >= 5

            if is_yesterday_weekend:
                nt_times_yesterday = self._parse_tariff_times(
                    options.get("tariff_nt_start_weekend", "0")
                )
                vt_times_yesterday = self._parse_tariff_times(
                    options.get("tariff_vt_start_weekend", "")
                )
            else:
                nt_times_yesterday = self._parse_tariff_times(
                    options.get("tariff_nt_start_weekday", "22,2")
                )
                vt_times_yesterday = self._parse_tariff_times(
                    options.get("tariff_vt_start_weekday", "6")
                )

            yesterday_changes: List[Tuple[int, str]] = []
            for hour in nt_times_yesterday:
                yesterday_changes.append((hour, "NT"))
            for hour in vt_times_yesterday:
                yesterday_changes.append((hour, "VT"))

            yesterday_changes.sort(reverse=True)

            for hour, tariff in yesterday_changes:
                last_tariff = tariff
                break

        return last_tariff

    def _get_next_tariff_change(
        self, current_time: datetime, is_weekend: bool
    ) -> Tuple[str, datetime]:
        """Get next tariff change time and type."""
        # Pokud není dvoutarifní sazba povolena, žádné změny
        dual_tariff_enabled = self._entry.options.get("dual_tariff_enabled", True)
        if not dual_tariff_enabled:
            return "VT", current_time + timedelta(
                days=365
            )  # Žádná změna v dohledné době

        options = self._entry.options

        # Získání tarifních časů podle dne
        if is_weekend:
            nt_times = self._parse_tariff_times(
                options.get("tariff_nt_start_weekend", "0")
            )
            vt_times = self._parse_tariff_times(
                options.get("tariff_vt_start_weekend", "")
            )
        else:
            nt_times = self._parse_tariff_times(
                options.get("tariff_nt_start_weekday", "22,2")
            )
            vt_times = self._parse_tariff_times(
                options.get("tariff_vt_start_weekday", "6")
            )

        current_hour = current_time.hour
        today = current_time.date()

        # Kombinuj všechny změny tarifu pro dnes
        changes_today: List[Tuple[int, str]] = []
        for hour in nt_times:
            changes_today.append((hour, "NT"))
        for hour in vt_times:
            changes_today.append((hour, "VT"))

        # Seřaď podle času
        changes_today.sort()

        # Najdi další změnu dnes
        for hour, tariff in changes_today:
            if hour > current_hour:
                next_change = datetime.combine(today, time(hour, 0))
                return tariff, next_change

        # Žádná změna dnes, hledej zítra
        tomorrow = today + timedelta(days=1)
        is_tomorrow_weekend = tomorrow.weekday() >= 5

        # Tarifní časy pro zítra
        if is_tomorrow_weekend:
            nt_times_tomorrow = self._parse_tariff_times(
                options.get("tariff_nt_start_weekend", "0")
            )
            vt_times_tomorrow = self._parse_tariff_times(
                options.get("tariff_vt_start_weekend", "")
            )
        else:
            nt_times_tomorrow = self._parse_tariff_times(
                options.get("tariff_nt_start_weekday", "22,2")
            )
            vt_times_tomorrow = self._parse_tariff_times(
                options.get("tariff_vt_start_weekday", "6")
            )

        changes_tomorrow: List[Tuple[int, str]] = []
        for hour in nt_times_tomorrow:
            changes_tomorrow.append((hour, "NT"))
        for hour in vt_times_tomorrow:
            changes_tomorrow.append((hour, "VT"))

        changes_tomorrow.sort()

        if changes_tomorrow:
            hour, tariff = changes_tomorrow[0]
            next_change = datetime.combine(tomorrow, time(hour, 0))
            return tariff, next_change

        # Fallback - žádné změny
        return "NT", current_time + timedelta(hours=1)

    def _calculate_tariff_intervals(
        self, current_time: datetime
    ) -> Dict[str, List[str]]:
        """Calculate NT and VT intervals for today and tomorrow."""
        intervals: Dict[str, List[str]] = {"NT": [], "VT": []}

        # Pokud není dvoutarifní sazba povolena, celý den je VT
        dual_tariff_enabled = self._entry.options.get("dual_tariff_enabled", True)
        if not dual_tariff_enabled:
            for day_offset in [0, 1]:  # Dnes a zítra
                check_date = current_time.date() + timedelta(days=day_offset)
                interval_str = f"{check_date.strftime('%d.%m')} 00:00-24:00"
                intervals["VT"].append(interval_str)
            return intervals

        for day_offset in [0, 1]:  # Dnes a zítra
            check_date = current_time.date() + timedelta(days=day_offset)
            is_weekend = check_date.weekday() >= 5
            options = self._entry.options

            # Získání tarifních časů
            if is_weekend:
                nt_times = self._parse_tariff_times(
                    options.get("tariff_nt_start_weekend", "0")
                )
                vt_times = self._parse_tariff_times(
                    options.get("tariff_vt_start_weekend", "")
                )
            else:
                nt_times = self._parse_tariff_times(
                    options.get("tariff_nt_start_weekday", "22,2")
                )
                vt_times = self._parse_tariff_times(
                    options.get("tariff_vt_start_weekday", "6")
                )

            # Vytvoř seznam všech změn pro den
            all_changes: List[Tuple[int, str]] = []
            for hour in nt_times:
                all_changes.append((hour, "NT"))
            for hour in vt_times:
                all_changes.append((hour, "VT"))

            all_changes.sort()

            # Zpracuj intervaly
            if all_changes:
                for i, (start_hour, tariff) in enumerate(all_changes):
                    if i < len(all_changes) - 1:
                        end_hour = all_changes[i + 1][0]
                    else:
                        # Poslední interval dne - pokračuje do dalšího dne
                        end_hour = 24

                    start_time = f"{start_hour:02d}:00"
                    end_time = f"{end_hour:02d}:00" if end_hour < 24 else "24:00"

                    interval_str = (
                        f"{check_date.strftime('%d.%m')} {start_time}-{end_time}"
                    )
                    intervals[tariff].append(interval_str)
            else:
                # Žádné změny = celý den NT
                interval_str = f"{check_date.strftime('%d.%m')} 00:00-24:00"
                intervals["NT"].append(interval_str)

        return intervals

    def _get_tariff_for_datetime(self, target_datetime: datetime) -> str:
        """Get tariff (VT/NT) for specific datetime."""
        # Pokud není dvoutarifní sazba povolena, vždy vracíme VT
        dual_tariff_enabled = self._entry.options.get("dual_tariff_enabled", True)
        if not dual_tariff_enabled:
            return "VT"

        is_weekend = target_datetime.weekday() >= 5  # sobota=5, neděle=6
        options = self._entry.options

        # Získání tarifních časů
        if is_weekend:
            nt_times = self._parse_tariff_times(
                options.get("tariff_nt_start_weekend", "0")
            )
            vt_times = self._parse_tariff_times(
                options.get("tariff_vt_start_weekend", "")
            )
        else:
            nt_times = self._parse_tariff_times(
                options.get("tariff_nt_start_weekday", "22,2")
            )
            vt_times = self._parse_tariff_times(
                options.get("tariff_vt_start_weekday", "6")
            )

        current_hour = target_datetime.hour

        # Najdi poslední platnou změnu tarifu
        last_tariff = "NT"  # Default
        last_hour = -1

        # Zkontroluj změny dnes
        all_changes: List[Tuple[int, str]] = []
        for hour in nt_times:
            all_changes.append((hour, "NT"))
        for hour in vt_times:
            all_changes.append((hour, "VT"))

        all_changes.sort(reverse=True)  # Od největší hodiny

        for hour, tariff in all_changes:
            if hour <= current_hour and hour > last_hour:
                last_tariff = tariff
                last_hour = hour

        # Pokud žádná změna dnes, zkontroluj včerejšek
        if last_hour == -1:
            yesterday = target_datetime.date() - timedelta(days=1)
            is_yesterday_weekend = yesterday.weekday() >= 5

            if is_yesterday_weekend:
                nt_times_yesterday = self._parse_tariff_times(
                    options.get("tariff_nt_start_weekend", "0")
                )
                vt_times_yesterday = self._parse_tariff_times(
                    options.get("tariff_vt_start_weekend", "")
                )
            else:
                nt_times_yesterday = self._parse_tariff_times(
                    options.get("tariff_nt_start_weekday", "22,2")
                )
                vt_times_yesterday = self._parse_tariff_times(
                    options.get("tariff_vt_start_weekday", "6")
                )

            yesterday_changes: List[Tuple[int, str]] = []
            for hour in nt_times_yesterday:
                yesterday_changes.append((hour, "NT"))
            for hour in vt_times_yesterday:
                yesterday_changes.append((hour, "VT"))

            yesterday_changes.sort(reverse=True)

            for hour, tariff in yesterday_changes:
                last_tariff = tariff
                break

        return last_tariff

    def _get_spot_price_value(self, spot_data: Dict[str, Any]) -> Optional[float]:
        """Získat hodnotu podle typu spotového senzoru s finálním přepočtem."""
        if not spot_data:
            return None

        # Kontrola, zda jsou povoleny fixní obchodní ceny
        pricing_model = self._entry.options.get("spot_pricing_model", "percentage")

        if pricing_model == "fixed_prices":
            return self._get_fixed_price_value()
        else:
            return self._get_dynamic_spot_price_value(spot_data)

    def _get_fixed_price_value(self) -> Optional[float]:
        """Získat hodnotu pro fixní obchodní ceny."""
        # PŘIDÁNO: Pro spot_price_hourly_all vrátit aktuální cenu
        if self._sensor_type == "spot_price_hourly_all":
            now = datetime.now()
            return self._calculate_fixed_final_price_for_datetime(now)

        fixed_price_vt = self._entry.options.get("fixed_commercial_price_vt", 4.50)
        fixed_price_nt = self._entry.options.get("fixed_commercial_price_nt", 3.20)
        distribution_fee_vt_kwh = self._entry.options.get(
            "distribution_fee_vt_kwh", 1.35
        )
        distribution_fee_nt_kwh = self._entry.options.get(
            "distribution_fee_nt_kwh", 1.05
        )
        dual_tariff_enabled = self._entry.options.get("dual_tariff_enabled", True)
        vat_rate = self._entry.options.get("vat_rate", 21.0)

        def calculate_fixed_final_price(target_datetime: datetime = None) -> float:
            """Vypočítat finální cenu s fixními obchodními cenami včetně DPH."""
            # Určení tarifu
            if target_datetime:
                current_tariff = self._get_tariff_for_datetime(target_datetime)
            elif dual_tariff_enabled:
                current_tariff = self._calculate_current_tariff()
            else:
                current_tariff = "VT"

            # Výběr obchodní ceny podle tarifu
            commercial_price = (
                fixed_price_vt if current_tariff == "VT" else fixed_price_nt
            )

            # Výběr distribučního poplatku podle tarifu
            distribution_fee = (
                distribution_fee_vt_kwh
                if current_tariff == "VT"
                else distribution_fee_nt_kwh
            )

            # Cena bez DPH
            price_without_vat = commercial_price + distribution_fee

            # Finální cena včetně DPH
            return round(price_without_vat * (1 + vat_rate / 100.0), 2)

        # Implementace pro různé typy senzorů
        if self._sensor_type == "spot_price_current_czk_kwh":
            now = datetime.now()
            return calculate_fixed_final_price(now)

        elif self._sensor_type == "spot_price_current_eur_mwh":
            # Pro EUR/MWh vracíme None pro fixní ceny (není relevantní)
            return None

        elif self._sensor_type == "spot_price_today_avg":
            # Průměr fixních cen podle tarifních pásem dnes
            return self._calculate_fixed_daily_average(datetime.now().date())

        elif self._sensor_type == "spot_price_today_min":
            # Minimum z fixních cen (obvykle NT)
            if dual_tariff_enabled:
                return round(
                    min(
                        fixed_price_vt + distribution_fee_vt_kwh,
                        fixed_price_nt + distribution_fee_nt_kwh,
                    )
                    * (1 + vat_rate / 100.0),
                    2,
                )
            else:
                return round(
                    (fixed_price_vt + distribution_fee_vt_kwh) * (1 + vat_rate / 100.0),
                    2,
                )

        elif self._sensor_type == "spot_price_today_max":
            # Maximum z fixních cen (obvykle VT)
            if dual_tariff_enabled:
                return round(
                    max(
                        fixed_price_vt + distribution_fee_vt_kwh,
                        fixed_price_nt + distribution_fee_nt_kwh,
                    )
                    * (1 + vat_rate / 100.0),
                    2,
                )
            else:
                return round(
                    (fixed_price_vt + distribution_fee_vt_kwh) * (1 + vat_rate / 100.0),
                    2,
                )

        elif self._sensor_type == "spot_price_tomorrow_avg":
            # Průměr fixních cen podle tarifních pásem zítra
            tomorrow = datetime.now().date() + timedelta(days=1)
            return self._calculate_fixed_daily_average(tomorrow)

        elif self._sensor_type == "eur_czk_exchange_rate":
            # Pro fixní ceny vracíme None (není relevantní)
            return None

        return None

    def _calculate_fixed_daily_average(self, target_date: datetime.date) -> float:
        """Vypočítat vážený průměr fixních cen pro daný den podle tarifních pásem."""
        dual_tariff_enabled = self._entry.options.get("dual_tariff_enabled", True)
        vat_rate = self._entry.options.get("vat_rate", 21.0)

        if not dual_tariff_enabled:
            # Jednotarifní sazba - celý den VT
            fixed_price_vt = self._entry.options.get("fixed_commercial_price_vt", 4.50)
            distribution_fee_vt_kwh = self._entry.options.get(
                "distribution_fee_vt_kwh", 1.35
            )
            price_without_vat = fixed_price_vt + distribution_fee_vt_kwh
            return round(price_without_vat * (1 + vat_rate / 100.0), 2)

        # Dvoutarifní sazba - počítáme vážený průměr podle hodin
        fixed_price_vt = self._entry.options.get("fixed_commercial_price_vt", 4.50)
        fixed_price_nt = self._entry.options.get("fixed_commercial_price_nt", 3.20)
        distribution_fee_vt_kwh = self._entry.options.get(
            "distribution_fee_vt_kwh", 1.35
        )
        distribution_fee_nt_kwh = self._entry.options.get(
            "distribution_fee_nt_kwh", 1.05
        )

        total_price = 0.0

        # Projdeme všechny hodiny dne
        for hour in range(24):
            hour_datetime = datetime.combine(target_date, time(hour, 0))
            tariff = self._get_tariff_for_datetime(hour_datetime)

            if tariff == "VT":
                hour_price_without_vat = fixed_price_vt + distribution_fee_vt_kwh
            else:
                hour_price_without_vat = fixed_price_nt + distribution_fee_nt_kwh

            # Přidání DPH
            hour_price_with_vat = hour_price_without_vat * (1 + vat_rate / 100.0)
            total_price += hour_price_with_vat

        return round(total_price / 24.0, 2)

    def _get_dynamic_spot_price_value(
        self, spot_data: Dict[str, Any]
    ) -> Optional[float]:
        """Původní logika pro spotové ceny."""
        # Načíst konfiguraci cenového modelu
        pricing_model = self._entry.options.get("spot_pricing_model", "percentage")
        positive_fee_percent = self._entry.options.get(
            "spot_positive_fee_percent", 15.0
        )
        negative_fee_percent = self._entry.options.get("spot_negative_fee_percent", 9.0)
        fixed_fee_mwh = self._entry.options.get("spot_fixed_fee_mwh", 500.0)

        # OPRAVA: Použít správné názvy polí pro distribuční poplatky
        distribution_fee_vt_kwh = self._entry.options.get(
            "distribution_fee_vt_kwh", 1.35
        )
        distribution_fee_nt_kwh = self._entry.options.get(
            "distribution_fee_nt_kwh", 1.05
        )
        dual_tariff_enabled = self._entry.options.get("dual_tariff_enabled", True)
        vat_rate = self._entry.options.get("vat_rate", 21.0)

        def calculate_final_price(
            spot_price_czk: float, target_datetime: datetime = None
        ) -> float:
            """Vypočítat finální cenu včetně obchodních a distribučních poplatků a DPH."""
            if pricing_model == "percentage":
                if spot_price_czk >= 0:
                    commercial_price = spot_price_czk * (
                        1 + positive_fee_percent / 100.0
                    )
                else:
                    commercial_price = spot_price_czk * (
                        1 - negative_fee_percent / 100.0
                    )
            else:  # fixed
                fixed_fee_kwh = fixed_fee_mwh / 1000.0  # MWh -> kWh
                commercial_price = spot_price_czk + fixed_fee_kwh

            # Pro výpočet použijeme tarif pro konkrétní datum/čas nebo aktuální
            if target_datetime:
                current_tariff = self._get_tariff_for_datetime(target_datetime)
            elif dual_tariff_enabled:
                current_tariff = self._calculate_current_tariff()
            else:
                current_tariff = "VT"

            distribution_fee = (
                distribution_fee_vt_kwh
                if current_tariff == "VT"
                else distribution_fee_nt_kwh
            )

            # Cena bez DPH
            price_without_vat = commercial_price + distribution_fee

            # Finální cena včetně DPH zaokrouhlená na 2 desetinná místa
            return round(price_without_vat * (1 + vat_rate / 100.0), 2)

        # PŘIDÁNO: Pro spot_price_hourly_all vrátit aktuální spotovou cenu s finálním přepočtem
        if self._sensor_type == "spot_price_hourly_all":
            now = datetime.now()
            current_hour_key = f"{now.strftime('%Y-%m-%d')}T{now.hour:02d}:00:00"
            prices_czk = spot_data.get("prices_czk_kwh", {})
            spot_price = prices_czk.get(current_hour_key)
            if spot_price is not None:
                return calculate_final_price(spot_price, now)
            return None

        # OPRAVA: Přizpůsobit klíče podle struktury OTE API dat s finálním přepočtem
        if self._sensor_type == "spot_price_current_czk_kwh":
            now = datetime.now()
            current_hour_key = f"{now.strftime('%Y-%m-%d')}T{now.hour:02d}:00:00"
            prices_czk = spot_data.get("prices_czk_kwh", {})
            spot_price = prices_czk.get(current_hour_key)
            if spot_price is not None:
                return calculate_final_price(spot_price, now)
            return None

        elif self._sensor_type == "spot_price_current_eur_mwh":
            # EUR/MWh ponechat hrubé (referenční ceny) - také zaokrouhlit
            now = datetime.now()
            current_hour_key = f"{now.strftime('%Y-%m-%d')}T{now.hour:02d}:00:00"
            prices_eur = spot_data.get("prices_eur_mwh", {})
            eur_price = prices_eur.get(current_hour_key)
            return round(eur_price, 2) if eur_price is not None else None

        elif self._sensor_type == "spot_price_today_avg":
            # Pro průměry používáme aktuální tarif jako aproximaci
            today_stats = spot_data.get("today_stats", {})
            spot_avg = today_stats.get("avg_czk")
            return calculate_final_price(spot_avg) if spot_avg is not None else None

        elif self._sensor_type == "spot_price_today_min":
            # Pro minimum najdeme nejlevnější hodinu včetně distribuce
            prices_czk = spot_data.get("prices_czk_kwh", {})
            today = datetime.now().date()
            min_final_price = None

            for time_key, spot_price in prices_czk.items():
                try:
                    price_datetime = datetime.fromisoformat(
                        time_key.replace("Z", "+00:00")
                    )
                    if price_datetime.date() == today:
                        final_price = calculate_final_price(spot_price, price_datetime)
                        if min_final_price is None or final_price < min_final_price:
                            min_final_price = final_price
                except (ValueError, AttributeError):
                    continue

            return min_final_price

        elif self._sensor_type == "spot_price_today_max":
            # Pro maximum najdeme nejdražší hodinu včetně distribuce
            prices_czk = spot_data.get("prices_czk_kwh", {})
            today = datetime.now().date()
            max_final_price = None

            for time_key, spot_price in prices_czk.items():
                try:
                    price_datetime = datetime.fromisoformat(
                        time_key.replace("Z", "+00:00")
                    )
                    if price_datetime.date() == today:
                        final_price = calculate_final_price(spot_price, price_datetime)
                        if max_final_price is None or final_price > max_final_price:
                            max_final_price = final_price
                except (ValueError, AttributeError):
                    continue

            return max_final_price

        elif self._sensor_type == "spot_price_tomorrow_avg":
            # Pro zítřejší průměr používáme aproximaci s aktuálním tarifem
            tomorrow_stats = spot_data.get("tomorrow_stats")
            if tomorrow_stats:
                spot_avg = tomorrow_stats.get("avg_czk")
                return calculate_final_price(spot_avg) if spot_avg is not None else None
            return None

        elif self._sensor_type == "eur_czk_exchange_rate":
            exchange_rate = spot_data.get("eur_czk_rate")
            return (
                round(exchange_rate, 4) if exchange_rate is not None else None
            )  # Kurz na 4 desetinná místa

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        attrs = {}

        # Pro tarifní senzor přidat speciální atributy
        if self._sensor_type == "current_tariff":
            current_time = dt_util.now()
            is_weekend = current_time.weekday() >= 5
            dual_tariff_enabled = self._entry.options.get("dual_tariff_enabled", True)

            # Vypočítej další změnu tarifu
            next_tariff, next_change_time = self._get_next_tariff_change(
                current_time, is_weekend
            )

            # Vypočítej intervaly
            intervals = self._calculate_tariff_intervals(current_time)

            attrs.update(
                {
                    "current_tariff": self.native_value,
                    "dual_tariff_enabled": dual_tariff_enabled,
                    "tariff_type": (
                        "Dvoutarifní" if dual_tariff_enabled else "Jednotarifní"
                    ),
                    "next_tariff": next_tariff if dual_tariff_enabled else "VT",
                    "next_change": (
                        next_change_time.strftime("%d.%m %H:%M")
                        if dual_tariff_enabled
                        else "Žádná změna"
                    ),
                    "is_weekend": is_weekend,
                    "nt_intervals": intervals["NT"],
                    "vt_intervals": intervals["VT"],
                    "update_time": current_time.strftime("%d.%m.%Y %H:%M:%S"),
                    "distribution_fee_vt": self._entry.options.get(
                        "distribution_fee_vt_kwh", 1.35
                    ),
                }
            )

            # Přidat NT poplatek pouze pro dvoutarifní sazbu
            if dual_tariff_enabled:
                attrs["distribution_fee_nt"] = self._entry.options.get(
                    "distribution_fee_nt_kwh", 1.05
                )

        if self.coordinator.data and "spot_prices" in self.coordinator.data:
            spot_data = self.coordinator.data["spot_prices"]
            pricing_model = self._entry.options.get("spot_pricing_model", "percentage")

            # OPRAVA: Přidat atributy pro spot_price_hourly_all - pouze finální ceny
            if spot_data and self._sensor_type == "spot_price_hourly_all":
                if pricing_model == "fixed_prices":
                    # Pro fixní ceny vytvoříme simulované hodinové ceny
                    final_prices = {}
                    vat_rate = self._entry.options.get("vat_rate", 21.0)

                    # Vygenerujeme ceny pro dnes a zítra
                    for day_offset in [0, 1]:
                        target_date = datetime.now().date() + timedelta(days=day_offset)
                        for hour in range(24):
                            hour_datetime = datetime.combine(target_date, time(hour, 0))
                            time_key = hour_datetime.strftime("%Y-%m-%dT%H:00:00")
                            tariff = self._get_tariff_for_datetime(hour_datetime)

                            fixed_price_vt = self._entry.options.get(
                                "fixed_commercial_price_vt", 4.50
                            )
                            fixed_price_nt = self._entry.options.get(
                                "fixed_commercial_price_nt", 3.20
                            )
                            distribution_fee_vt_kwh = self._entry.options.get(
                                "distribution_fee_vt_kwh", 1.35
                            )
                            distribution_fee_nt_kwh = self._entry.options.get(
                                "distribution_fee_nt_kwh", 1.05
                            )

                            commercial_price = (
                                fixed_price_vt if tariff == "VT" else fixed_price_nt
                            )
                            distribution_fee = (
                                distribution_fee_vt_kwh
                                if tariff == "VT"
                                else distribution_fee_nt_kwh
                            )

                            price_without_vat = commercial_price + distribution_fee
                            final_price = round(
                                price_without_vat * (1 + vat_rate / 100.0), 2
                            )

                            final_prices[time_key] = {
                                "tariff": tariff,
                                "distribution_fee": round(distribution_fee, 2),
                                "price_without_vat": round(price_without_vat, 2),
                                "vat_rate": vat_rate,
                                "final_price": final_price,
                            }

                    # OPRAVA: Pouze finální ceny v atributech
                    attrs["hourly_final_prices"] = final_prices
                    attrs["hours_count"] = len(final_prices)
                    attrs["date_range"] = {
                        "start": datetime.now().strftime("%Y-%m-%d"),
                        "end": (datetime.now() + timedelta(days=1)).strftime(
                            "%Y-%m-%d"
                        ),
                    }
                else:
                    # Původní logika pro spotové ceny
                    raw_prices = spot_data.get("prices_czk_kwh", {})
                    final_prices = {}
                    vat_rate = self._entry.options.get("vat_rate", 21.0)

                    for time_key, spot_price in raw_prices.items():
                        try:
                            price_datetime = datetime.fromisoformat(
                                time_key.replace("Z", "+00:00")
                            )
                            tariff = self._get_tariff_for_datetime(price_datetime)

                            # Výpočet finální ceny
                            pricing_model = self._entry.options.get(
                                "spot_pricing_model", "percentage"
                            )
                            positive_fee_percent = self._entry.options.get(
                                "spot_positive_fee_percent", 15.0
                            )
                            negative_fee_percent = self._entry.options.get(
                                "spot_negative_fee_percent", 9.0
                            )
                            fixed_fee_mwh = self._entry.options.get(
                                "spot_fixed_fee_mwh", 500.0
                            )
                            distribution_fee_vt_kwh = self._entry.options.get(
                                "distribution_fee_vt_kwh", 1.35
                            )
                            distribution_fee_nt_kwh = self._entry.options.get(
                                "distribution_fee_nt_kwh", 1.05
                            )

                            if pricing_model == "percentage":
                                if spot_price >= 0:
                                    commercial_price = spot_price * (
                                        1 + positive_fee_percent / 100.0
                                    )
                                else:
                                    commercial_price = spot_price * (
                                        1 - negative_fee_percent / 100.0
                                    )
                            else:  # fixed
                                fixed_fee_kwh = fixed_fee_mwh / 1000.0
                                commercial_price = spot_price + fixed_fee_kwh

                            distribution_fee = (
                                distribution_fee_vt_kwh
                                if tariff == "VT"
                                else distribution_fee_nt_kwh
                            )

                            price_without_vat = commercial_price + distribution_fee
                            final_price = round(
                                price_without_vat * (1 + vat_rate / 100.0), 2
                            )

                            final_prices[time_key] = {
                                "spot_price": round(spot_price, 2),
                                "commercial_price": round(commercial_price, 2),
                                "tariff": tariff,
                                "distribution_fee": round(distribution_fee, 2),
                                "price_without_vat": round(price_without_vat, 2),
                                "vat_rate": vat_rate,
                                "final_price": final_price,
                            }
                        except (ValueError, AttributeError):
                            continue

                    # OPRAVA: Pouze finální ceny v atributech
                    attrs["hourly_final_prices"] = final_prices
                    attrs["hours_count"] = len(final_prices)

                    # OPRAVA: Přidat date_range i pro spotové ceny
                    if final_prices:
                        timestamps = list(final_prices.keys())
                        timestamps.sort()
                        start_date = datetime.fromisoformat(
                            timestamps[0].replace("Z", "+00:00")
                        ).strftime("%Y-%m-%d")
                        end_date = datetime.fromisoformat(
                            timestamps[-1].replace("Z", "+00:00")
                        ).strftime("%Y-%m-%d")
                        attrs["date_range"] = {
                            "start": start_date,
                            "end": end_date,
                        }

                # Přidat informace o použité konfiguraci pro všechny CZK senzory
                if (
                    "czk" in self._sensor_type
                    and self._sensor_type != "eur_czk_exchange_rate"
                ):
                    pricing_model = self._entry.options.get(
                        "spot_pricing_model", "percentage"
                    )
                    dual_tariff_enabled = self._entry.options.get(
                        "dual_tariff_enabled", True
                    )

                    attrs["pricing_type"] = (
                        "Fixní obchodní ceny"
                        if pricing_model == "fixed_prices"
                        else "Spotové ceny"
                    )
                    attrs["pricing_model"] = {
                        "percentage": "Procentní model",
                        "fixed": "Fixní poplatek",
                        "fixed_prices": "Fixní ceny",
                    }.get(pricing_model, "Neznámý")
                    attrs["tariff_type"] = (
                        "Dvoutarifní" if dual_tariff_enabled else "Jednotarifní"
                    )
                    attrs["distribution_fee_vt_kwh"] = self._entry.options.get(
                        "distribution_fee_vt_kwh", 1.35
                    )

                    if dual_tariff_enabled:
                        attrs["distribution_fee_nt_kwh"] = self._entry.options.get(
                            "distribution_fee_nt_kwh", 1.05
                        )

                    if pricing_model == "fixed_prices":
                        attrs["fixed_commercial_price_vt"] = self._entry.options.get(
                            "fixed_commercial_price_vt", 4.50
                        )
                        if dual_tariff_enabled:
                            attrs["fixed_commercial_price_nt"] = (
                                self._entry.options.get(
                                    "fixed_commercial_price_nt", 3.20
                                )
                            )
                    elif pricing_model == "percentage":
                        attrs["positive_fee_percent"] = self._entry.options.get(
                            "spot_positive_fee_percent", 15.0
                        )
                        attrs["negative_fee_percent"] = self._entry.options.get(
                            "spot_negative_fee_percent", 9.0
                        )
                    elif pricing_model == "fixed":
                        attrs["fixed_fee_mwh"] = self._entry.options.get(
                            "spot_fixed_fee_mwh", 500.0
                        )
                        attrs["fixed_fee_kwh"] = (
                            self._entry.options.get("spot_fixed_fee_mwh", 500.0)
                            / 1000.0
                        )

                attrs["vat_rate"] = self._entry.options.get("vat_rate", 21.0)

        return attrs

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # OPRAVA: Kontrola zda jsou spotové ceny povoleny
        spot_prices_enabled = self._entry.options.get("enable_spot_prices", False)

        if not spot_prices_enabled:
            _LOGGER.debug(f"💰 [{self.entity_id}] Unavailable - spot prices disabled")
            return False  # Spotové ceny jsou vypnuté - senzor není dostupný

        is_available = self.coordinator.last_update_success
        _LOGGER.debug(
            f"💰 [{self.entity_id}] Available check: coordinator_success={is_available}, spot_enabled={spot_prices_enabled}"
        )

        return is_available

    @property
    def state(self) -> Optional[Union[str, float]]:
        """Return the state of the sensor."""
        try:
            _LOGGER.debug(
                f"💰 [{self.entity_id}] Getting state for sensor: {self._sensor_type}"
            )

            # OPRAVA: Kontrola dostupnosti na začátku
            if not self.available:
                return None

            # Pro tarifní senzor
            if self._sensor_type == "current_tariff":
                return self._calculate_current_tariff()

            # OPRAVA: Načíst spotové ceny z coordinator.data místo ote_api.spot_data
            if self.coordinator.data and "spot_prices" in self.coordinator.data:
                spot_data = self.coordinator.data["spot_prices"]
                result = self._get_spot_price_value(spot_data)
                _LOGGER.debug(f"💰 [{self.entity_id}] State calculated: {result}")
                return result

        except Exception as e:
            _LOGGER.error(
                f"💰 [{self.entity_id}] Error getting state: {e}", exc_info=True
            )
            return None

        return None

    @property
    def sensor_type(self) -> str:
        """Return sensor type for compatibility."""
        return self._sensor_type

    def _calculate_fixed_final_price_for_datetime(
        self, target_datetime: datetime
    ) -> float:
        """Vypočítat finální cenu s fixními obchodními cenami pro konkrétní datum/čas."""
        fixed_price_vt = self._entry.options.get("fixed_commercial_price_vt", 4.50)
        fixed_price_nt = self._entry.options.get("fixed_commercial_price_nt", 3.20)
        distribution_fee_vt_kwh = self._entry.options.get(
            "distribution_fee_vt_kwh", 1.35
        )
        distribution_fee_nt_kwh = self._entry.options.get(
            "distribution_fee_nt_kwh", 1.05
        )
        dual_tariff_enabled = self._entry.options.get("dual_tariff_enabled", True)
        vat_rate = self._entry.options.get("vat_rate", 21.0)

        # Určení tarifu
        if dual_tariff_enabled:
            current_tariff = self._get_tariff_for_datetime(target_datetime)
        else:
            current_tariff = "VT"

        # Výběr ceny podle tarifu
        commercial_price = fixed_price_vt if current_tariff == "VT" else fixed_price_nt
        distribution_fee = (
            distribution_fee_vt_kwh
            if current_tariff == "VT"
            else distribution_fee_nt_kwh
        )

        # Finální cena
        price_without_vat = commercial_price + distribution_fee
        return round(price_without_vat * (1 + vat_rate / 100.0), 2)
