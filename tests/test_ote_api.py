from __future__ import annotations

import json
import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

import custom_components.oig_cloud.api.ote_api as ote_module
from custom_components.oig_cloud.api.ote_api import CnbRate, OTEFault, OteApi, UpdateFailed


class DummyResponse:
    def __init__(self, status=200, json_data=None, text_data=""):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _tb):
        return None

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data


class DummySession:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _tb):
        return None

    def get(self, *_args, **_kwargs):
        return self._response

    def post(self, *_args, **_kwargs):
        return self._response


def test_get_current_15min_interval():
    ts = datetime(2025, 1, 1, 10, 31, 0)
    assert OteApi.get_current_15min_interval(ts) == 42


def test_get_15min_price_for_interval():
    spot_data = {
        "prices15m_czk_kwh": {
            "2025-01-01T10:30:00": 3.5,
        }
    }
    price = OteApi.get_15min_price_for_interval(
        42, spot_data, target_date=date(2025, 1, 1)
    )
    assert price == 3.5

    assert OteApi.get_15min_price_for_interval(0, {}, target_date=date(2025, 1, 1)) is None
    assert OteApi.get_15min_price_for_interval(0, spot_data) is None


@pytest.mark.asyncio
async def test_ote_api_close_noop():
    api = OteApi()
    assert await api.close() is None


def test_soap_headers():
    headers = ote_module._soap_headers("GetDamPricePeriodE")
    assert headers["Content-Type"] == "text/xml; charset=utf-8"


def test_parse_period_interval_dst_suffix():
    api = OteApi()
    dt_utc = api._parse_period_interval(date(2025, 10, 26), "02b:00-02b:15")
    assert dt_utc.minute == 1


def test_parse_period_interval_first_occurrence():
    api = OteApi()
    dt_utc = api._parse_period_interval(date(2025, 10, 26), "02a:00-02a:15")
    assert dt_utc.minute == 0


def test_parse_period_interval_overflow():
    api = OteApi()
    dt_utc = api._parse_period_interval(date(2025, 10, 26), "02b:59-03b:14")
    assert dt_utc.minute == 0
    assert dt_utc.tzinfo == api.utc


def test_aggregate_quarter_to_hour():
    api = OteApi()
    base = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    qh_map = {
        base: Decimal("1"),
        base + timedelta(minutes=15): Decimal("2"),
        base + timedelta(minutes=30): Decimal("3"),
        base + timedelta(minutes=45): Decimal("4"),
    }
    result = api._aggregate_quarter_to_hour(qh_map)
    assert result[base] == Decimal("2.5")


def test_is_cache_valid_requires_tomorrow_after_13(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 1, 14, 0, 0, tzinfo=tz)

    monkeypatch.setattr(ote_module, "datetime", FixedDateTime)
    api = OteApi()
    api._cache_time = FixedDateTime.now(api.timezone)
    api._last_data = {
        "prices_czk_kwh": {"2025-01-01T10:00:00": 1.0},
    }
    assert api._is_cache_valid() is False

    api._last_data["prices_czk_kwh"]["2025-01-02T10:00:00"] = 1.1
    assert api._is_cache_valid() is True


def test_is_cache_valid_missing_today(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 1, 10, 0, 0, tzinfo=tz)

    monkeypatch.setattr(ote_module, "datetime", FixedDateTime)
    api = OteApi()
    api._cache_time = FixedDateTime.now(api.timezone)
    api._last_data = {"prices_czk_kwh": {"2025-01-02T10:00:00": 1.0}}
    assert api._is_cache_valid() is False


def test_cache_helpers(tmp_path):
    cache_file = tmp_path / "cache.json"
    api = OteApi(cache_path=str(cache_file))
    api._last_data = {"prices_czk_kwh": {"2025-01-01T10:00:00": 1.0}}
    api._cache_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=api.timezone)
    api._persist_cache_sync()
    assert cache_file.exists()

    api2 = OteApi(cache_path=str(cache_file))
    api2._load_cached_spot_prices_sync()
    assert api2._last_data

    api3 = OteApi(cache_path=str(tmp_path / "missing.json"))
    api3._load_cached_spot_prices_sync()
    assert api3._last_data == {}


