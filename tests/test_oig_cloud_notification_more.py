from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.core import oig_cloud_notification as notif_module


class DummyStore:
    def __init__(self):
        self.saved = None
        self.to_load = None

    async def async_save(self, data):
        self.saved = data

    async def async_load(self):
        return self.to_load


class DummyApi:
    def __init__(self, result):
        self._result = result

    async def get_notifications(self, _device_id):
        return self._result


def _make_html_notification(device="Box #123", message="Hello"):
    return (
        "<div class=\"folder\">"
        "<div class=\"point level-2\"></div>"
        "<div class=\"date\">28. 6. 2025 | 13:05</div>"
        "<div class=\"row-2\"><strong>"
        f"{device}</strong> - Short</div>"
        f"<div class=\"body\">{message}<br/>Line2</div>"
        "</div>"
    )


def test_parse_html_and_deduplicate():
    parser = notif_module.OigNotificationParser()
    html = _make_html_notification()
    content = html + html
    notifications = parser.parse_from_controller_call(content)
    assert len(notifications) == 1
    assert notifications[0].device_id == "123"
    assert "Line2" in notifications[0].message


def test_extract_html_from_json_wrapper():
    parser = notif_module.OigNotificationParser()
    html = _make_html_notification()
    payload = notif_module.json.dumps([[11, "ctrl-notifs", html, None]])
    extracted = parser._extract_html_from_json_response(payload)
    assert extracted == html


def test_extract_show_notifications_payloads_and_json_objects():
    parser = notif_module.OigNotificationParser()
    js = "showNotifications([{ 'type':'error', 'message':'Oops', }, {'type':'warning'}]);"
    payloads = parser._extract_show_notifications_payloads(js)
    assert len(payloads) == 1
    objects = parser._extract_json_objects(payloads[0])
    assert len(objects) == 2


def test_parse_single_notification_invalid_json():
    parser = notif_module.OigNotificationParser()
    assert parser._parse_single_notification("{bad") is None


def test_html_parser_row2_without_dash():
    parser = notif_module._NotificationHtmlParser()
    html = (
        "<div class=\"folder\">"
        "<div class=\"point level-1\"></div>"
        "<div class=\"date\">1. 1. 2025 | 01:00</div>"
        "<div class=\"row-2\"><strong>Box #1</strong>Short</div>"
        "<div class=\"body\">Body</div>"
        "</div>"
    )
    parser.feed(html)
    parser.close()
    assert parser.items[0][3] == "Short"


def test_extract_html_from_json_wrapper_invalid():
    parser = notif_module.OigNotificationParser()
    assert parser._extract_html_from_json_response("not-json") is None


def test_detect_bypass_status_compact_indicators():
    parser = notif_module.OigNotificationParser()
    assert parser.detect_bypass_status('{"bypass":true}') is True
    assert parser.detect_bypass_status('{"bypass":false}') is False


def test_parse_czech_datetime_invalid():
    parser = notif_module.OigNotificationParser()
    timestamp = parser._parse_czech_datetime("bad-date")
    assert isinstance(timestamp, datetime)


def test_detect_bypass_status_tokens():
    parser = notif_module.OigNotificationParser()
    assert parser.detect_bypass_status("Automatic bypass - on") is True
    assert parser.detect_bypass_status("Automatic bypass - off") is False


def test_determine_notification_type_keywords():
    parser = notif_module.OigNotificationParser()
    assert parser._determine_notification_type("chyba baterie", "1") == "error"
    assert parser._determine_notification_type("bypass aktivní", "1") == "warning"
    assert parser._determine_notification_type("dobrý den", "1") == "info"
    assert parser._determine_notification_type("anything", "3") == "error"


def test_clean_json_string_fixes_formatting():
    parser = notif_module.OigNotificationParser()
    dirty = "{'type':'info', 'message':'ok',}//comment"
    cleaned = parser._clean_json_string(dirty)
    assert "\"type\"" in cleaned
    assert "//" not in cleaned


def test_create_notification_from_json_parses_timestamp():
    parser = notif_module.OigNotificationParser()
    data = {
        "type": "warning",
        "message": "msg",
        "timestamp": "2025-01-01T00:00:00",
    }
    notif = parser._create_notification_from_json(data)
    assert notif.type == "warning"
    assert notif.severity == 2


def test_get_priority_name():
    parser = notif_module.OigNotificationParser()
    assert parser._get_priority_name(4) == "critical"
    assert parser._get_priority_name(99) == "info"


