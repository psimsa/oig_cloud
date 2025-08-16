"""Senzor pro predikci nabití baterie v průběhu dne."""

import logging
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta

from homeassistant.helpers.entity import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .oig_cloud_sensor import OigCloudSensor

_LOGGER = logging.getLogger(__name__)


class OigCloudBatteryForecastSensor(OigCloudSensor):
    """Senzor pro predikci nabití baterie."""

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        config_entry: ConfigEntry,
        device_info: Dict[str, Any],  # PŘIDÁNO: přebíráme device_info jako parametr
    ) -> None:
        super().__init__(coordinator, sensor_type)
        self._config_entry = config_entry
        self._device_info = device_info  # OPRAVA: použijeme předané device_info
        self._hass: Optional[HomeAssistant] = None

        # Získáme inverter_sn ze správného místa
        inverter_sn = "unknown"

        # Zkusíme získat z coordinator.config_entry.data
        if hasattr(coordinator, "config_entry") and coordinator.config_entry.data:
            inverter_sn = coordinator.config_entry.data.get("inverter_sn", "unknown")
            _LOGGER.debug(
                f"Battery forecast: Got inverter_sn from coordinator.config_entry: {inverter_sn}"
            )

        # Pokud stále unknown, zkusíme z coordinator.data
        if inverter_sn == "unknown" and coordinator.data:
            first_device_key = list(coordinator.data.keys())[0]
            inverter_sn = first_device_key
            _LOGGER.debug(
                f"Battery forecast: Got inverter_sn from coordinator.data keys: {inverter_sn}"
            )

        # Pokud stále unknown, něco je špatně - nebudeme vytvářet senzor
        if inverter_sn == "unknown":
            _LOGGER.error(
                "Battery forecast: Cannot determine inverter_sn - skipping sensor creation"
            )
            raise ValueError("Cannot determine inverter_sn for battery forecast sensor")

        _LOGGER.debug(f"Battery forecast: Final inverter_sn: {inverter_sn}")

        # OPRAVA: Nastavit _box_id a entity_id podle vzoru z OigCloudDataSensor
        self._box_id = inverter_sn
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"

        # OPRAVA: Přepsat název podle name_cs logiky - bez replace("_", " ").title()
        from .sensors.SENSOR_TYPES_STATISTICS import SENSOR_TYPES_STATISTICS

        sensor_config = SENSOR_TYPES_STATISTICS.get(sensor_type, {})
        name_cs = sensor_config.get("name_cs")
        name_en = sensor_config.get("name")

        # Preferujeme český název, fallback na anglický, fallback na sensor_type
        self._attr_name = name_cs or name_en or sensor_type

    async def async_added_to_hass(self) -> None:
        """Při přidání do HA."""
        await super().async_added_to_hass()
        self._hass = self.hass

    async def async_will_remove_from_hass(self) -> None:
        """Při odebrání z HA."""
        await super().async_will_remove_from_hass()

    @property
    def device_info(self) -> Optional[Dict[str, Any]]:
        """Return device info - Analytics Module."""
        return self._device_info

    @property
    def state(self) -> Optional[Union[float, str]]:
        """Stav senzoru - aktuální predikovaná kapacita baterie."""
        # OPRAVA: Používat správnou strukturu dat
        forecast_data = getattr(self.coordinator, "battery_forecast_data", None)

        if not forecast_data:
            return None

        # Vzít aktuální kapacitu z výpočtu
        current_kwh = forecast_data.get("current_battery_kwh", 0)
        return round(current_kwh, 2) if current_kwh > 0 else None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Dodatečné atributy s daty forecast."""
        forecast_data = getattr(self.coordinator, "battery_forecast_data", None)

        if not forecast_data:
            return {}

        return {
            # Původní kompatibilní struktura
            "solar_today_predicted": forecast_data.get("solar_today_predicted", {}),
            "solar_tomorrow_predicted": forecast_data.get(
                "solar_tomorrow_predicted", {}
            ),
            "battery_today_predicted": forecast_data.get("battery_today_predicted", {}),
            "battery_tomorrow_predicted": forecast_data.get(
                "battery_tomorrow_predicted", {}
            ),
            "consumption_prediction": forecast_data.get("consumption_prediction", {}),
            # NOVÉ: Timeline data pro dashboard
            "timeline_data": forecast_data.get("timeline_data", []),
            # Metadata
            "current_battery_kwh": forecast_data.get("current_battery_kwh", 0),
            "max_capacity_kwh": forecast_data.get("max_capacity_kwh", 0),
            "calculation_time": forecast_data.get("calculation_time"),
            "data_source": forecast_data.get("data_source", "unknown"),
        }

    async def _calculate_battery_forecast(self) -> Dict[str, Any]:
        """Výpočet predikce nabití baterie pomocí existujících senzorů."""
        _LOGGER.debug("🔋 Starting battery forecast calculation using existing sensors")

        calculation_time = datetime.now()

        # Počkat na klíčové senzory před výpočtem
        critical_sensors = [
            "sensor.hourly_real_fve_total_kwh",
            f"sensor.oig_{self._box_id}_remaining_usable_capacity",
        ]

        for sensor_id in critical_sensors:
            if not await self._wait_for_sensor(sensor_id, timeout=5):
                _LOGGER.warning(
                    f"🔋 Critical sensor {sensor_id} not available, continuing with fallback data"
                )

        # Použijeme data z existujících senzorů (synchronní operace)
        solar_forecast_data = self._get_existing_solar_forecast()
        consumption_stats = self._get_existing_consumption_stats()
        current_battery_data = self._get_current_battery_state()
        spot_prices_data = self._get_existing_spot_prices()

        # Jednoduchý forecast výpočet
        battery_forecast = self._calculate_simple_battery_forecast(
            solar_forecast_data, consumption_stats, current_battery_data
        )

        # NOVÉ: Vytvoříme spojitou časovou řadu pro všechna data
        timeline_data = self._create_combined_timeline(
            solar_forecast_data, battery_forecast, spot_prices_data
        )

        return {
            # Původní struktura pro kompatibilitu
            "solar_today_predicted": solar_forecast_data.get(
                "today_hourly_total_kw", {}
            ),
            "solar_tomorrow_predicted": solar_forecast_data.get(
                "tomorrow_hourly_total_kw", {}
            ),
            "consumption_prediction": consumption_stats,
            "battery_today_predicted": battery_forecast.get("today", {}),
            "battery_tomorrow_predicted": battery_forecast.get("tomorrow", {}),
            # NOVÉ: Spojitá časová řada pro dashboard
            "timeline_data": timeline_data,
            "calculation_time": calculation_time.isoformat(),
            "data_source": "existing_sensors",
            "current_battery_kwh": current_battery_data.get("current_kwh", 0),
            "max_capacity_kwh": current_battery_data.get("max_kwh", 0),
        }

    def _get_existing_spot_prices(self) -> Dict[str, float]:
        """Získání spotových cen elektřiny."""
        if not self.hass:
            return {}

        spot_prices = {}

        # Zkusit najít spot prices senzor
        spot_sensor_id = f"sensor.oig_{self._box_id}_spot_prices_current"
        spot_sensor = self.hass.states.get(spot_sensor_id)

        if spot_sensor and spot_sensor.attributes:
            prices = spot_sensor.attributes.get("prices_czk_kwh", {})
            spot_prices = prices
            _LOGGER.debug(f"🔋 Loaded {len(prices)} spot prices")
        else:
            _LOGGER.debug("🔋 No spot prices sensor found")

        return spot_prices

    def _create_combined_timeline(
        self,
        solar_data: Dict[str, Any],
        battery_data: Dict[str, Any],
        spot_prices: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """Vytvoří spojitou časovou řadu pro všechna data."""

        timeline = []
        continuous_solar = solar_data.get("combined_timeline", {})
        continuous_battery = battery_data.get("continuous", {})

        # Seřadit timestamp chronologicky
        all_timestamps = sorted(
            set(list(continuous_solar.keys()) + list(continuous_battery.keys()))
        )

        for timestamp_str in all_timestamps:
            timestamp = datetime.fromisoformat(timestamp_str)

            # FVE výroba (převést na W)
            solar_kw = continuous_solar.get(timestamp_str, 0.0)
            solar_w = solar_kw * 1000

            # Kapacita baterie
            battery_kwh = continuous_battery.get(timestamp_str, 0.0)

            # Spotová cena pro tuto hodinu
            hour_key = timestamp.strftime("%Y-%m-%dT%H:00:00")
            spot_price = self._find_closest_spot_price(timestamp, spot_prices)

            # Určit jestli baterie nabíjí nebo vybíjí
            is_charging = self._is_battery_charging(timestamp_str, continuous_battery)

            timeline_point = {
                "timestamp": timestamp_str,
                "hour": timestamp.hour,
                "date": timestamp.date().isoformat(),
                "solar_production_w": round(solar_w, 0),
                "battery_capacity_kwh": round(battery_kwh, 2),
                "spot_price_czk": round(spot_price, 2) if spot_price else None,
                "is_charging": is_charging,
                "is_historical": timestamp < datetime.now(),
            }

            timeline.append(timeline_point)

        _LOGGER.debug(f"🔋 Created combined timeline with {len(timeline)} data points")
        return timeline

    def _find_closest_spot_price(
        self, target_time: datetime, spot_prices: Dict[str, float]
    ) -> Optional[float]:
        """Najde nejbližší spotovou cenu pro daný čas."""
        if not spot_prices:
            return None

        # Hledat přesnou shodu nebo nejbližší čas
        target_hour = target_time.replace(minute=0, second=0, microsecond=0)

        for price_time_str, price in spot_prices.items():
            try:
                price_time = datetime.fromisoformat(
                    price_time_str.replace("Z", "+00:00")
                )
                if price_time.replace(tzinfo=None) == target_hour:
                    return price
            except (ValueError, AttributeError):
                continue

        return None

    def _is_battery_charging(
        self, timestamp_str: str, battery_timeline: Dict[str, float]
    ) -> bool:
        """Určí jestli baterie v daném čase nabíjí."""
        try:
            current_capacity = battery_timeline.get(timestamp_str, 0)

            # Najít předchozí záznam pro porovnání
            timestamps = sorted(battery_timeline.keys())
            current_index = timestamps.index(timestamp_str)

            if current_index > 0:
                previous_capacity = battery_timeline[timestamps[current_index - 1]]
                return current_capacity > previous_capacity

        except (ValueError, IndexError):
            pass

        return False

    def _get_existing_consumption_stats(self) -> Dict[str, Any]:
        """Získání dat ze statistických senzorů spotřeby pro průměrný odběr po intervalech."""
        if not self.hass:
            _LOGGER.warning(
                "🔋 No Home Assistant instance available for consumption stats"
            )
            return {}

        consumption_by_hour: Dict[str, float] = {}
        found_sensors = 0

        # Načíst všechny definované intervalové senzory ze SENSOR_TYPES_STATISTICS
        from .sensors.SENSOR_TYPES_STATISTICS import SENSOR_TYPES_STATISTICS

        # Najít všechny load_avg senzory (skutečné spotřební senzory)
        load_sensors = {}
        for sensor_key, sensor_config in SENSOR_TYPES_STATISTICS.items():
            if sensor_key.startswith("load_avg_"):
                load_sensors[sensor_key] = sensor_config

        _LOGGER.debug(
            f"🔋 Found {len(load_sensors)} load_avg sensor definitions: {list(load_sensors.keys())}"
        )

        # Zkusit také najít senzory přímo v Home Assistant
        all_entities = [
            entity_id
            for entity_id in self.hass.states.entity_ids()
            if entity_id.startswith(f"sensor.oig_{self._box_id}_load_avg_")
        ]
        _LOGGER.debug(f"🔋 Found {len(all_entities)} load_avg entities: {all_entities}")

        # Určit aktuální typ dne
        current_time = datetime.now()
        is_weekend = current_time.weekday() >= 5  # 5=sobota, 6=neděle
        current_day_type = "weekend" if is_weekend else "weekday"

        # Načíst data z jednotlivých senzorů
        for sensor_key, sensor_config in load_sensors.items():
            sensor_id = f"sensor.oig_{self._box_id}_{sensor_key}"

            # Získat parametry ze sensor_config
            time_range = sensor_config.get("time_range")
            day_type = sensor_config.get("day_type")

            if not time_range:
                _LOGGER.debug(f"🔋 No time_range for sensor: {sensor_key}")
                continue

            # Filtrovat podle typu dne
            if day_type and day_type != current_day_type:
                _LOGGER.debug(
                    f"🔋 Skipping {sensor_key} - wrong day_type: {day_type} (current: {current_day_type})"
                )
                continue

            # Převést time_range na seznam hodin
            start_hour, end_hour = time_range
            if end_hour <= start_hour:
                # Přes půlnoc (např. 22-6)
                hours = list(range(start_hour, 24)) + list(range(0, end_hour))
            else:
                # Normální rozsah (např. 6-8)
                hours = list(range(start_hour, end_hour))

            sensor = self.hass.states.get(sensor_id)
            if sensor and sensor.state not in ["unknown", "unavailable"]:
                try:
                    consumption_w = float(sensor.state)
                    consumption_kwh = consumption_w / 1000.0  # W -> kWh

                    # Přiřadit spotřebu všem hodinám v intervalu
                    for hour in hours:
                        hour_key = f"{hour:02d}:00"
                        if hour_key not in consumption_by_hour:
                            consumption_by_hour[hour_key] = consumption_kwh

                    found_sensors += 1
                    _LOGGER.debug(
                        f"🔋 Found load sensor: {sensor_id} = {consumption_w}W ({consumption_kwh:.3f}kWh) "
                        f"for hours {hours} ({day_type})"
                    )

                except (ValueError, TypeError) as e:
                    _LOGGER.debug(f"🔋 Error parsing sensor {sensor_id}: {e}")
                    continue
            else:
                _LOGGER.debug(f"🔋 Load sensor not found or unavailable: {sensor_id}")

        if found_sensors == 0:
            _LOGGER.error(
                f"🔋 No load_avg sensors found for box_id: {self._box_id} and day_type: {current_day_type} - forecast will be inaccurate"
            )
            return {}

        _LOGGER.debug(
            f"🔋 Loaded consumption data from {found_sensors} load_avg sensors, covering {len(consumption_by_hour)} hours for {current_day_type}"
        )
        return consumption_by_hour

    def _get_historical_battery_capacity(self) -> Dict[str, float]:
        """Získání historických kapacit baterie ze senzoru remaining_usable_capacity."""
        if not self.hass:
            return {}

        historical_capacities = {}

        # Načíst aktuální senzor kapacity baterie
        capacity_sensor = self.hass.states.get(
            f"sensor.oig_{self._box_id}_remaining_usable_capacity"
        )

        if capacity_sensor and capacity_sensor.attributes:
            # Pokud má senzor historická data po hodinách
            yesterday_data = capacity_sensor.attributes.get(
                "yesterday_hourly_capacity_kwh", {}
            )
            today_data = capacity_sensor.attributes.get("today_hourly_capacity_kwh", {})

            historical_capacities.update(yesterday_data)
            historical_capacities.update(today_data)

            _LOGGER.debug(
                f"🔋 Loaded {len(historical_capacities)} historical battery capacity points"
            )

        return historical_capacities

    def _calculate_simple_battery_forecast(
        self,
        solar_data: Dict[str, Any],
        consumption_data: Dict[str, Any],
        battery_state: Dict[str, float],
    ) -> Dict[str, Dict[str, float]]:
        """Výpočet predikce baterie: Kapacita += (FVE_výroba - Spotřeba)."""

        current_kwh = battery_state["current_kwh"]
        max_kwh = battery_state["max_kwh"]
        min_kwh = 0.0  # Minimální kapacita

        # Získat spojitou časovou řadu solární výroby
        continuous_solar = solar_data.get("combined_timeline", {})

        # Získat historické kapacity baterie
        historical_capacities = self._get_historical_battery_capacity()

        if not continuous_solar:
            _LOGGER.warning("🔋 No continuous solar timeline available")
            return {"today": {}, "tomorrow": {}, "yesterday": {}, "continuous": {}}

        # Výpočet predikce pro celou časovou řadu
        battery_timeline = {}
        now = datetime.now()

        # Seřadit timestamp pro chronologické zpracování
        sorted_timestamps = sorted(continuous_solar.keys())

        for timestamp_str in sorted_timestamps:
            timestamp = datetime.fromisoformat(timestamp_str)
            solar_kwh = continuous_solar[timestamp_str]  # už je v kWh

            # Spotřeba pro tuto hodinu z průměrných dat
            hour_key = f"{timestamp.hour:02d}:00"
            consumption_kwh = consumption_data.get(hour_key, 0.5)

            if timestamp <= now:
                # HISTORIE: Použít reálné hodnoty ze senzoru
                battery_kwh = historical_capacities.get(timestamp_str)
                if battery_kwh is None:
                    # Pokud nemáme historickou hodnotu, použít poslední známou
                    battery_kwh = current_kwh

            else:
                # PREDIKCE: Počítat energetickou bilanci
                # Najít poslední známou kapacitu
                previous_timestamp = None
                for ts in sorted_timestamps:
                    if datetime.fromisoformat(ts) < timestamp:
                        previous_timestamp = ts
                    else:
                        break

                if previous_timestamp:
                    previous_capacity = battery_timeline.get(
                        previous_timestamp, current_kwh
                    )
                else:
                    previous_capacity = current_kwh

                # Energetická bilance: Kapacita += (Výroba - Spotřeba)
                energy_balance = solar_kwh - consumption_kwh
                battery_kwh = previous_capacity + energy_balance

                # Kontrola limitů
                battery_kwh = max(min_kwh, min(battery_kwh, max_kwh))

                _LOGGER.debug(
                    f"🔋 {timestamp.strftime('%H:%M')}: "
                    f"Solar={solar_kwh:.2f}kWh, "
                    f"Consumption={consumption_kwh:.2f}kWh, "
                    f"Balance={energy_balance:.2f}kWh, "
                    f"Battery={battery_kwh:.2f}kWh"
                )

            battery_timeline[timestamp_str] = round(battery_kwh, 2)

        # Rozdělit zpět podle dnů pro kompatibilitu
        today = now.date()
        yesterday = (now - timedelta(days=1)).date()
        tomorrow = (now + timedelta(days=1)).date()

        result = {
            "yesterday": {},
            "today": {},
            "tomorrow": {},
            "continuous": battery_timeline,  # Celá spojitá řada
        }

        for timestamp_str, capacity in battery_timeline.items():
            timestamp = datetime.fromisoformat(timestamp_str)
            hour_key = f"{timestamp.hour:02d}:00"

            if timestamp.date() == yesterday:
                result["yesterday"][hour_key] = capacity
            elif timestamp.date() == today:
                result["today"][hour_key] = capacity
            elif timestamp.date() == tomorrow:
                result["tomorrow"][hour_key] = capacity

        _LOGGER.debug(
            f"🔋 Battery forecast calculated: "
            f"yesterday={len(result['yesterday'])}, "
            f"today={len(result['today'])}, "
            f"tomorrow={len(result['tomorrow'])} hours"
        )
        return result

    def _get_current_battery_state(self) -> Dict[str, float]:
        """Získání aktuálního stavu baterie z koordinátoru."""
        if not self.coordinator.data:
            return {"current_kwh": 0, "max_kwh": 0}

        device_id = next(iter(self.coordinator.data.keys()))
        device_data = self.coordinator.data.get(device_id, {})

        current_kwh = self._get_state_float(
            f"sensor.oig_{self._box_id}_remaining_usable_capacity", 0
        )
        max_kwh = self._get_state_float(
            f"sensor.oig_{self._box_id}_usable_battery_capacity", 0
        )

        return {
            "current_kwh": current_kwh,
            "max_kwh": max_kwh,
            "current_percent": (current_kwh / max_kwh * 100) if max_kwh > 0 else 0,
        }

    async def _wait_for_sensor(self, entity_id: str, timeout: int = 30) -> bool:
        """Počká na dostupnost senzoru s timeoutem."""
        # Místo čekání jen zkontrolujeme dostupnost okamžitě
        if self.hass and self.hass.states.get(entity_id):
            _LOGGER.debug(f"🔋 Sensor {entity_id} is available")
            return True
        else:
            _LOGGER.warning(f"🔋 Sensor {entity_id} not available")
            return False

    async def _get_existing_solar_forecast_async(self) -> Dict[str, Any]:
        """Asynchronní verze získání solárních dat."""
        # Počkat na klíčový senzor
        historical_sensor_id = "sensor.hourly_real_fve_total_kwh"
        await self._wait_for_sensor(historical_sensor_id, timeout=5)

        # Použít synchronní verzi pro skutečné načtení dat
        return self._get_existing_solar_forecast()

    def _get_existing_solar_forecast(self) -> Dict[str, Any]:
        """Získání kombinovaných solárních dat - historie + předpověď."""
        # OPRAVA: Použít self.hass místo self._hass
        if not self.hass:
            _LOGGER.warning("🔋 No Home Assistant instance available")
            return self._create_fallback_solar_data()

        combined_data = {
            "yesterday_actual": {},
            "today_actual": {},
            "today_predicted": {},
            "tomorrow_predicted": {},
            "combined_timeline": {},
        }

        # 1. OPRAVA: Zkusit načíst historická data ze senzoru hourly_real_fve_total_kwh
        historical_sensor_id = "sensor.hourly_real_fve_total_kwh"
        historical_sensor = self.hass.states.get(historical_sensor_id)

        if not historical_sensor:
            _LOGGER.debug(
                f"🔋 Sensor {historical_sensor_id} not immediately available, checking if it exists in registry..."
            )
            # Zkontrolovat jestli senzor existuje v entity registry
            if hasattr(self.hass, "data") and "entity_registry" in self.hass.data:
                entity_registry = self.hass.data["entity_registry"]
                if entity_registry.async_get(historical_sensor_id):
                    _LOGGER.info(
                        f"🔋 Sensor {historical_sensor_id} exists in registry but state not yet available"
                    )
                else:
                    _LOGGER.warning(
                        f"🔋 Sensor {historical_sensor_id} not found in entity registry"
                    )
            else:
                _LOGGER.debug("🔋 Entity registry not available")

        if historical_sensor:
            _LOGGER.debug(
                f"🔋 Found historical sensor: {historical_sensor.entity_id}, state: {historical_sensor.state}"
            )
            if historical_sensor.attributes:
                historical_attrs = historical_sensor.attributes
                yesterday_data = historical_attrs.get("yesterday_hourly_total_kwh", {})
                today_historical = historical_attrs.get("today_hourly_total_kwh", {})

                combined_data["yesterday_actual"] = yesterday_data
                combined_data["today_actual"] = today_historical

                _LOGGER.debug(
                    f"🔋 Historical data loaded: yesterday={len(yesterday_data)}, today={len(today_historical)}"
                )
            else:
                _LOGGER.warning("🔋 Historical sensor has no attributes")
        else:
            _LOGGER.warning(f"🔋 Historical sensor '{historical_sensor_id}' not found")

        # 2. OPRAVA: Zkusit načíst předpověď ze solar forecast senzoru
        solar_forecast_sensor_id = f"sensor.oig_{self._box_id}_solar_forecast"
        solar_forecast_sensor = self.hass.states.get(solar_forecast_sensor_id)

        if solar_forecast_sensor:
            _LOGGER.debug(
                f"🔋 Found solar forecast sensor: {solar_forecast_sensor.entity_id}, state: {solar_forecast_sensor.state}"
            )
            if solar_forecast_sensor.attributes:
                forecast_attrs = solar_forecast_sensor.attributes
                today_forecast = forecast_attrs.get("today_hourly_total_kw", {})
                tomorrow_forecast = forecast_attrs.get("tomorrow_hourly_total_kw", {})

                combined_data["today_predicted"] = today_forecast
                combined_data["tomorrow_predicted"] = tomorrow_forecast

                _LOGGER.debug(
                    f"🔋 Forecast data loaded: today={len(today_forecast)}, tomorrow={len(tomorrow_forecast)}"
                )
            else:
                _LOGGER.warning(
                    f"🔋 Solar forecast sensor {solar_forecast_sensor_id} has no attributes"
                )
        else:
            _LOGGER.warning(
                f"🔋 Solar forecast sensor '{solar_forecast_sensor_id}' not found"
            )
            # FALLBACK: Zkusit fallback názvy senzorů
            fallback_sensors = [
                f"sensor.oig_{self._box_id}_solar_forecast",
                "sensor.solar_forecast",
                "sensor.forecast_solar",
            ]
            for fallback_id in fallback_sensors:
                fallback_sensor = self.hass.states.get(fallback_id)
                if fallback_sensor:
                    _LOGGER.info(f"🔋 Found fallback solar sensor: {fallback_id}")
                    if fallback_sensor.attributes:
                        forecast_attrs = fallback_sensor.attributes
                        combined_data["today_predicted"] = forecast_attrs.get(
                            "today_hourly_total_kw", {}
                        )
                        combined_data["tomorrow_predicted"] = forecast_attrs.get(
                            "tomorrow_hourly_total_kw", {}
                        )
                    break

        # 3. OPRAVA: Pokud nemáme žádná data, vytvoříme fallback data
        if not any(
            [
                combined_data["yesterday_actual"],
                combined_data["today_actual"],
                combined_data["today_predicted"],
                combined_data["tomorrow_predicted"],
            ]
        ):
            _LOGGER.warning("🔋 No solar data available, using fallback data")
            return self._create_fallback_solar_data()

        # 4. Vytvořit spojitou časovou řadu
        try:
            combined_data["combined_timeline"] = self._create_continuous_solar_timeline(
                combined_data["yesterday_actual"],
                combined_data["today_actual"],
                combined_data["today_predicted"],
                combined_data["tomorrow_predicted"],
            )
            _LOGGER.debug(
                f"🔋 Combined timeline created with {len(combined_data['combined_timeline'])} points"
            )
        except Exception as e:
            _LOGGER.error(f"🔋 Error creating combined timeline: {e}")
            combined_data["combined_timeline"] = {}

        return combined_data

    def _create_fallback_solar_data(self) -> Dict[str, Any]:
        """Vytvoří fallback solární data pro testování."""
        _LOGGER.info("🔋 Creating fallback solar data")

        combined_data = {
            "yesterday_actual": {},
            "today_actual": {},
            "today_predicted": {},
            "tomorrow_predicted": {},
            "combined_timeline": {},
        }

        # Minimální mock data pro testování
        for hour in range(24):
            hour_key = f"{hour:02d}:00"
            # Simulace solární výroby - špička kolem poledne
            if 6 <= hour <= 18:
                mock_value = max(0, (4 - abs(hour - 12)) / 4 * 3)  # Max 3kW v poledne
            else:
                mock_value = 0

            combined_data["today_predicted"][hour_key] = mock_value
            combined_data["tomorrow_predicted"][hour_key] = mock_value

        # Vytvořit spojitou časovou řadu
        try:
            combined_data["combined_timeline"] = self._create_continuous_solar_timeline(
                combined_data["yesterday_actual"],
                combined_data["today_actual"],
                combined_data["today_predicted"],
                combined_data["tomorrow_predicted"],
            )
        except Exception as e:
            _LOGGER.error(f"🔋 Error creating fallback timeline: {e}")
            combined_data["combined_timeline"] = {}

        return combined_data

    def _get_existing_consumption_stats(self) -> Dict[str, Any]:
        """Získání dat ze statistických senzorů spotřeby pro průměrný odběr po intervalech."""
        if not self.hass:
            _LOGGER.warning(
                "🔋 No Home Assistant instance available for consumption stats"
            )
            return {}

        consumption_by_hour: Dict[str, float] = {}
        found_sensors = 0

        # Načíst všechny definované intervalové senzory ze SENSOR_TYPES_STATISTICS
        from .sensors.SENSOR_TYPES_STATISTICS import SENSOR_TYPES_STATISTICS

        # Najít všechny load_avg senzory (skutečné spotřební senzory)
        load_sensors = {}
        for sensor_key, sensor_config in SENSOR_TYPES_STATISTICS.items():
            if sensor_key.startswith("load_avg_"):
                load_sensors[sensor_key] = sensor_config

        _LOGGER.debug(
            f"🔋 Found {len(load_sensors)} load_avg sensor definitions: {list(load_sensors.keys())}"
        )

        # Zkusit také najít senzory přímo v Home Assistant
        all_entities = [
            entity_id
            for entity_id in self.hass.states.entity_ids()
            if entity_id.startswith(f"sensor.oig_{self._box_id}_load_avg_")
        ]
        _LOGGER.debug(f"🔋 Found {len(all_entities)} load_avg entities: {all_entities}")

        # Určit aktuální typ dne
        current_time = datetime.now()
        is_weekend = current_time.weekday() >= 5  # 5=sobota, 6=neděle
        current_day_type = "weekend" if is_weekend else "weekday"

        # Načíst data z jednotlivých senzorů
        for sensor_key, sensor_config in load_sensors.items():
            sensor_id = f"sensor.oig_{self._box_id}_{sensor_key}"

            # Získat parametry ze sensor_config
            time_range = sensor_config.get("time_range")
            day_type = sensor_config.get("day_type")

            if not time_range:
                _LOGGER.debug(f"🔋 No time_range for sensor: {sensor_key}")
                continue

            # Filtrovat podle typu dne
            if day_type and day_type != current_day_type:
                _LOGGER.debug(
                    f"🔋 Skipping {sensor_key} - wrong day_type: {day_type} (current: {current_day_type})"
                )
                continue

            # Převést time_range na seznam hodin
            start_hour, end_hour = time_range
            if end_hour <= start_hour:
                # Přes půlnoc (např. 22-6)
                hours = list(range(start_hour, 24)) + list(range(0, end_hour))
            else:
                # Normální rozsah (např. 6-8)
                hours = list(range(start_hour, end_hour))

            sensor = self.hass.states.get(sensor_id)
            if sensor and sensor.state not in ["unknown", "unavailable"]:
                try:
                    consumption_w = float(sensor.state)
                    consumption_kwh = consumption_w / 1000.0  # W -> kWh

                    # Přiřadit spotřebu všem hodinám v intervalu
                    for hour in hours:
                        hour_key = f"{hour:02d}:00"
                        if hour_key not in consumption_by_hour:
                            consumption_by_hour[hour_key] = consumption_kwh

                    found_sensors += 1
                    _LOGGER.debug(
                        f"🔋 Found load sensor: {sensor_id} = {consumption_w}W ({consumption_kwh:.3f}kWh) "
                        f"for hours {hours} ({day_type})"
                    )

                except (ValueError, TypeError) as e:
                    _LOGGER.debug(f"🔋 Error parsing sensor {sensor_id}: {e}")
                    continue
            else:
                _LOGGER.debug(f"🔋 Load sensor not found or unavailable: {sensor_id}")

        if found_sensors == 0:
            _LOGGER.error(
                f"🔋 No load_avg sensors found for box_id: {self._box_id} and day_type: {current_day_type} - forecast will be inaccurate"
            )
            return {}

        _LOGGER.debug(
            f"🔋 Loaded consumption data from {found_sensors} load_avg sensors, covering {len(consumption_by_hour)} hours for {current_day_type}"
        )
        return consumption_by_hour

    def _get_state_float(self, entity_id: str, default: float = 0.0) -> float:
        """Získání float hodnoty ze stavu entity."""
        # OPRAVA: Použít self.hass místo self._hass
        if not self.hass:
            return default

        state = self.hass.states.get(entity_id)
        if not state or state.state in ["unknown", "unavailable", None]:
            return default

        try:
            return float(state.state)
        except (ValueError, TypeError):
            return default

    async def async_update(self) -> None:
        """Aktualizace senzoru - spustí výpočet forecast."""
        try:
            _LOGGER.debug("🔋 Starting battery forecast calculation")

            # Počkat na klíčové senzory před výpočetem
            critical_sensors = [
                "sensor.hourly_real_fve_total_kwh",
                f"sensor.oig_{self._box_id}_remaining_usable_capacity",
            ]

            for sensor_id in critical_sensors:
                if not await self._wait_for_sensor(sensor_id, timeout=10):
                    _LOGGER.warning(
                        f"🔋 Critical sensor {sensor_id} not available, continuing with fallback data"
                    )

            # Spustíme výpočet forecast
            forecast_data = await self._calculate_battery_forecast()

            # Uložíme data do koordinátoru
            if hasattr(self.coordinator, "battery_forecast_data"):
                self.coordinator.battery_forecast_data = forecast_data
                _LOGGER.debug("🔋 Battery forecast data saved to coordinator")

        except Exception as e:
            _LOGGER.error(f"🔋 Failed to calculate battery forecast: {e}")

    def _create_continuous_solar_timeline(
        self,
        yesterday_actual: Dict[str, float],
        today_actual: Dict[str, float],
        today_predicted: Dict[str, float],
        tomorrow_predicted: Dict[str, float],
    ) -> Dict[str, float]:
        """Vytvoří spojitou časovou řadu ze solárních dat."""

        timeline: Dict[str, float] = {}
        now = datetime.now()

        # Včerejší den - pouze skutečná data
        yesterday_date = (now - timedelta(days=1)).date()
        for hour_key, value in yesterday_actual.items():
            try:
                hour = int(hour_key.split(":")[0])
                timestamp = datetime.combine(
                    yesterday_date, datetime.min.time().replace(hour=hour)
                )
                timeline[timestamp.isoformat()] = float(value)
            except (ValueError, IndexError):
                continue

        # Dnešní den - kombinace skutečných a předpovídaných dat
        today_date = now.date()
        current_hour = now.hour

        for hour in range(24):
            hour_key = f"{hour:02d}:00"
            timestamp = datetime.combine(
                today_date, datetime.min.time().replace(hour=hour)
            )

            # Pokud je hodina už proběhlá, použít skutečná data, jinak předpověď
            if hour <= current_hour and hour_key in today_actual:
                timeline[timestamp.isoformat()] = float(today_actual[hour_key])
            elif hour_key in today_predicted:
                timeline[timestamp.isoformat()] = float(today_predicted[hour_key])
            else:
                timeline[timestamp.isoformat()] = 0.0

        # Zítřejší den - pouze předpověď
        tomorrow_date = (now + timedelta(days=1)).date()
        for hour_key, value in tomorrow_predicted.items():
            try:
                hour = int(hour_key.split(":")[0])
                timestamp = datetime.combine(
                    tomorrow_date, datetime.min.time().replace(hour=hour)
                )
                timeline[timestamp.isoformat()] = float(value)
            except (ValueError, IndexError):
                continue

        _LOGGER.debug(
            f"🔋 Created continuous solar timeline with {len(timeline)} data points"
        )
        return timeline