def test_cache_helpers_no_path(monkeypatch):
    api = OteApi()
    api._last_data = {"prices_czk_kwh": {"2025-01-01T10:00:00": 1.0}}
    api._load_cached_spot_prices_sync()
    api._persist_cache_sync()


def test_cache_helpers_bad_cache(tmp_path):
    cache_file = tmp_path / "bad_cache.json"
    cache_file.write_text("{bad json", encoding="utf-8")
    api = OteApi(cache_path=str(cache_file))
    api._load_cached_spot_prices_sync()


@pytest.mark.asyncio
async def test_async_cache_load_failure(monkeypatch):
    api = OteApi()

    async def boom(_func):
        raise RuntimeError("boom")

    monkeypatch.setattr(ote_module.asyncio, "to_thread", boom)
    await api.async_load_cached_spot_prices()


def test_persist_cache_creates_dir(tmp_path):
    cache_file = tmp_path / "nested" / "cache.json"
    api = OteApi(cache_path=str(cache_file))
    api._last_data = {"prices_czk_kwh": {"2025-01-01T10:00:00": 1.0}}
    api._cache_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=api.timezone)
    api._persist_cache_sync()
    assert cache_file.exists()


def test_persist_cache_sync_error(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    api = OteApi(cache_path=str(cache_file))
    api._last_data = {"prices_czk_kwh": {"2025-01-01T10:00:00": 1.0}}
    api._cache_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=api.timezone)

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(json, "dump", boom)
    api._persist_cache_sync()


@pytest.mark.asyncio
async def test_async_persist_cache_failure(monkeypatch):
    api = OteApi()

    async def boom(_func):
        raise RuntimeError("boom")

    monkeypatch.setattr(ote_module.asyncio, "to_thread", boom)
    await api.async_persist_cache()


@pytest.mark.asyncio
async def test_format_spot_data_includes_15m_prices():
    api = OteApi()
    today = datetime(2025, 1, 1, 0, 0, tzinfo=api.utc)
    tomorrow = today + timedelta(days=1)
    hourly_czk = {today: 1.0, tomorrow: 2.0}
    hourly_eur = {today: Decimal("0.1"), tomorrow: Decimal("0.2")}
    qh_rates_czk = {today: 1.0}
    qh_rates_eur = {today: Decimal("0.1")}

    data = await api._format_spot_data(
        hourly_czk,
        hourly_eur,
        eur_czk_rate=25.0,
        reference_date=today,
        qh_rates_czk=qh_rates_czk,
        qh_rates_eur=qh_rates_eur,
    )

    assert data["prices_czk_kwh"]
    assert data["prices15m_czk_kwh"]
    assert data["today_stats"]["min_czk"] == 1.0


def test_dam_period_query():
    api = OteApi()
    query = api._dam_period_query(date(2025, 1, 1), date(2025, 1, 2), 1, 2)
    assert "<pub:StartPeriod>1</pub:StartPeriod>" in query
    assert "<pub:EndPeriod>2</pub:EndPeriod>" in query


def test_parse_soap_response_fault():
    api = OteApi()
    soap = (
        f"<soapenv:Envelope xmlns:soapenv=\"{ote_module.SOAPENV}\">"
        "<soapenv:Body><soapenv:Fault><faultstring>oops</faultstring></soapenv:Fault></soapenv:Body>"
        "</soapenv:Envelope>"
    )
    with pytest.raises(OTEFault):
        api._parse_soap_response(soap)


def test_parse_soap_response_invalid():
    api = OteApi()
    with pytest.raises(UpdateFailed):
        api._parse_soap_response("bad xml")


def test_parse_soap_response_portal_unavailable():
    api = OteApi()
    with pytest.raises(UpdateFailed):
        api._parse_soap_response("Application is not available")


@pytest.mark.asyncio
async def test_download_rates_validation_error(monkeypatch):
    rate = CnbRate()
    response = DummyResponse(
        status=400, json_data={"errorCode": "VALIDATION_ERROR"}
    )
    monkeypatch.setattr(
        ote_module.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: DummySession(response),
    )

    with pytest.raises(ote_module.InvalidDateError):
        await rate.download_rates(date(2025, 1, 1))


