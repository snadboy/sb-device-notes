"""Date fields (warranty end, purchase date…)."""

from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceNotesConfigEntry
from .entity import NoteEntity, async_setup_notes_platform
from .model import DATE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceNotesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_notes_platform(hass, entry, async_add_entities, "date", {DATE}, NoteDate)


class NoteDate(NoteEntity, DateEntity):
    _attr_icon = "mdi:calendar-check"

    @property
    def native_value(self) -> date | None:
        v = self._value
        return date.fromisoformat(v) if v else None

    async def async_set_value(self, value: date) -> None:
        await self._async_set(value)
