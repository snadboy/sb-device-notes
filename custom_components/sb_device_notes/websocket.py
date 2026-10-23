"""WebSocket API for the sidebar page (admins only).

  sb_device_notes/list                          → fields, devices (with their fields/values), waiting records
  sb_device_notes/subscribe                     → an empty event whenever anything changes
  sb_device_notes/set   {device_id, field, value}   (empty value clears)
  sb_device_notes/add_to_device {device_id, field}
  sb_device_notes/forget {record_id}
  sb_device_notes/field_add {name, type, scope, integrations}
  sb_device_notes/field_update {field, name?, type?, scope?, integrations?}
  sb_device_notes/field_delete {field}

Validation errors come back as `invalid` errors carrying the notebook's message, so the
page can show them next to the field.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, SIGNAL_UPDATED
from .manager import NotesManager
from .model import FIELD_TYPES, SCOPES, NoteError, display


def _manager(hass: HomeAssistant) -> NotesManager | None:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0].runtime_data if entries else None


def _record_view(book, rid: str, rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": rid,
        "values": {
            fid: {"raw": v, "display": display(book.fields[fid]["type"], v)}
            for fid, v in rec["values"].items()
            if fid in book.fields
        },
    }


def _snapshot(manager: NotesManager) -> dict[str, Any]:
    book = manager.book
    devices = []
    for dev in manager.devices.values():
        found = book.for_device(dev.id)
        view = _record_view(book, *found) if found else {"record_id": None, "values": {}}
        devices.append(
            {
                "device_id": dev.id,
                "name": dev.name,
                "area": dev.area,
                "manufacturer": dev.manufacturer,
                "model": dev.model,
                "integration": dev.integration,
                "visible": book.visible(dev),
                "unavailable": dev.id in manager.unavailable,
                **view,
            }
        )
    waiting = [
        {
            "name": rec["name"],
            "area": rec["area"],
            "manufacturer": rec["manufacturer"],
            "model": rec["model"],
            "updated": rec["updated"],
            **_record_view(book, rid, rec),
        }
        for rid, rec in book.waiting()
    ]
    fields = [
        {"id": fid, **f, "usage": book.field_usage(fid)} for fid, f in book.fields.items()
    ]
    return {
        "fields": fields,
        "devices": devices,
        "waiting": waiting,
        "integrations": sorted({d.integration for d in manager.devices.values() if d.integration}),
        "types": list(FIELD_TYPES),
        "scopes": list(SCOPES),
    }


def _write(fn: Callable[[NotesManager, dict[str, Any]], None]):
    """Run an edit against the notebook; NoteError → an `invalid` error with its message."""

    @callback
    def handler(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
        manager = _manager(hass)
        if manager is None:
            connection.send_error(msg["id"], "not_loaded", "SB Device Notes is not loaded")
            return
        try:
            fn(manager, msg)
        except NoteError as err:
            connection.send_error(msg["id"], "invalid", str(err))
            return
        manager.changed()
        connection.send_result(msg["id"], {})

    return handler


def _device(manager: NotesManager, device_id: str):
    if (device := manager.device(device_id)) is None:
        raise NoteError("That device is not in Home Assistant any more")
    return device


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "sb_device_notes/list"})
@callback
def ws_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    manager = _manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "SB Device Notes is not loaded")
        return
    connection.send_result(msg["id"], _snapshot(manager))


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "sb_device_notes/subscribe"})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    @callback
    def changed() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {}))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_UPDATED, changed)
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "sb_device_notes/set",
        vol.Required("device_id"): str,
        vol.Required("field"): str,
        vol.Optional("value"): vol.Any(str, int, float, bool, None),
    }
)
@callback
def ws_set(hass, connection, msg) -> None:
    def run(m: NotesManager, msg: dict) -> None:
        m.book.set_value(_device(m, msg["device_id"]), m.book.field_ref(msg["field"]), msg.get("value"))

    _write(run)(hass, connection, msg)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "sb_device_notes/add_to_device", vol.Required("device_id"): str, vol.Required("field"): str}
)
@callback
def ws_add_to_device(hass, connection, msg) -> None:
    def run(m: NotesManager, msg: dict) -> None:
        m.book.pick(_device(m, msg["device_id"]), m.book.field_ref(msg["field"]))

    _write(run)(hass, connection, msg)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "sb_device_notes/forget", vol.Required("record_id"): str})
@callback
def ws_forget(hass, connection, msg) -> None:
    _write(lambda m, msg: m.book.forget(msg["record_id"]))(hass, connection, msg)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "sb_device_notes/field_add",
        vol.Required("name"): str,
        vol.Required("field_type"): vol.In(FIELD_TYPES),
        vol.Optional("scope", default="picked"): vol.In(SCOPES),
        vol.Optional("integrations", default=[]): [str],
    }
)
@callback
def ws_field_add(hass, connection, msg) -> None:
    def run(m: NotesManager, msg: dict) -> None:
        m.book.add_field(msg["name"], msg["field_type"], msg["scope"], msg["integrations"])

    _write(run)(hass, connection, msg)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "sb_device_notes/field_update",
        vol.Required("field"): str,
        vol.Optional("name"): str,
        vol.Optional("field_type"): vol.In(FIELD_TYPES),
        vol.Optional("scope"): vol.In(SCOPES),
        vol.Optional("integrations"): [str],
    }
)
@callback
def ws_field_update(hass, connection, msg) -> None:
    def run(m: NotesManager, msg: dict) -> None:
        m.book.update_field(
            m.book.field_ref(msg["field"]),
            name=msg.get("name"),
            ftype=msg.get("field_type"),
            scope=msg.get("scope"),
            integrations=msg.get("integrations"),
        )

    _write(run)(hass, connection, msg)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "sb_device_notes/field_delete", vol.Required("field"): str})
@callback
def ws_field_delete(hass, connection, msg) -> None:
    _write(lambda m, msg: m.book.delete_field(m.book.field_ref(msg["field"])))(hass, connection, msg)


@callback
def async_register(hass: HomeAssistant) -> None:
    for handler in (
        ws_list,
        ws_subscribe,
        ws_set,
        ws_add_to_device,
        ws_forget,
        ws_field_add,
        ws_field_update,
        ws_field_delete,
    ):
        websocket_api.async_register_command(hass, handler)

