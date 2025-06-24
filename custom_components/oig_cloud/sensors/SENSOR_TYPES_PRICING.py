"""Definice typů senzorů pro cenové kalkulace."""

from typing import Dict, Any

# Typy senzorů pro cenové kalkulace
SENSOR_TYPES_PRICING: Dict[str, Dict[str, Any]] = {
    "electricity_buy_price_current": {
        "name": "Aktuální nákupní cena elektřiny",
        "icon": "mdi:currency-eur",
        "unit_of_measurement": "CZK/kWh",
        "device_class": "monetary",
        "state_class": "measurement",
        "category": "pricing",
        "sensor_type_category": "pricing",
        "description": "Aktuální cena za nákup elektřiny včetně všech poplatků",
    },
    "electricity_sell_price_current": {
        "name": "Aktuální prodejní cena elektřiny",
        "icon": "mdi:currency-eur",
        "unit_of_measurement": "CZK/kWh",
        "device_class": "monetary",
        "state_class": "measurement",
        "category": "pricing",
        "sensor_type_category": "pricing",
        "description": "Aktuální cena za prodej elektřiny po odečtení poplatků",
    },
    "electricity_monthly_fixed_costs": {
        "name": "Měsíční fixní náklady",
        "icon": "mdi:calendar-month",
        "unit_of_measurement": "CZK/měsíc",
        "device_class": "monetary",
        "state_class": "total",
        "category": "pricing",
        "sensor_type_category": "pricing",
        "description": "Měsíční fixní poplatky za distribuci a jistič",
    },
    "electricity_tariff_type": {
        "name": "Typ tarifu",
        "icon": "mdi:clock-time-four-outline",
        "category": "pricing",
        "sensor_type_category": "pricing",
        "description": "Aktuální typ tarifu (VT/NT/jednotný)",
    },
}