@pytest.mark.asyncio
async def test_download_rates_http_error(monkeypatch):
    rate = CnbRate()
    response = DummyResponse(status=500, json_data={})
    monkeypatch.setattr(
        ote_module.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: DummySession(response),
    )

    with pytest.raises(Exception):
        await rate.download_rates(date(2025, 1, 1))


@pytest.mark.asyncio
async def test_download_rates_success(monkeypatch):
    rate = CnbRate()
    response = DummyResponse(status=200, json_data={"rates": []})
    monkeypatch.setattr(
        ote_module.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: DummySession(response),
    )

    result = await rate.download_rates(date(2025, 1, 1))
    assert "rates" in result


@pytest.mark.asyncio
async def test_get_dam_period_prices_parses(monkeypatch):
    api = OteApi()
    xml = f"""
    <Envelope xmlns="{ote_module.SOAPENV}">
      <Body>
        <Item xmlns="{ote_module.NAMESPACE}">
          <Date>2025-01-01</Date>
          <PeriodInterval>00:00-00:15</PeriodInterval>
          <PeriodResolution>PT15M</PeriodResolution>
          <Price>10</Price>
        </Item>
        <Item xmlns="{ote_module.NAMESPACE}">
          <Date>2025-01-01</Date>
          <PeriodInterval>00:00-00:15</PeriodInterval>
          <PeriodResolution>PT60M</PeriodResolution>
          <Price>10</Price>
        </Item>
      </Body>
    </Envelope>
    """

    async def fake_download(*_args, **_kwargs):
        return xml

    monkeypatch.setattr(api, "_download_soap", fake_download)
    result = await api._get_dam_period_prices(date(2025, 1, 1), date(2025, 1, 1))
    assert result


@pytest.mark.asyncio
async def test_get_dam_period_prices_skips_invalid(monkeypatch):
    api = OteApi()
    xml = f"""
    <Envelope xmlns="{ote_module.SOAPENV}">
      <Body>
        <Item xmlns="{ote_module.NAMESPACE}">
          <Date></Date>
          <PeriodInterval>00:00-00:15</PeriodInterval>
          <PeriodResolution>PT15M</PeriodResolution>
          <Price>10</Price>
        </Item>
        <Item xmlns="{ote_module.NAMESPACE}">
          <Date>2025-01-01</Date>
          <PeriodInterval></PeriodInterval>
          <PeriodResolution>PT15M</PeriodResolution>
          <Price>10</Price>
        </Item>
      </Body>
    </Envelope>
    """

    async def fake_download(*_args, **_kwargs):
        return xml

    monkeypatch.setattr(api, "_download_soap", fake_download)
    result = await api._get_dam_period_prices(date(2025, 1, 1), date(2025, 1, 1))
    assert result == {}


@pytest.mark.asyncio
async def test_get_dam_period_prices_missing_elements(monkeypatch):
    api = OteApi()
    xml = f"""
    <Envelope xmlns="{ote_module.SOAPENV}">
      <Body>
        <Item xmlns="{ote_module.NAMESPACE}">
          <Date>2025-01-01</Date>
          <PeriodInterval>00:00-00:15</PeriodInterval>
          <PeriodResolution>PT15M</PeriodResolution>
        </Item>
      </Body>
    </Envelope>
    """

    async def fake_download(*_args, **_kwargs):
        return xml

    monkeypatch.setattr(api, "_download_soap", fake_download)
    result = await api._get_dam_period_prices(date(2025, 1, 1), date(2025, 1, 1))
    assert result == {}


@pytest.mark.asyncio
async def test_cnb_rate_get_day_rates(monkeypatch):
    rate = CnbRate()

    async def fake_download(day):
        return {
            "rates": [
                {"currencyCode": "EUR", "rate": 25.0},
            ]
        }

    monkeypatch.setattr(rate, "download_rates", fake_download)
    rates = await rate.get_day_rates(date(2025, 1, 1))
    assert rates["EUR"] == 25


@pytest.mark.asyncio
async def test_cnb_rate_get_day_rates_failure(monkeypatch):
    rate = CnbRate()

    async def fake_download(day):
        raise ote_module.InvalidDateError("bad")

    monkeypatch.setattr(rate, "download_rates", fake_download)
    with pytest.raises(Exception):
        await rate.get_day_rates(date(2025, 1, 1))


