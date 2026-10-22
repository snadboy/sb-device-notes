"""Yes/no fields."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceNotesConfigEntry
from .entity import NoteEntity, async_setup_notes_platform
from .model import BOOLEAN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceNotesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_notes_platform(hass, entry, async_add_entities, "switch", {BOOLEAN}, NoteSwitch)


class NoteSwitch(NoteEntity, SwitchEntity):
    _attr_icon = "mdi:checkbox-marked-outline"

    @property
    def is_on(self) -> bool | None:
        return self._value

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)
