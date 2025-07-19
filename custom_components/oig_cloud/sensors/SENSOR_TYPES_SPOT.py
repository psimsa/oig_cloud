"""Definice typů senzorů pro spotové ceny elektřiny z OTE a ČNB."""

from typing import Dict, Any
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

# Typy senzorů pro spotové ceny elektřiny
SENSOR_TYPES_SPOT: Dict[str, Dict[str, Any]] = {
    "spot_price_current_czk_kwh": {
        "name": "Current Spot Price",
        "name_cs": "Aktuální spotová cena",
        "icon": "mdi:flash",
        "unit_of_measurement": "CZK/kWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": None,  # OPRAVA: Monetary sensors nesmí mít measurement state_class
        "category": "spot_price",
        "pricing_type": "spot_price",
        "sensor_type_category": "pricing",
        "description": "Aktuální spotová cena elektřiny v CZK/kWh",
    },
    "spot_price_current_eur_mwh": {
        "name": "Current Spot Price EUR",
        "name_cs": "Aktuální spotová cena EUR/MWh",
        "icon": "mdi:flash",
        "unit_of_measurement": "EUR/MWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": None,  # OPRAVA: Monetary sensors nesmí mít measurement state_class
        "category": "spot_price",
        "pricing_type": "spot_price",
        "sensor_type_category": "pricing",
        "description": "Aktuální spotová cena elektřiny v EUR/MWh",
    },
    "spot_price_today_avg": {
        "name": "Today Average Price",
        "name_cs": "Průměrná cena dnes",
        "icon": "mdi:chart-line",
        "unit_of_measurement": "CZK/kWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": None,  # OPRAVA: Monetary sensors nesmí mít measurement state_class
        "category": "spot_price",
        "pricing_type": "spot_price",
        "sensor_type_category": "pricing",
        "description": "Průměrná spotová cena elektřiny pro dnešní den",
    },
    "spot_price_today_min": {
        "name": "Today Minimum Price",
        "name_cs": "Minimální cena dnes",
        "icon": "mdi:arrow-down",
        "unit_of_measurement": "CZK/kWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": None,  # OPRAVA: Monetary sensors nesmí mít measurement state_class
        "category": "spot_price",
        "pricing_type": "spot_price",
        "sensor_type_category": "pricing",
        "description": "Minimální spotová cena elektřiny pro dnešní den",
    },
    "spot_price_today_max": {
        "name": "Today Maximum Price",
        "name_cs": "Maximální cena dnes",
        "icon": "mdi:arrow-up",
        "unit_of_measurement": "CZK/kWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": None,  # OPRAVA: Monetary sensors nesmí mít measurement state_class
        "category": "spot_price",
        "pricing_type": "spot_price",
        "sensor_type_category": "pricing",
        "description": "Maximální spotová cena elektřiny pro dnešní den",
    },
    "spot_price_tomorrow_avg": {
        "name": "Tomorrow Average Price",
        "name_cs": "Průměrná cena zítřek",
        "icon": "mdi:chart-bar",
        "unit_of_measurement": "CZK/kWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": None,  # OPRAVA: Monetary sensors nesmí mít measurement state_class
        "category": "spot_price",
        "pricing_type": "spot_price",
        "sensor_type_category": "pricing",
        "description": "Průměrná spotová cena elektřiny pro zítřejší den",
    },
    "spot_price_hourly_all": {
        "name": "Hourly Prices All",
        "name_cs": "Všechny hodinové ceny",
        "icon": "mdi:clock-time-eight-outline",
        "unit_of_measurement": "CZK/kWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": None,  # OPRAVA: Monetary sensors nesmí mít measurement state_class
        "category": "spot_price",
        "pricing_type": "spot_price",
        "sensor_type_category": "pricing",
        "description": "Všechny dostupné hodinové spotové ceny",
    },
    "eur_czk_exchange_rate": {
        "name": "EUR CZK Exchange Rate",
        "name_cs": "Kurz EUR/CZK",
        "icon": "mdi:currency-eur",
        "unit_of_measurement": "CZK/EUR",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": None,
        "category": "spot_price",
        "pricing_type": "exchange_rate",
        "sensor_type_category": "pricing",
        "description": "Aktuální kurz EUR/CZK z ČNB pro přepočet spotových cen",
    },
    "current_tariff": {
        "name": "Current Tariff",
        "name_cs": "Aktuální tarif",
        "icon": "mdi:clock-time-four-outline",
        "unit_of_measurement": None,
        "device_class": None,
        "state_class": None,
        "category": "tariff",
        "pricing_type": "tariff",
        "sensor_type_category": "pricing",
        "description": "Aktuální tarifní pásmo NT/VT podle času a dne v týdnu",
    },
}
