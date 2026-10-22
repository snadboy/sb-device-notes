"""Text, link and Matter setup code fields."""

from __future__ import annotations

from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceNotesConfigEntry
from .entity import NoteEntity, async_setup_notes_platform
from .model import LINK, MATTER_CODE, MAX_TEXT, TEXT, display


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceNotesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_setup_notes_platform(
        hass, entry, async_add_entities, "text", {TEXT, LINK, MATTER_CODE}, NoteText
    )


class NoteText(NoteEntity, TextEntity):
    _attr_native_min = 0
    _attr_native_max = MAX_TEXT

    @property
    def icon(self) -> str | None:
        return {MATTER_CODE: "mdi:qrcode", LINK: "mdi:link-variant"}.get(self._ftype, "mdi:note-text-outline")

    @property
    def native_value(self) -> str | None:
        v = self._value
        if v is None:
            return ""
        return display(self._ftype, v)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        v = self._value
        if self._ftype == MATTER_CODE and isinstance(v, str) and v.startswith("MT:"):
            return {"qr": v}
        return None

    async def async_set_value(self, value: str) -> None:
        await self._async_set(value)
