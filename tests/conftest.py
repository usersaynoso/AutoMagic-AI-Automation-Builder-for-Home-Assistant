"""Pytest conftest providing minimal homeassistant stubs for unit tests."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType
from unittest.mock import MagicMock
from uuid import uuid4


class _StubModule(ModuleType):
    """Module stub that returns MagicMock for any attribute access.

    This handles `from pkg.sub import name` by making all attribute lookups
    succeed, while still being a proper module.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.__package__ = name
        self.__path__ = []
        self.__all__ = []

    def __getattr__(self, name: str):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return MagicMock()


def _stub_module(name: str) -> _StubModule:
    """Create a stub module and register it in sys.modules."""
    if name in sys.modules and isinstance(sys.modules[name], _StubModule):
        return sys.modules[name]
    mod = _StubModule(name)
    sys.modules[name] = mod
    return mod


# Stub out homeassistant and its submodules before any test imports them.
_HA_MODULES = [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.data_entry_flow",
    "homeassistant.components",
    "homeassistant.components.http",
    "homeassistant.components.websocket_api",
    "homeassistant.components.frontend",
    "homeassistant.components.panel_custom",
    "homeassistant.components.automation",
    "homeassistant.helpers",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.config_validation",
    "voluptuous",
]

for mod_name in _HA_MODULES:
    _stub_module(mod_name)

# --- Override specific stubs that need real behaviour ---

# voluptuous helpers used in config_flow
vol = sys.modules["voluptuous"]
vol.Schema = lambda *a, **kw: MagicMock()
vol.Required = lambda *a, **kw: a[0] if a else MagicMock()
vol.Optional = lambda *a, **kw: a[0] if a else MagicMock()
vol.All = lambda *a, **kw: MagicMock()
vol.In = lambda *a, **kw: MagicMock()
vol.Range = lambda *a, **kw: MagicMock()

# HomeAssistantView needs to be a real class for inheritance
http_mod = sys.modules["homeassistant.components.http"]
http_mod.HomeAssistantView = type("HomeAssistantView", (), {
    "requires_auth": True,
    "json": staticmethod(lambda data, status_code=200: MagicMock()),
})
http_mod.StaticPathConfig = type(
    "StaticPathConfig",
    (),
    {"__init__": lambda self, url_path, path, cache_headers=True: None},
)

ws_mod = sys.modules["homeassistant.components.websocket_api"]
ws_mod.async_register_command = MagicMock()
ws_mod.async_response = lambda f: f
ws_mod.websocket_command = lambda schema: (lambda f: f)
components_mod = sys.modules["homeassistant.components"]
components_mod.websocket_api = ws_mod

frontend_mod = sys.modules["homeassistant.components.frontend"]
frontend_mod.async_register_built_in_panel = MagicMock()
frontend_mod.async_remove_panel = MagicMock()
frontend_mod.add_extra_js_url = MagicMock()

# ConfigFlow / OptionsFlow need to be real classes for inheritance
homeassistant_mod = sys.modules["homeassistant"]
config_entries = sys.modules["homeassistant.config_entries"]


class _ConfigFlow:
    def __init_subclass__(cls, **kwargs):
        return super().__init_subclass__()


class _ConfigSubentryFlow:
    def __init_subclass__(cls, **kwargs):
        return super().__init_subclass__()

    def _get_entry(self):
        return getattr(self, "_entry", MagicMock())


@dataclass
class _ConfigSubentry:
    data: dict
    subentry_type: str
    title: str
    unique_id: str | None = None
    subentry_id: str = field(default_factory=lambda: uuid4().hex)


config_entries.ConfigFlow = _ConfigFlow
config_entries.ConfigEntry = MagicMock
config_entries.ConfigSubentry = _ConfigSubentry
config_entries.ConfigSubentryFlow = _ConfigSubentryFlow
config_entries.OptionsFlow = type("OptionsFlow", (), {})
homeassistant_mod.config_entries = config_entries

# entity_registry.async_get
er = sys.modules["homeassistant.helpers.entity_registry"]
er.async_get = MagicMock()

# callback is a decorator - should be a no-op passthrough
core = sys.modules["homeassistant.core"]
core.callback = lambda f: f
core.HomeAssistant = MagicMock
homeassistant_mod.core = core

# FlowResult is just a dict alias
flow = sys.modules["homeassistant.data_entry_flow"]
flow.FlowResult = dict
