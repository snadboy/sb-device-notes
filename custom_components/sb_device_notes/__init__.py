"""SB Device Notes: your own fields on Home Assistant devices (Matter setup code, warranty,
notes…), kept when a device is deleted and re-attached when it comes back."""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from . import websocket
from .const import DOMAIN, ENTRY_TITLE, OLD_ENTRY_TITLE, PANEL_URL, STATIC_URL
from .manager import NotesManager
from .model import FIELD_TYPES, SCOPES, Device, NoteError

_LOGGER = logging.getLogger(__name__)
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
RESTORE_SCHEMA = vol.Schema({vol.Required("device_id"): cv.string})
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


def _restore(manager: NotesManager, call: ServiceCall) -> None:
    found = manager.book.for_device(call.data["device_id"])
    if not found or not manager.book.restore_pending(found[0]):
        raise NoteError("Nothing to restore on that device")
    plan = manager.restore(found[0])
    if plan["blocked"]:
        held = ", ".join(target for _, target, _ in plan["blocked"])
        raise NoteError(
            f"Restored what was free; still in use: {held}. Delete the old device and run this again."
        )


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
        ("restore", _restore, RESTORE_SCHEMA),
        ("add_field", _add_field, ADD_FIELD_SCHEMA),
        ("update_field", _update_field, UPDATE_FIELD_SCHEMA),
        ("delete_field", _delete_field, DELETE_FIELD_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, _guard(fn), schema)
    websocket.async_register(hass)
    await _async_register_panel(hass)
    return True


async def _async_register_panel(hass: HomeAssistant) -> None:
    """The sidebar page. The notes work without it, so a failure here is only logged."""
    try:
        integration = await async_get_integration(hass, DOMAIN)
        version = str(integration.version or "0")
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "frontend"), False)]
        )
        if PANEL_URL not in hass.data.get("frontend_panels", {}):
            await panel_custom.async_register_panel(
                hass,
                frontend_url_path=PANEL_URL,
                webcomponent_name="sb-device-notes-panel",
                sidebar_title="SB Device Notes",
                sidebar_icon="mdi:note-text-outline",
                module_url=f"{STATIC_URL}/sb-device-notes.js?v={version}",
                embed_iframe=False,
                require_admin=True,
                # the ⚙ on the integration page opens this page
                config_panel_domain=DOMAIN,
            )
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Could not register the Device Notes sidebar page")


async def async_setup_entry(hass: HomeAssistant, entry: DeviceNotesConfigEntry) -> bool:
    if entry.title == OLD_ENTRY_TITLE:  # the old default; a title the user chose stays
        hass.config_entries.async_update_entry(entry, title=ENTRY_TITLE)
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
