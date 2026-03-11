# OIG Cloud Sensors - Dokumentace

## Přehled

Senzory jsou rozděleny do 17 SENSOR_TYPES souborů podle funkční oblasti.

## Device Mapping

Každý senzor má field `device_mapping`, který určuje, ke kterému zařízení bude přiřazen v Home Assistantu.

### Dostupné zařízení

1. **`"main"`** - Hlavní OIG zařízení
   - Identifier: `("oig_cloud", box_id)`
   - Název: `OIG Cloud {box_id}`
   - Pro základní data a computed senzory

2. **`"analytics"`** - Analytics & Predictions
   - Identifier: `("oig_cloud_analytics", box_id)`
   - Název: `Analytics & Predictions {box_id}`
   - Pro statistics, forecasts, predictions, pricing

3. **`"shield"`** - ServiceShield
   - Identifier: `("oig_cloud_shield", box_id)`
   - Název: `ServiceShield {box_id}`
   - Pro shield monitoring senzory

### Mapování kategorií

| Kategorie | Device Mapping | Popis |
|-----------|---------------|-------|
| `data` | `main` | Základní data z API |
| `computed` | `main` | Vypočítané hodnoty |
| `extended` | `main` | Rozšířené metriky |
| `notification` | `main` | Systémové notifikace |
| `statistics` | `analytics` | Historická statistika |
| `solar_forecast` | `analytics` | Solární předpovědi |
| `battery_prediction` | `analytics` | Predikce baterie |
| `grid_charging_plan` | `analytics` | Plán nabíjení ze sítě |
| `pricing` | `analytics` | Spotové ceny |
| `shield` | `shield` | ServiceShield monitoring |

## Struktura SENSOR_TYPES souboru

```python
SENSOR_TYPES_EXAMPLE: Dict[str, Dict[str, Any]] = {
    "sensor_name": {
        "name": "Sensor Name (EN)",
        "name_cs": "Název senzoru (CZ)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": UnitOfPower.WATT,
        "node_id": "actual",  # nebo None pro computed
        "node_key": "value_key",  # nebo None pro computed
        "state_class": SensorStateClass.MEASUREMENT,
        "sensor_type_category": "data",  # kategorie senzoru
        "device_mapping": "main",  # NOVÉ: určuje device přiřazení
    },
}
```

### Povinná pole

- `name`: Anglický název senzoru
- `name_cs`: Český název senzoru
- `sensor_type_category`: Kategorie senzoru (data, computed, extended, atd.)
- **`device_mapping`**: Mapování na zařízení (`"main"`, `"analytics"`, nebo `"shield"`)

### Volitelná pole

- `device_class`: Home Assistant device class (POWER, ENERGY, atd.)
- `unit_of_measurement`: Jednotka měření
- `node_id`: ID uzlu v API datech (None pro computed)
- `node_key`: Klíč hodnoty v uzlu (None pro computed)
- `state_class`: State class (MEASUREMENT, TOTAL, atd.)
- `entity_category`: Entity kategorie (CONFIG, DIAGNOSTIC, None)
- `icon`: Custom ikona (pokud není device_class)

## Helper funkce

### `get_device_info_for_sensor()`

```python
def get_device_info_for_sensor(
    sensor_config: Dict[str, Any],
    box_id: str,
    main_device_info: Dict[str, Any],
    analytics_device_info: Dict[str, Any],
    shield_device_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Vrací správný device_info pro senzor podle device_mapping."""
```

**Použití:**

```python
device_info = get_device_info_for_sensor(
    sensor_config=config,
    box_id="2206237016",
    main_device_info=main_device_info,
    analytics_device_info=analytics_device_info,
    shield_device_info=shield_device_info,
)
```

## Příklady

### Data senzor (main device)

```python
"actual_aci_wr": {
    "name": "Grid Load Line 1 (live)",
    "name_cs": "Síť - zátěž fáze 1 (live)",
    "device_class": SensorDeviceClass.POWER,
    "unit_of_measurement": UnitOfPower.WATT,
    "node_id": "actual",
    "node_key": "aci_wr",
    "state_class": SensorStateClass.MEASUREMENT,
    "sensor_type_category": "data",
    "device_mapping": "main",  # ← na hlavní zařízení
},
```

