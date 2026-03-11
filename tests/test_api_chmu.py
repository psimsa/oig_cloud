from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.oig_cloud.api.api_chmu import ChmuApi


def test_cache_validation_and_invalidate():
    api = ChmuApi()
    assert api._is_cache_valid() is False

    api._last_data = {"x": 1}
    api._cache_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    assert api._is_cache_valid() is True

    api._cache_time = datetime.now(timezone.utc) - timedelta(hours=2)
    assert api._is_cache_valid() is False

    api._invalidate_cache()
    assert api._cache_time is None
    assert api._last_data == {}


def test_parse_polygon_and_circle():
    api = ChmuApi()
    polygon = api._parse_polygon("50.0,14.0 50.0,14.1 50.1,14.1 50.1,14.0")
    assert polygon == [
        (50.0, 14.0),
        (50.0, 14.1),
        (50.1, 14.1),
        (50.1, 14.0),
    ]

    assert api._parse_polygon("50.0,14.0 50.0") is None
    assert api._parse_polygon("bad") is None

    circle = api._parse_circle("50.0,14.0 10")
    assert circle == {"center_lat": 50.0, "center_lon": 14.0, "radius_km": 10.0}
    assert api._parse_circle("50.0,14.0") is None
    assert api._parse_circle("invalid") is None


def test_geometry_helpers():
    api = ChmuApi()
    square = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
    assert api._point_in_polygon((0.5, 0.5), square) is True
    assert api._point_in_polygon((2.0, 2.0), square) is False

    assert api._point_in_circle((0.0, 0.0), (0.0, 0.0), 1.0) is True
    assert api._point_in_circle((2.0, 0.0), (0.0, 0.0), 1.0) is False

    assert api._haversine_distance((0.0, 0.0), (0.0, 0.0)) == 0.0


def test_parse_cap_xml_minimal():
    api = ChmuApi()
    xml_text = """
    <alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
      <sent>2000-01-01T00:00:00+00:00</sent>
      <info>
        <language>cs</language>
        <event>Test warning</event>
        <severity>Moderate</severity>
        <urgency>Immediate</urgency>
        <certainty>Observed</certainty>
        <effective>2000-01-01T00:00:00+00:00</effective>
        <onset>2000-01-01T00:00:00+00:00</onset>
        <expires>2100-01-01T00:00:00+00:00</expires>
        <description>Desc</description>
        <instruction>Instr</instruction>
        <area>
          <areaDesc>Area 1</areaDesc>
          <polygon>50.0,14.0 50.0,14.1 50.1,14.1 50.1,14.0</polygon>
          <geocode>
            <valueName>ORP</valueName>
            <value>123</value>
          </geocode>
        </area>
      </info>
    </alert>
    """

    alerts = api._parse_cap_xml(xml_text)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["event"] == "Test warning"
    assert alert["severity_level"] == 2
    assert alert["status"] == "active"
    assert alert["eta_hours"] == 0.0
    assert alert["areas"][0]["polygon"]


def test_filter_select_and_prefer_language():
    api = ChmuApi()
    alert_cs = {
        "language": "cs",
        "event": "Test",
        "onset": "2025-01-01T00:00:00+00:00",
        "status": "active",
        "severity_level": 2,
        "eta_hours": 3.0,
        "areas": [
            {
                "polygon": [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)],
                "circle": None,
                "geocodes": [],
            }
        ],
    }
    alert_en = {
        "language": "en",
        "event": "Test",
        "onset": "2025-01-01T00:00:00+00:00",
        "status": "active",
        "severity_level": 3,
        "eta_hours": 2.0,
        "areas": [],
    }
    alert_other = {
        "language": "cs",
        "event": "Other",
        "onset": "2025-01-02T00:00:00+00:00",
        "status": "upcoming",
        "severity_level": 1,
        "eta_hours": 1.0,
        "areas": [
            {
                "polygon": None,
                "circle": {"center_lat": 0.0, "center_lon": 0.0, "radius_km": 10.0},
                "geocodes": [],
            }
        ],
    }

    preferred = api._prefer_czech_language([alert_en, alert_cs, alert_other])
    assert alert_en not in preferred
    assert alert_cs in preferred

    local_alerts, method = api._filter_by_location([alert_cs], 0.5, 0.5)
    assert method == "polygon_match"
    assert local_alerts == [alert_cs]

    local_alerts, method = api._filter_by_location([alert_other], 0.0, 0.0)
    assert method == "circle_match"
    assert local_alerts == [alert_other]

    top = api._select_top_alert([alert_cs, alert_other])
    assert top == alert_cs
