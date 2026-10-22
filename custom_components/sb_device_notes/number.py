"""Number fields."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceNotesConfigEntry
from .entity import NoteEntity, async_setup_notes_platform
from .model import NUMBER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceNotesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_notes_platform(hass, entry, async_add_entities, "number", {NUMBER}, NoteNumber)


class NoteNumber(NoteEntity, NumberEntity):
    _attr_icon = "mdi:numeric"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = -1e9
    _attr_native_max_value = 1e9
    _attr_native_step = 0.01

    @property
    def native_value(self) -> float | None:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        await self._async_set(value)