### Statistics senzor (analytics device)

```python
"daily_fve_production": {
    "name": "Daily FVE Production",
    "name_cs": "Denní výroba FVE",
    "device_class": SensorDeviceClass.ENERGY,
    "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    "node_id": None,
    "node_key": None,
    "state_class": SensorStateClass.TOTAL,
    "sensor_type_category": "statistics",
    "device_mapping": "analytics",  # ← na analytics zařízení
},
```

### Shield senzor (shield device)

```python
"shield_last_communication": {
    "name": "Last Communication",
    "name_cs": "Poslední komunikace",
    "device_class": SensorDeviceClass.TIMESTAMP,
    "node_id": None,
    "node_key": None,
    "sensor_type_category": "shield",
    "device_mapping": "shield",  # ← na shield zařízení
},
```

## Pravidla

1. **Každý senzor MUSÍ mít `device_mapping`** - bez tohoto pole nebude senzor správně přiřazen
2. **Device mapping MUSÍ odpovídat kategorii** - viz tabulka mapování výše
3. **Entity ID se NIKDY NEMĚNÍ** - formát `sensor.oig_{box_id}_{sensor_type}` je IMMUTABLE
4. **Fallback na "main"** - pokud device_mapping chybí, použije se "main"

## Změny v refaktoru (Fáze 2)

### Co bylo přidáno:
- ✅ Field `device_mapping` do všech 17 SENSOR_TYPES souborů
- ✅ Helper funkce `get_device_info_for_sensor()` v sensor.py
- ✅ Automatické mapování podle kategorie
- ✅ Dokumentace v tomto README.md

### Co se NEZMĚNILO:
- ✅ Entity ID formát - pořád `sensor.oig_{box_id}_{sensor_type}`
- ✅ Device identifiers - pořád stejné
- ✅ Sensor konfigurace - pouze přidáno 1 nové pole
- ✅ API compatibility - 100% zachováno

## Testing

### Validace device_mapping

```python
# V pytest testu
def test_all_sensors_have_device_mapping():
    """Všechny senzory musí mít device_mapping."""
    from custom_components.oig_cloud.sensors.sensor_types import SENSOR_TYPES

    for sensor_type, config in SENSOR_TYPES.items():
        assert "device_mapping" in config, f"{sensor_type} nemá device_mapping"
        assert config["device_mapping"] in ["main", "analytics", "shield"]
```

### Validace mapování podle kategorie

```python
CATEGORY_TO_DEVICE = {
    "data": "main",
    "computed": "main",
    "extended": "main",
    "notification": "main",
    "statistics": "analytics",
    "solar_forecast": "analytics",
    "battery_prediction": "analytics",
    "grid_charging_plan": "analytics",
    "pricing": "analytics",
    "shield": "shield",
}

def test_device_mapping_matches_category():
    """Device mapping musí odpovídat kategorii."""
    from custom_components.oig_cloud.sensors.sensor_types import SENSOR_TYPES

    for sensor_type, config in SENSOR_TYPES.items():
        category = config.get("sensor_type_category")
        expected = CATEGORY_TO_DEVICE[category]
        actual = config.get("device_mapping")

        assert actual == expected, (
            f"{sensor_type}: expected device_mapping='{expected}' "
            f"for category='{category}', got '{actual}'"
        )
```

## FAQ

### Proč device_mapping?

Před refaktorem bylo device přiřazení rozházené v sensor.py. Nyní je explicitně v konfiguraci senzoru, což je přehlednější a testovatelné.

### Co když přidám nový senzor?

Přidej `device_mapping` podle kategorie:
- Basic data → `"main"`
- Analytics/stats → `"analytics"`
- Shield monitoring → `"shield"`

### Můžu změnit device_mapping existujícího senzoru?

**NE!** To by změnilo entity_id a uživatelé by přišli o historická data. Device mapping je IMMUTABLE po prvním nasazení.

### Co když zapomenu device_mapping?

Helper funkce použije fallback na `"main"`. Ale doporuč ujeme vždy explicitně zadat.

---

**Verze:** Fáze 2 Device Mapping Refactor
**Datum:** 23. října 2025
**Autor:** OIG Cloud Integration Team