@pytest.mark.asyncio
async def test_cnb_rate_get_current_rates_cache(monkeypatch):
    rate = CnbRate()
    today = datetime.now(timezone.utc).date()
    rate._rates = {"EUR": Decimal("25")}
    rate._last_checked_date = today
    rates = await rate.get_current_rates()
    assert rates["EUR"] == Decimal("25")


@pytest.mark.asyncio
async def test_cnb_rate_get_current_rates_updates(monkeypatch):
    rate = CnbRate()
    today = datetime.now(timezone.utc).date()

    async def fake_day_rates(_day):
        return {"EUR": Decimal("26")}

    monkeypatch.setattr(rate, "get_day_rates", fake_day_rates)
    rates = await rate.get_current_rates()
    assert rates["EUR"] == Decimal("26")
    assert rate._last_checked_date == today


@pytest.mark.asyncio
async def test_get_cnb_exchange_rate(monkeypatch):
    api = OteApi()

    async def fake_rates():
        return {"EUR": Decimal("25")}

    monkeypatch.setattr(api._cnb_rate, "get_current_rates", fake_rates)
    rate = await api.get_cnb_exchange_rate()
    assert rate == 25.0

    async def fake_empty():
        return {}

    api._rate_cache_time = None
    monkeypatch.setattr(api._cnb_rate, "get_current_rates", fake_empty)
    assert await api.get_cnb_exchange_rate() is None


