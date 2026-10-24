"""Shared base for the per-device field entities, and the add/remove bookkeeping."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_UPDATED, SUMMARY_PREFIX
from .manager import NotesManager
from .model import BadCodeError, NoteError

_SEP = "__"

# HA's device page and entity dialog have no room for our own text; a rejected code's error is
# the one place a person typing a code here sees, so it points at the scanner.
_SCAN_HINT = "Or scan its QR code: open SB Device Notes in the sidebar and tap Scan."


class NoteEntity(Entity):
    """One field on one device. Named after the field, so renaming the field renames it."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager: NotesManager, device_entry: dr.DeviceEntry, fid: str) -> None:
        self._manager = manager
        self._device_id = device_entry.id
        self._fid = fid
        self._attr_unique_id = f"{device_entry.id}{_SEP}{fid}"
        # Link to the device without claiming it, so deleting the device still works.
        self.device_entry = device_entry

    @property
    def name(self) -> str | None:
        field = self._manager.book.fields.get(self._fid)
        return field["name"] if field else None

    @property
    def _ftype(self) -> str:
        return self._manager.book.fields[self._fid]["type"]

    @property
    def _value(self) -> Any:
        return self._manager.book.value(self._device_id, self._fid)

    async def _async_set(self, raw: Any) -> None:
        device = self._manager.device(self._device_id)
        if device is None:
            raise ServiceValidationError("This device is no longer in Home Assistant")
        try:
            self._manager.book.set_value(device, self._fid, raw)
        except NoteError as err:
            msg = str(err)
            if isinstance(err, BadCodeError):
                msg = f"{msg.rstrip('.')}. {_SCAN_HINT}"
            raise ServiceValidationError(msg) from err
        self._manager.changed()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATED, self.async_write_ha_state)
        )


def async_setup_notes_platform(
    hass: HomeAssistant,
    entry: ConfigEntry[NotesManager],
    async_add_entities: AddConfigEntryEntitiesCallback,
    platform: str,
    types: set[str],
    factory: Callable[[NotesManager, dr.DeviceEntry, str], Entity],
) -> None:
    """Keep one entity per (device, field) showing, for fields of `types`."""
    manager = entry.runtime_data
    known: set[tuple[str, str]] = set()

    @callback
    def _sync() -> None:
        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)
        want = manager.visible_pairs(types)
        new = []
        for key in want - known:
            if device_entry := dev_reg.async_get(key[0]):
                known.add(key)
                new.append(factory(manager, device_entry, key[1]))
        if new:
            async_add_entities(new)
        for reg in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            if reg.domain != platform or reg.unique_id.startswith(SUMMARY_PREFIX) or _SEP not in reg.unique_id:
                continue
            device_id, fid = reg.unique_id.split(_SEP, 1)
            if (device_id, fid) not in want:
                known.discard((device_id, fid))
                ent_reg.async_remove(reg.entity_id)

    _sync()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_UPDATED, _sync))
