from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.oig_cloud.core import oig_cloud_notification as notif_module


class DummyStore:
    def __init__(self, *_args, **_kwargs):
        self.saved = None
        self.loaded = None

    async def async_save(self, data):
        self.saved = data

    async def async_load(self):
        return self.loaded


class DummyApi:
    def __init__(self, content):
        self._content = content

    async def get_notifications(self, _device_id):
        return {"status": "success", "content": self._content}


def test_parse_html_notifications():
    parser = notif_module.OigNotificationParser()
    html = (
        "<div class='folder'>"
        "<div class='point level-2'></div>"
        "<div class='date'>25. 6. 2025 | 8:13</div>"
        "<div class='row-2'><strong>Box #2206237016</strong> - Short</div>"
        "<div class='body'>Line1<br/>Line2</div>"
        "</div>"
    )
    notifications = parser._parse_html_notifications(html)

    assert len(notifications) == 1
    notif = notifications[0]
    assert notif.device_id == "2206237016"
    assert "Line1" in notif.message
    assert notif.type == "warning"


def test_parse_json_notifications_and_bypass_status():
    parser = notif_module.OigNotificationParser()
    content = "showNotifications([{ 'id': 1, 'type': 'error', 'message': 'Oops', 'time': '2025-01-01T00:00:00' }]);"

    notifications = parser._parse_json_notifications(content)
    assert len(notifications) == 1
    assert notifications[0].type == "error"

    bypass_on = parser.detect_bypass_status("Automatick\u00fd bypass - zapnut")
    bypass_off = parser.detect_bypass_status("automatic bypass - off")
    assert bypass_on is True
    assert bypass_off is False


def test_parse_notification_fallback():
    parser = notif_module.OigNotificationParser()
    notif = parser.parse_notification({"bad": object()})
    assert notif.type == "info"
    assert notif.message == "Unknown notification"


@pytest.mark.asyncio
async def test_notification_manager_update_from_api(monkeypatch):
    html = (
        "<div class='folder'>"
        "<div class='point level-1'></div>"
        "<div class='date'>25. 6. 2025 | 8:13</div>"
        "<div class='row-2'><strong>Box #2206237016</strong> - Info</div>"
        "<div class='body'>Status OK</div>"
        "</div>"
    )

    api = DummyApi(html)
    manager = notif_module.OigNotificationManager(hass=None, api=api, base_url="test")
    manager.set_device_id("2206237016")

    monkeypatch.setattr(notif_module, "Store", DummyStore)

    updated = await manager.update_from_api()
    assert updated is True
    assert manager.get_device_id() == "2206237016"
    assert len(manager._notifications) == 1