@pytest.mark.asyncio
async def test_get_cnb_exchange_rate_cached(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 1, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(ote_module, "datetime", FixedDateTime)
    api = OteApi()
    api._rate_cache_time = FixedDateTime.now()
    api._eur_czk_rate = 24.5

    rate = await api.get_cnb_exchange_rate()
    assert rate == 24.5


@pytest.mark.asyncio
async def test_get_spot_prices_uses_cache(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 1, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(ote_module, "datetime", FixedDateTime)
    api = OteApi()
    api._cache_time = FixedDateTime.now(api.timezone)
    api._last_data = {"prices_czk_kwh": {"2025-01-01T10:00:00": 1.0}}
    result = await api.get_spot_prices()
    assert result == api._last_data


@pytest.mark.asyncio
async def test_get_spot_prices_fetch_and_fallback(monkeypatch):
    api = OteApi()

    async def fake_rate():
        return None

    async def fake_qh(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(api, "get_cnb_exchange_rate", fake_rate)
    monkeypatch.setattr(api, "_get_dam_period_prices", fake_qh)
    result = await api.get_spot_prices()
    assert result == {}


@pytest.mark.asyncio
async def test_get_spot_prices_force_today(monkeypatch):
    api = OteApi()

    async def fake_rate():
        return 25.0

    async def fake_qh(*_args, **_kwargs):
        base = datetime(2025, 1, 1, 0, 0, tzinfo=api.utc)
        return {base: Decimal("0.1")}

    async def fake_format(*_args, **_kwargs):
        return {"prices_czk_kwh": {"2025-01-01T00:00:00": 1.0}}

    async def fake_persist():
        return None

    monkeypatch.setattr(api, "get_cnb_exchange_rate", fake_rate)
    monkeypatch.setattr(api, "_get_dam_period_prices", fake_qh)
    monkeypatch.setattr(api, "_format_spot_data", fake_format)
    monkeypatch.setattr(api, "async_persist_cache", fake_persist)
    result = await api.get_spot_prices(
        date=datetime(2025, 1, 1, tzinfo=api.timezone),
        force_today_only=True,
    )
    assert result["prices_czk_kwh"]


@pytest.mark.asyncio
async def test_get_spot_prices_after_13(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 1, 14, 0, 0, tzinfo=tz)

    monkeypatch.setattr(ote_module, "datetime", FixedDateTime)
    api = OteApi()
    base = datetime(2025, 1, 1, 0, 0, tzinfo=api.utc)

    async def fake_rate():
        return 25.0

    async def fake_qh(*_args, **_kwargs):
        return {
            base: Decimal("0.1"),
            base + timedelta(minutes=15): Decimal("0.2"),
        }

    async def fake_format(*_args, **_kwargs):
        return {"prices_czk_kwh": {"2025-01-01T00:00:00": 1.0}}

    async def fake_persist():
        return None

    monkeypatch.setattr(api, "get_cnb_exchange_rate", fake_rate)
    monkeypatch.setattr(api, "_get_dam_period_prices", fake_qh)
    monkeypatch.setattr(api, "_format_spot_data", fake_format)
    monkeypatch.setattr(api, "async_persist_cache", fake_persist)

    result = await api.get_spot_prices(
        date=datetime(2025, 1, 1, tzinfo=api.timezone),
        force_today_only=False,
    )
    assert result["prices_czk_kwh"]


@pytest.mark.asyncio
async def test_get_spot_prices_full_success(monkeypatch):
    api = OteApi()
    base = datetime(2025, 1, 1, 0, 0, tzinfo=api.utc)
    called = {"persist": 0}

    async def fake_rate():
        return 25.0

    async def fake_qh(*_args, **_kwargs):
        return {
            base: Decimal("0.1"),
            base + timedelta(minutes=15): Decimal("0.2"),
        }

    async def fake_format(*_args, **_kwargs):
        return {"prices_czk_kwh": {"2025-01-01T00:00:00": 1.0}}

    async def fake_persist():
        called["persist"] += 1

    monkeypatch.setattr(api, "get_cnb_exchange_rate", fake_rate)
    monkeypatch.setattr(api, "_get_dam_period_prices", fake_qh)
    monkeypatch.setattr(api, "_format_spot_data", fake_format)
    monkeypatch.setattr(api, "async_persist_cache", fake_persist)
    result = await api.get_spot_prices(
        date=datetime(2025, 1, 1, tzinfo=api.timezone),
        force_today_only=True,
    )

    assert result["prices_czk_kwh"]
    assert called["persist"] == 1


@pytest.mark.asyncio
async def test_get_spot_prices_fallback_to_cache_on_error(monkeypatch):
    api = OteApi()
    api._last_data = {"prices_czk_kwh": {"2025-01-01T10:00:00": 1.0}}

    async def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(api, "_get_dam_period_prices", boom)
    result = await api.get_spot_prices()
    assert result == api._last_data


@pytest.mark.asyncio
async def test_get_spot_prices_error_no_cache(monkeypatch):
    api = OteApi()

    async def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(api, "_get_dam_period_prices", boom)
    result = await api.get_spot_prices()
    assert result == {}


@pytest.mark.asyncio
async def test_cnb_rate_retries(monkeypatch):
    rate = CnbRate()

    calls = {"count": 0}

    async def fake_download(day):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ote_module.InvalidDateError("bad")
        return {"rates": [{"currencyCode": "EUR", "rate": 25.0}]}

    monkeypatch.setattr(rate, "download_rates", fake_download)
    rates = await rate.get_day_rates(date(2025, 1, 1))
    assert rates["EUR"] == 25


@pytest.mark.asyncio
async def test_format_spot_data_empty():
    api = OteApi()
    data = await api._format_spot_data({}, {}, 25.0, datetime.now(api.utc))
    assert data == {}


def test_has_data_for_date_helpers():
    api = OteApi()
    assert api._has_data_for_date(date(2025, 1, 1)) is False
    api._last_data = {"prices_czk_kwh": {}}
    assert api._has_data_for_date(date(2025, 1, 1)) is False


def test_should_fetch_new_data(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 1, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(ote_module, "datetime", FixedDateTime)
    api = OteApi()
    api._cache_time = FixedDateTime.now(api.timezone)
    api._last_data = {"prices_czk_kwh": {"2025-01-01T10:00:00": 1.0}}
    assert api._should_fetch_new_data() is False


@pytest.mark.asyncio
async def test_download_soap_success(monkeypatch):
    api = OteApi()
    response = DummyResponse(status=200, text_data="ok")
    monkeypatch.setattr(
        ote_module.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: DummySession(response),
    )

    result = await api._download_soap("<xml />", "GetDamPricePeriodE")
    assert result == "ok"


@pytest.mark.asyncio
async def test_download_soap_error(monkeypatch):
    api = OteApi()
    response = DummyResponse(status=500, text_data="oops")
    monkeypatch.setattr(
        ote_module.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: DummySession(response),
    )
    with pytest.raises(OTEFault):
        await api._download_soap("<xml />", "GetDamPricePeriodE")
