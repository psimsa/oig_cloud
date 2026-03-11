from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import core as module


class DummyHass:
    def __init__(self):
        self.data = {"core.uuid": "abc"}

    def async_create_task(self, coro):
        coro.close()
        return object()

    class Services:
        def async_register(self, *_args, **_kwargs):
            return None

    @property
    def services(self):
        return self.Services()


def test_setup_telemetry_failure(monkeypatch):
    def _raise(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "setup_simple_telemetry", _raise)
    shield = module.ServiceShield(DummyHass(), SimpleNamespace(options={}, data={}))
    assert shield.telemetry_handler is None


def test_setup_state_listener_without_pending():
    shield = module.ServiceShield(DummyHass(), SimpleNamespace(options={}, data={}))
    shield.pending = {}
    shield._setup_state_listener()
    assert shield._state_listener_unsub is None