def test_parse_notification_fallback(monkeypatch):
    parser = notif_module.OigNotificationParser()
    def _raise(_data):
        raise ValueError("boom")

    monkeypatch.setattr(parser, "_create_notification_from_json", _raise)
    notif = parser.parse_notification({"device_id": "dev"})
    assert notif.message == "Failed to parse notification"
    assert notif.device_id == "dev"


@pytest.mark.asyncio
async def test_manager_save_and_load_storage(monkeypatch):
    store = DummyStore()
    monkeypatch.setattr(notif_module, "Store", lambda *_args, **_kwargs: store)
    hass = SimpleNamespace()
    manager = notif_module.OigNotificationManager(hass, api=SimpleNamespace(), base_url="x")
    manager._bypass_status = True
    notif = notif_module.OigNotification(
        id="n1",
        type="info",
        message="msg",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    await manager._save_notifications_to_storage([notif])
    store.to_load = store.saved
    loaded = await manager._load_notifications_from_storage()
    assert len(loaded) == 1
    assert manager._bypass_status is True


@pytest.mark.asyncio
async def test_manager_refresh_data(monkeypatch):
    manager = notif_module.OigNotificationManager(SimpleNamespace(), api=SimpleNamespace(), base_url="x")

    async def _update():
        return True

    monkeypatch.setattr(manager, "update_from_api", _update)
    assert await manager.refresh_data() is True


@pytest.mark.asyncio
async def test_update_from_api_success(monkeypatch):
    store = DummyStore()
    monkeypatch.setattr(notif_module, "Store", lambda *_args, **_kwargs: store)
    html = _make_html_notification(message="Automatic bypass - on")
    api = DummyApi({"status": "success", "content": html})
    manager = notif_module.OigNotificationManager(SimpleNamespace(), api=api, base_url="x")
    manager.set_device_id("123")
    result = await manager.update_from_api()
    assert result is True
    assert manager.get_notification_count("warning") == 1
    assert manager.get_bypass_status() == "on"


@pytest.mark.asyncio
async def test_update_from_api_missing_device_id():
    manager = notif_module.OigNotificationManager(SimpleNamespace(), api=SimpleNamespace(), base_url="x")
    assert await manager.update_from_api() is False


@pytest.mark.asyncio
async def test_update_from_api_missing_method_uses_cache(monkeypatch):
    manager = notif_module.OigNotificationManager(SimpleNamespace(), api=SimpleNamespace(), base_url="x")
    manager.set_device_id("123")
    cached = [
        notif_module.OigNotification(
            id="n1",
            type="info",
            message="cached",
            timestamp=datetime.now(),
        )
    ]
    async def _load():
        return cached

    monkeypatch.setattr(manager, "_load_notifications_from_storage", _load)
    assert await manager.update_from_api() is True
    assert manager.get_latest_notification_message() == "cached"


@pytest.mark.asyncio
async def test_update_from_api_error_uses_cache(monkeypatch):
    api = DummyApi({"error": "fail"})
    manager = notif_module.OigNotificationManager(SimpleNamespace(), api=api, base_url="x")
    manager.set_device_id("123")
    cached = [
        notif_module.OigNotification(
            id="n1",
            type="warning",
            message="cached",
            timestamp=datetime.now(),
        )
    ]

    async def _load():
        return cached

    monkeypatch.setattr(manager, "_load_notifications_from_storage", _load)
    assert await manager.update_from_api() is True
    assert manager.get_notification_count("warning") == 1


def test_manager_counts_and_latest():
    manager = notif_module.OigNotificationManager(SimpleNamespace(), api=SimpleNamespace(), base_url="x")
    manager._notifications = [
        notif_module.OigNotification(
            id="n1",
            type="warning",
            message="first",
            timestamp=datetime.now(),
            read=False,
        ),
        notif_module.OigNotification(
            id="n2",
            type="error",
            message="second",
            timestamp=datetime.now(),
            read=True,
        ),
    ]
    assert manager.get_notification_count("warning") == 1
    assert manager.get_notification_count("error") == 1
    assert manager.get_notification_count("info") == 0
    assert manager.get_unread_count() == 1
    assert manager.get_latest_notification_message() == "first"


@pytest.mark.asyncio
async def test_load_notifications_handles_error(monkeypatch):
    class BadStore:
        async def async_load(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(notif_module, "Store", lambda *_args, **_kwargs: BadStore())
    manager = notif_module.OigNotificationManager(SimpleNamespace(), api=SimpleNamespace(), base_url="x")
    loaded = await manager._load_notifications_from_storage()
    assert loaded == []
