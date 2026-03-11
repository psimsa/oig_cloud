from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import aiohttp
import pytest

from custom_components.oig_cloud.api import api_chmu as module


class DummyResponse:
    def __init__(self, status: int, text: str):
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _tb):
        return None


class DummySession:
    def __init__(self, response: DummyResponse):
        self._response = response
        self.closed = False

    def get(self, _url: str):
        return self._response

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_fetch_cap_xml_http_errors(monkeypatch):
    api = module.ChmuApi()

    async def _resolve(_session):
        return "http://example.com/cap.xml"

    monkeypatch.setattr(api, "_resolve_latest_cap_url", _resolve)

    session = DummySession(DummyResponse(500, "x" * 200))
    with pytest.raises(module.ChmuApiError, match="HTTP 500"):
        await api._fetch_cap_xml(session)

    session = DummySession(DummyResponse(200, "short"))
    with pytest.raises(module.ChmuApiError, match="Prázdný nebo neplatný"):
        await api._fetch_cap_xml(session)


@pytest.mark.asyncio
async def test_fetch_cap_xml_success(monkeypatch):
    api = module.ChmuApi()

    async def _resolve(_session):
        return "http://example.com/cap.xml"

    monkeypatch.setattr(api, "_resolve_latest_cap_url", _resolve)
    session = DummySession(DummyResponse(200, "x" * 200))

    text = await api._fetch_cap_xml(session)

    assert len(text) == 200


@pytest.mark.asyncio
async def test_fetch_cap_xml_timeout_and_client_error(monkeypatch):
    api = module.ChmuApi()

    class DummyTimeout:
        def __init__(self, _seconds):
            pass

        async def __aenter__(self):
            raise asyncio.TimeoutError()

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

    monkeypatch.setattr(module.async_timeout, "timeout", DummyTimeout)

    session = DummySession(DummyResponse(200, "x" * 200))
    with pytest.raises(module.ChmuApiError, match="Timeout"):
        await api._fetch_cap_xml(session)

    class DummyOkTimeout:
        def __init__(self, _seconds):
            pass

        async def __aenter__(self):
            return None

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

    monkeypatch.setattr(module.async_timeout, "timeout", DummyOkTimeout)

    class ErrorSession(DummySession):
        def get(self, _url: str):
            raise aiohttp.ClientError("boom")

    async def _resolve(_session):
        return "http://example.com/cap.xml"

    monkeypatch.setattr(api, "_resolve_latest_cap_url", _resolve)

    with pytest.raises(module.ChmuApiError, match="HTTP chyba"):
        await api._fetch_cap_xml(ErrorSession(DummyResponse(200, "x" * 200)))


@pytest.mark.asyncio
async def test_resolve_latest_cap_url_variants(monkeypatch):
    api = module.ChmuApi()

    index_html = """
    <a href="alert_cap_49_123.xml">alert_cap_49_123.xml</a> 01-Jan-2025 10:00 10
    <a href="alert_cap_50_456.xml">alert_cap_50_456.xml</a> 02-Jan-2025 09:00 10
    <a href="alert_cap_50_999.xml">alert_cap_50_999.xml</a> 32-Jan-2025 10:00 10
    """
    session = DummySession(DummyResponse(200, index_html))
    url = await api._resolve_latest_cap_url(session)
    assert url.endswith("alert_cap_50_456.xml")

    bad_index = "<a href=\"alert_cap_50_1.xml\">alert_cap_50_1.xml</a> bad-date 10"
    session = DummySession(DummyResponse(200, bad_index))
    with pytest.raises(module.ChmuApiError, match="neobsahuje žádné"):
        await api._resolve_latest_cap_url(session)

    session = DummySession(DummyResponse(500, "err"))
    with pytest.raises(module.ChmuApiError, match="HTTP 500"):
        await api._resolve_latest_cap_url(session)

    async def _bad_get(_url: str):
        raise RuntimeError("boom")

    class BadRe:
        def finditer(self, _text):
            raise RuntimeError("boom")

    monkeypatch.setattr(api, "_AUTO_INDEX_RE", BadRe())
    with pytest.raises(module.ChmuApiError, match="Chyba při výběru"):
        await api._resolve_latest_cap_url(DummySession(DummyResponse(200, index_html)))


