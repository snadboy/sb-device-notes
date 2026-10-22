"""Repair flow: a device with no notes, while a removed device of the same model left a
waiting record. Typical after a factory reset of a device that reports no serial number
or MAC: Home Assistant creates a new device and the record can't be matched by itself."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import DOMAIN
from .manager import NotesManager
from .model import NoteError

NEW_DEVICE = "new_device"


class UnmatchedDeviceFlow(RepairsFlow):
    """Pick the waiting record that belongs to this device, or say it's a new device."""

    def __init__(self, manager: NotesManager, device_id: str) -> None:
        self._manager = manager
        self._device_id = device_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        device = self._manager.device(self._device_id)
        if device is None:
            return self.async_abort(reason="device_gone")
        book = self._manager.book
        errors: dict[str, str] = {}

        if user_input is not None:
            choice = user_input["record"]
            try:
                if choice == NEW_DEVICE:
                    book.dismissed.add(device.id)
                else:
                    book.attach(choice, device)
            except (NoteError, KeyError):
                errors["base"] = "attach_failed"
            else:
                self._manager.changed()
                return self.async_create_entry(data={})

        options = [
            SelectOptionDict(
                value=rid,
                label=" · ".join(p for p in (rec["name"], rec["area"], book.summary(rec)) if p),
            )
            for rid, rec in book.candidates(device)
        ]
        options.append(SelectOptionDict(value=NEW_DEVICE, label="None of these: it's a new device"))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("record"): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
            description_placeholders={"device": device.name},
            errors=errors,
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    manager: NotesManager = hass.config_entries.async_loaded_entries(DOMAIN)[0].runtime_data
    return UnmatchedDeviceFlow(manager, (data or {})["device_id"])
