"""SB Device Notes: your own fields on Home Assistant devices (Matter setup code, warranty,
notes…), kept when a device is deleted and re-attached when it comes back."""

from __future__ import annotations

from collections.abc import Callable

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .manager import NotesManager
from .model import FIELD_TYPES, SCOPES, Device, NoteError

PLATFORMS = [Platform.DATE, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH, Platform.TEXT]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type DeviceNotesConfigEntry = ConfigEntry[NotesManager]

_ANY = vol.Any(str, int, float, bool, None)

SET_SCHEMA = vol.Schema(
    {vol.Required("device_id"): cv.string, vol.Required("field"): cv.string, vol.Optional("value"): _ANY}
)
PICK_SCHEMA = vol.Schema({vol.Required("device_id"): cv.string, vol.Required("field"): cv.string})
ADD_WAITING_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("values"): {cv.string: _ANY},
        vol.Optional("area"): cv.string,
        vol.Optional("manufacturer"): cv.string,
        vol.Optional("model"): cv.string,
        vol.Optional("serial"): cv.string,
    }
)
FORGET_SCHEMA = vol.All(
    vol.Schema({vol.Optional("record_id"): cv.string, vol.Optional("device_id"): cv.string}),
    cv.has_at_least_one_key("record_id", "device_id"),
)
ADD_FIELD_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("type"): vol.In(FIELD_TYPES),
        vol.Optional("scope", default="picked"): vol.In(SCOPES),
        vol.Optional("integrations", default=[]): vol.All(cv.ensure_list, [cv.string]),
    }
)
UPDATE_FIELD_SCHEMA = vol.Schema(
    {
        vol.Required("field"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("type"): vol.In(FIELD_TYPES),
        vol.Optional("scope"): vol.In(SCOPES),
        vol.Optional("integrations"): vol.All(cv.ensure_list, [cv.string]),
    }
)
DELETE_FIELD_SCHEMA = vol.Schema({vol.Required("field"): cv.string, vol.Required("confirm"): cv.boolean})


def _manager(hass: HomeAssistant) -> NotesManager:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("SB Device Notes is not set up")
    return entries[0].runtime_data


def _guard(fn: Callable[[NotesManager, ServiceCall], None]) -> Callable[[ServiceCall], None]:
    """Run a service against the manager, turning NoteError into a readable error."""

    @callback
    def handler(call: ServiceCall) -> None:
        manager = _manager(call.hass)
        try:
            fn(manager, call)
        except NoteError as err:
            raise ServiceValidationError(str(err)) from err
        manager.changed()

    return handler


def _device(manager: NotesManager, device_id: str) -> Device:
    if (device := manager.device(device_id)) is None:
        raise NoteError("No such device (service devices can't carry notes)")
    return device


def _set(manager: NotesManager, call: ServiceCall) -> None:
    book = manager.book
    book.set_value(_device(manager, call.data["device_id"]), book.field_ref(call.data["field"]), call.data.get("value"))


def _pick(manager: NotesManager, call: ServiceCall) -> None:
    book = manager.book
    book.pick(_device(manager, call.data["device_id"]), book.field_ref(call.data["field"]))


def _add_waiting(manager: NotesManager, call: ServiceCall) -> None:
    data = dict(call.data)
    manager.book.add_waiting(data.pop("name"), data.pop("values"), **data)


def _forget(manager: NotesManager, call: ServiceCall) -> None:
    book = manager.book
    if rid := call.data.get("record_id"):
        book.forget(rid)
    if device_id := call.data.get("device_id"):
        found = book.for_device(device_id)
        if not found:
            raise NoteError("That device has no notes")
        book.forget(found[0])


def _add_field(manager: NotesManager, call: ServiceCall) -> None:
    d = call.data
    manager.book.add_field(d["name"], d["type"], d["scope"], d["integrations"])


def _update_field(manager: NotesManager, call: ServiceCall) -> None:
    d = call.data
    book = manager.book
    book.update_field(
        book.field_ref(d["field"]),
        name=d.get("name"),
        ftype=d.get("type"),
        scope=d.get("scope"),
        integrations=d.get("integrations"),
    )


def _delete_field(manager: NotesManager, call: ServiceCall) -> None:
    if not call.data["confirm"]:
        raise NoteError("Set confirm: true to delete the field and all its values")
    manager.book.delete_field(manager.book.field_ref(call.data["field"]))


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    for name, fn, schema in (
        ("set", _set, SET_SCHEMA),
        ("add_to_device", _pick, PICK_SCHEMA),
        ("add_waiting", _add_waiting, ADD_WAITING_SCHEMA),
        ("forget", _forget, FORGET_SCHEMA),
        ("add_field", _add_field, ADD_FIELD_SCHEMA),
        ("update_field", _update_field, UPDATE_FIELD_SCHEMA),
        ("delete_field", _delete_field, DELETE_FIELD_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, _guard(fn), schema)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DeviceNotesConfigEntry) -> bool:
    manager = NotesManager(hass)
    await manager.async_load()
    entry.runtime_data = manager
    for unsub in manager.async_listen():
        entry.async_on_unload(unsub)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DeviceNotesConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_flush()
    return unloaded
