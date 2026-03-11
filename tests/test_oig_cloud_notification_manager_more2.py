from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.core import oig_cloud_notification as module


class DummyStore:
    def __init__(self, *_a, **_k):
        self.saved = None
        self.data = None

    async def async_save(self, data):
        self.saved = data

    async def async_load(self):
        return self.data


class DummyApi:
    def __init__(self, result):
        self._result = result

    async def get_notifications(self, _device_id):
        return self._result


class DummyHass:
    pass


def test_parser_extract_html_from_json():
    parser = module.OigNotificationParser()
    content = '[[11,"ctrl-notifs","&lt;div&gt;ok&lt;/div&gt;",null]]'
    assert parser._extract_html_from_json_response(content) == "<div>ok</div>"


def test_parse_notification_fallback():
    parser = module.OigNotificationParser()
    notif = parser.parse_notification({"device_id": "123"})
    assert notif.device_id == "123"


def test_html_parser_early_returns():
    parser = module._NotificationHtmlParser()
    parser.handle_starttag("div", [("class", "point")])
    parser.handle_data("data")
    assert parser.items == []


@pytest.mark.asyncio
async def test_manager_update_from_api_success(monkeypatch):
    api = DummyApi({"status": "success", "content": "<div></div>"})
    mgr = module.OigNotificationManager(DummyHass(), api, "http://x")
    mgr.set_device_id("123")

    monkeypatch.setattr(mgr._parser, "parse_from_controller_call", lambda _c: [])
    monkeypatch.setattr(mgr._parser, "detect_bypass_status", lambda _c: True)

    store = DummyStore()
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: store)
    assert await mgr.update_from_api() is True
    assert mgr.get_bypass_status() == "on"


@pytest.mark.asyncio
async def test_manager_update_from_api_error_uses_cache(monkeypatch):
    api = DummyApi({"error": "bad"})
    mgr = module.OigNotificationManager(DummyHass(), api, "http://x")
    mgr.set_device_id("123")

    store = DummyStore()
    store.data = {
        "notifications": [
            {
                "id": "1",
                "type": "info",
                "message": "m",
                "timestamp": datetime.now().isoformat(),
            }
        ],
        "bypass_status": True,
    }
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: store)
    assert await mgr.update_from_api() is True


@pytest.mark.asyncio
async def test_manager_update_from_api_missing_method(monkeypatch):
    api = SimpleNamespace()
    mgr = module.OigNotificationManager(DummyHass(), api, "http://x")
    mgr.set_device_id("123")

    store = DummyStore()
    store.data = {"notifications": []}
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: store)
    assert await mgr.update_from_api() is False


def test_create_notification_from_html_bypass():
    parser = module.OigNotificationParser()
    notif = parser._create_notification_from_html(
        "2",
        "25. 6. 2025 | 8:13",
        "Box #123",
        "short",
        "Bypass active",
    )
    assert notif is not None
    assert notif.type == "warning"


def test_parse_from_controller_call_paths(monkeypatch):
    parser = module.OigNotificationParser()

    monkeypatch.setattr(parser, "_extract_html_from_json_response", lambda _c: "<div></div>")
    monkeypatch.setattr(parser, "_parse_html_notifications", lambda _c: [])
    monkeypatch.setattr(parser, "_parse_json_notifications", lambda _c: [])
    assert parser.parse_from_controller_call("payload") == []

    def _boom(_c):
        raise RuntimeError("boom")

    monkeypatch.setattr(parser, "_parse_html_notifications", _boom)
    assert parser.parse_from_controller_call("payload") == []


def test_extract_html_from_json_response_errors(monkeypatch):
    parser = module.OigNotificationParser()
    content = '[[11,"ctrl-notifs",null,null]]'
    assert parser._extract_html_from_json_response(content) is None

    def _raise(_content):
        raise RuntimeError("bad")

    monkeypatch.setattr(module.json, "loads", _raise)
    assert parser._extract_html_from_json_response("[") is None


def test_parse_html_notifications_error_paths(monkeypatch):
    parser = module.OigNotificationParser()

    class DummyParser:
        def __init__(self):
            self.items = [("1", "25. 6. 2025 | 8:13", "Box #1", "s", "f")]

        def feed(self, *_a, **_k):
            return None

        def close(self):
            return None

    monkeypatch.setattr(module, "_NotificationHtmlParser", DummyParser)
    monkeypatch.setattr(
        parser,
        "_create_notification_from_html",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("fail")),
    )
    assert parser._parse_html_notifications("x" * (parser._max_parse_chars + 1)) == []


def test_parse_json_notifications_error_paths(monkeypatch):
    parser = module.OigNotificationParser()

    monkeypatch.setattr(parser, "_extract_show_notifications_payloads", lambda _c: [])
    monkeypatch.setattr(parser, "_extract_json_objects", lambda _c: ["{bad"])
    assert parser._parse_json_notifications("x") == []

    def _boom(_c):
        raise RuntimeError("fail")

    monkeypatch.setattr(parser, "_extract_show_notifications_payloads", _boom)
    assert parser._parse_json_notifications("x") == []