def test_parse_cap_xml_error_and_info_exception(monkeypatch):
    api = module.ChmuApi()
    assert api._parse_cap_xml("not-xml") == []

    xml_text = """
    <alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
      <info><language>cs</language><event>Test</event></info>
    </alert>
    """
    monkeypatch.setattr(api, "_parse_info_block", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert api._parse_cap_xml(xml_text) == []


def test_parse_info_block_language_event_and_awareness():
    api = module.ChmuApi()
    xml_text = """
    <alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
      <info><language>de</language><event>Test</event></info>
      <info><language>cs</language></info>
      <info>
        <language>cs</language>
        <event>Event</event>
        <severity>Unknown</severity>
        <parameter>
          <valueName>awareness_level</valueName>
          <value>3; orange</value>
        </parameter>
      </info>
    </alert>
    """
    alerts = api._parse_cap_xml(xml_text)
    assert len(alerts) == 1
    assert alerts[0]["severity_level"] == 0


def test_get_text_with_xpath_default():
    api = module.ChmuApi()
    elem = module.ET.fromstring(
        '<info xmlns="urn:oasis:names:tc:emergency:cap:1.2"><event>Event</event></info>'
    )
    assert api._get_text(elem, "parameter[valueName='awareness_level']/value", "x") == "x"


def test_determine_status_and_eta_and_parse_iso():
    api = module.ChmuApi()
    now = datetime.now(timezone.utc)
    expired = (now - timedelta(hours=1)).isoformat()
    upcoming = (now + timedelta(hours=1)).isoformat()

    assert api._determine_status(None, None, expired) == "expired"
    assert api._determine_status(None, upcoming, None) == "upcoming"
    assert api._determine_status(upcoming, None, None) == "upcoming"

    assert api._calculate_eta(None) == 0.0
    assert api._calculate_eta("bad") == 0.0
    assert api._parse_iso_datetime("bad") is None


def test_filter_by_location_geocode_fallback():
    api = module.ChmuApi()
    alert = {
        "areas": [{"polygon": None, "circle": None, "geocodes": [{"name": "ORP", "value": "123"}]}]
    }
    alerts, method = api._filter_by_location([alert], 0.0, 0.0)
    assert method == "geocode_fallback"
    assert alerts == [alert]


def test_select_top_alert_and_prefer_language_empty():
    api = module.ChmuApi()
    assert api._select_top_alert([]) is None
    assert api._select_top_alert([{"status": "expired"}]) is None
    assert api._prefer_czech_language([]) == []


@pytest.mark.asyncio
async def test_get_warnings_cache_and_session_close(monkeypatch):
    api = module.ChmuApi()
    api._last_data = {"cached": True}
    api._cache_time = datetime.now(timezone.utc)

    result = await api.get_warnings(50.0, 14.0, session=DummySession(DummyResponse(200, "")))
    assert result["cached"] is True

    async def _fetch(_session):
        return "<alert></alert>"

    monkeypatch.setattr(api, "_fetch_cap_xml", _fetch)
    monkeypatch.setattr(api, "_parse_cap_xml", lambda *_a, **_k: [])

    session = DummySession(DummyResponse(200, "x" * 200))
    api._invalidate_cache()
    result = await api.get_warnings(50.0, 14.0, session=session)
    assert result["all_warnings"] == []
    assert session.closed is False

    api._invalidate_cache()
    result = await api.get_warnings(50.0, 14.0, session=None)
    assert result["all_warnings"] == []


def test_parse_circle_invalid_value():
    api = module.ChmuApi()
    assert api._parse_circle("50.0,14.0 notnum") is None
