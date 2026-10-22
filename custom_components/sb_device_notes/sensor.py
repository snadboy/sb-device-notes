"""Long-text fields (read-only on the device page; edit with device_notes.set), and one
summary sensor per field listing every device's value for dashboards."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceNotesConfigEntry
from .const import DOMAIN, SIGNAL_UPDATED, SUMMARY_PREFIX
from .entity import NoteEntity, async_setup_notes_platform
from .manager import NotesManager
from .model import LONG_TEXT, MAX_TEXT, MISSING, WAITING


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceNotesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_notes_platform(hass, entry, async_add_entities, "sensor", {LONG_TEXT}, NoteLongText)

    manager = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_summaries() -> None:
        new = [FieldSummary(entry, fid) for fid in manager.book.fields.keys() - known]
        known.update(manager.book.fields)
        if new:
            async_add_entities(new)
        ent_reg = er.async_get(hass)
        for reg in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            if reg.domain == "sensor" and reg.unique_id.startswith(SUMMARY_PREFIX):
                fid = reg.unique_id.removeprefix(SUMMARY_PREFIX)
                if fid not in manager.book.fields:
                    known.discard(fid)
                    ent_reg.async_remove(reg.entity_id)

    _sync_summaries()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_UPDATED, _sync_summaries))


class NoteLongText(NoteEntity, SensorEntity):
    """The first 255 characters as the state; the whole text in the `text` attribute."""

    _attr_icon = "mdi:text-long"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset({"text"})

    @property
    def native_value(self) -> str | None:
        v = self._value
        if v is None:
            return None
        return v if len(v) <= MAX_TEXT else v[: MAX_TEXT - 1] + "…"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        v = self._value
        return {"text": v} if v is not None and len(v) > MAX_TEXT else None


class FieldSummary(SensorEntity):
    """State: how many devices have a value. `rows`: every value, for a dashboard card."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:format-list-text"
    _unrecorded_attributes = frozenset({"rows"})

    def __init__(self, entry: DeviceNotesConfigEntry, fid: str) -> None:
        self._manager: NotesManager = entry.runtime_data
        self._fid = fid
        self._attr_unique_id = f"{SUMMARY_PREFIX}{fid}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="SB Device Notes",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        return self._fid in self._manager.book.fields

    @property
    def name(self) -> str | None:
        field = self._manager.book.fields.get(self._fid)
        return field["name"] if field else None

    @property
    def native_value(self) -> int | None:
        return self._manager.book.field_usage(self._fid) if self.available else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.available:
            return None
        rows = self._manager.book.rows(self._fid, list(self._manager.devices.values()))
        return {
            "field_id": self._fid,
            "type": self._manager.book.fields[self._fid]["type"],
            "waiting": sum(r["status"] == WAITING for r in rows),
            "missing": sum(r["status"] == MISSING for r in rows),
            "rows": rows,
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATED, self.async_write_ha_state)
        )