def test_extract_show_notifications_payloads_and_paren_helpers():
    parser = module.OigNotificationParser()
    assert parser._extract_show_notifications_payloads("showNotifications") == []
    assert parser._extract_show_notifications_payloads("showNotifications(") == []

    text = 'showNotifications("a\\\\")b")'
    open_index = text.find("(")
    assert parser._find_matching_paren(text, open_index) == 23

    text = 'showNotifications("a\\\\")")'
    open_index = text.find("(")
    assert parser._find_matching_paren(text, open_index) == 23

    assert parser._extract_json_objects('{"a":"b\\\\\\"c"}') == ['{"a":"b\\\\\\"c"}']


def test_parse_single_notification_exception(monkeypatch):
    parser = module.OigNotificationParser()
    monkeypatch.setattr(
        parser, "_clean_json_string", lambda _c: (_ for _ in ()).throw(RuntimeError("fail"))
    )
    assert parser._parse_single_notification('{"a":1}') is None


def test_create_notification_from_html_error(monkeypatch):
    parser = module.OigNotificationParser()
    monkeypatch.setattr(
        parser, "_parse_czech_datetime", lambda _c: (_ for _ in ()).throw(RuntimeError("bad"))
    )
    assert (
        parser._create_notification_from_html(
            "1", "25. 6. 2025 | 8:13", "Box #1", "short", "full"
        )
        is None
    )


def test_detect_bypass_status_error():
    parser = module.OigNotificationParser()

    class BadContent:
        def lower(self):
            raise RuntimeError("nope")

    assert parser.detect_bypass_status(BadContent()) is False


def test_determine_notification_type_variants():
    parser = module.OigNotificationParser()
    assert parser._determine_notification_type("ok", "bad") == "info"
    assert parser._determine_notification_type("ok", "2") == "warning"
    assert parser._determine_notification_type("Pozor na limit", "1") == "warning"
    assert parser._determine_notification_type("random", "5") == "error"


def test_create_notification_from_json_edge_cases():
    parser = module.OigNotificationParser()
    notif = parser._create_notification_from_json(
        {"type": "info", "message": "x", "timestamp": "bad", "time": "also-bad"}
    )
    assert notif is not None
    assert parser._create_notification_from_json(None) is None


def test_generate_nonce_and_latest_helpers():
    mgr = module.OigNotificationManager(
        DummyHass(), DummyApi({"status": "success", "content": ""}), "http://x"
    )
    nonce = mgr._generate_nonce()
    assert nonce.isdigit()
    assert mgr.get_latest_notification_message() == "No notifications"
    assert mgr.get_latest_notification() is None


@pytest.mark.asyncio
async def test_manager_update_from_api_unexpected_response(monkeypatch):
    api = DummyApi({"status": "success"})
    mgr = module.OigNotificationManager(DummyHass(), api, "http://x")
    mgr.set_device_id("123")
    assert await mgr.update_from_api() is False


@pytest.mark.asyncio
async def test_manager_update_from_api_missing_get_notifications(monkeypatch):
    api = SimpleNamespace(notification_list=lambda: [])
    mgr = module.OigNotificationManager(DummyHass(), api, "http://x")
    mgr.set_device_id("123")

    store = DummyStore()
    store.data = {"notifications": []}
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: store)
    assert await mgr.update_from_api() is False


@pytest.mark.asyncio
async def test_manager_update_from_api_exception_uses_cache(monkeypatch):
    class BoomApi:
        async def get_notifications(self, _device_id):
            raise RuntimeError("boom")

    mgr = module.OigNotificationManager(DummyHass(), BoomApi(), "http://x")
    mgr.set_device_id("123")

    async def _load():
        raise RuntimeError("no cache")

    monkeypatch.setattr(mgr, "_load_notifications_from_storage", _load)
    assert await mgr.update_from_api() is False


@pytest.mark.asyncio
async def test_manager_load_save_storage_errors(monkeypatch):
    mgr = module.OigNotificationManager(
        DummyHass(), DummyApi({"status": "success", "content": ""}), "http://x"
    )

    class BadStore(DummyStore):
        async def async_save(self, _data):
            raise RuntimeError("save fail")

        async def async_load(self):
            return None

    monkeypatch.setattr(module, "Store", lambda *_a, **_k: BadStore())
    await mgr._save_notifications_to_storage([])
    assert await mgr._load_notifications_from_storage() == []


@pytest.mark.asyncio
async def test_manager_load_storage_bad_notification(monkeypatch):
    mgr = module.OigNotificationManager(
        DummyHass(), DummyApi({"status": "success", "content": ""}), "http://x"
    )

    store = DummyStore()
    store.data = {
        "notifications": [{"id": "1"}],
        "bypass_status": False,
    }
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: store)
    assert await mgr._load_notifications_from_storage() == []


@pytest.mark.asyncio
async def test_update_notifications_error(monkeypatch):
    mgr = module.OigNotificationManager(
        DummyHass(), DummyApi({"status": "success", "content": ""}), "http://x"
    )

    async def _save(_n):
        raise RuntimeError("no save")

    monkeypatch.setattr(mgr, "_save_notifications_to_storage", _save)
    await mgr._update_notifications([])


@pytest.mark.asyncio
async def test_get_notifications_and_status_calls_update(monkeypatch):
    mgr = module.OigNotificationManager(
        DummyHass(), DummyApi({"status": "success", "content": ""}), "http://x"
    )

    async def _update():
        mgr._notifications = []
        mgr._bypass_status = True
        return True

    monkeypatch.setattr(mgr, "update_from_api", _update)
    notifications, status = await mgr.get_notifications_and_status()
    assert notifications == []
    assert status is True
