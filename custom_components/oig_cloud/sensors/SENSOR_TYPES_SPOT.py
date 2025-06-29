"""Definice typů senzorů pro spotové ceny elektřiny z OTE a ČNB."""

from typing import Dict, Any
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

# Typy senzorů pro spotové ceny elektřiny
SENSOR_TYPES_SPOT: Dict[str, Dict[str, Any]] = {
    "spot_price_current_czk_kwh": {
        "name": "Aktuální spotová cena",
        "icon": "mdi:flash",
        "unit_of_measurement": "CZK/kWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": SensorStateClass.MEASUREMENT,
        "category": "spot_price",
        "pricing_type": "spot_price",  # Speciální atribut pro rozpoznání
        "sensor_type_category": "pricing",  # Nový atribut pro kategorizaci
        "description": "Aktuální spotová cena elektřiny v CZK/kWh",
    },
    "spot_price_current_eur_mwh": {
        "name": "Aktuální spotová cena EUR/MWh",
        "icon": "mdi:flash",
        "unit_of_measurement": "EUR/MWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": SensorStateClass.MEASUREMENT,
        "category": "spot_price",
        "pricing_type": "spot_price",  # Speciální atribut pro rozpoznání
        "sensor_type_category": "pricing",  # Nový atribut pro kategorizaci
        "description": "Aktuální spotová cena elektřiny v EUR/MWh",
    },
    "spot_price_today_avg": {
        "name": "Průměrná cena dnes",
        "icon": "mdi:chart-line",
        "unit_of_measurement": "CZK/kWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": SensorStateClass.MEASUREMENT,
        "category": "spot_price",
        "pricing_type": "spot_price",  # Speciální atribut pro rozpoznání
        "sensor_type_category": "pricing",  # Nový atribut pro kategorizaci
        "description": "Průměrná spotová cena elektřiny pro dnešní den",
    },
    "spot_price_today_min": {
        "name": "Minimální cena dnes",
        "icon": "mdi:arrow-down",
        "unit_of_measurement": "CZK/kWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": SensorStateClass.MEASUREMENT,
        "category": "spot_price",
        "pricing_type": "spot_price",  # Speciální atribut pro rozpoznání
        "sensor_type_category": "pricing",  # Nový atribut pro kategorizaci
        "description": "Minimální spotová cena elektřiny pro dnešní den",
    },
    "spot_price_today_max": {
        "name": "Maximální cena dnes",
        "icon": "mdi:arrow-up",
        "unit_of_measurement": "CZK/kWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": SensorStateClass.MEASUREMENT,
        "category": "spot_price",
        "pricing_type": "spot_price",  # Speciální atribut pro rozpoznání
        "sensor_type_category": "pricing",  # Nový atribut pro kategorizaci
        "description": "Maximální spotová cena elektřiny pro dnešní den",
    },
    "spot_price_tomorrow_avg": {
        "name": "Průměrná cena zítřek",
        "icon": "mdi:chart-bar",
        "unit_of_measurement": "CZK/kWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": SensorStateClass.MEASUREMENT,
        "category": "spot_price",
        "pricing_type": "spot_price",  # Speciální atribut pro rozpoznání
        "sensor_type_category": "pricing",  # Nový atribut pro kategorizaci
        "description": "Průměrná spotová cena elektřiny pro zítřejší den",
    },
    "spot_price_hourly_all": {
        "name": "Všechny hodinové ceny",
        "icon": "mdi:clock-time-eight-outline",
        "unit_of_measurement": "CZK/kWh",
        "device_class": SensorDeviceClass.MONETARY,
        "state_class": SensorStateClass.MEASUREMENT,
        "category": "spot_price",
        "pricing_type": "spot_price",  # Speciální atribut pro rozpoznání
        "sensor_type_category": "pricing",  # Nový atribut pro kategorizaci
        "description": "Všechny dostupné hodinové spotové ceny",
    },
}
