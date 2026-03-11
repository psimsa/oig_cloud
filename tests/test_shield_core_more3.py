from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.shield import core as module


class DummyTelemetry:
    async def send_event(self, **_kwargs):
        return None


class DummyHass:
    def __init__(self):
        self.data = {"core.uuid": "abc"}

    def async_create_task(self, coro):
        coro.close()
        return object()


def test_log_security_event_with_handler():
    shield = module.ServiceShield(DummyHass(), SimpleNamespace(options={}, data={}))
    shield._telemetry_handler = object()
    shield._log_security_event("TEST", {"task_id": "1"})


def test_notify_state_change_handles_exception():
    shield = module.ServiceShield(DummyHass(), SimpleNamespace(options={}, data={}))

    def _bad():
        raise RuntimeError("boom")

    shield.register_state_change_callback(_bad)
    shield._notify_state_change()
