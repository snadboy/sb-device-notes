"""Repair flows.

unmatched_<device_id>: a device with no notes while a same-model device left some, either
deleted (waiting) or still present but unavailable (paired again before the old one was
deleted). Pick the notes; then, if they came from another HA device, offer the restore.

restore_<record_id>: notes moved to a new HA device (picked here, matched by serial or
MAC, or a Matter code entered on it): put the old device's name, area, entity IDs and
entity settings on the new one.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import DOMAIN
from .manager import NotesManager
from .model import NoteError

NEW_DEVICE = "new_device"
_MAX_LINES = 25


def describe_plan(manager: NotesManager, rid: str) -> tuple[str, bool]:
    """Markdown preview of a restore, and whether anything is blocked."""
    rec = manager.book.records[rid]
    ident = rec["identity"]
    device = manager.devices.get(rec["device_id"])
    plan = manager.restore_plan(rid)
    lines = []
    if ident.get("name") and device and device.name != ident["name"]:
        lines.append(f"**Name:** {device.name} → {ident['name']}")
    if ident.get("area") and device and device.area != ident["area"]:
        lines.append(f"**Area:** {device.area or 'none'} → {ident['area']}")
    renames = plan["renames"]
    if renames:
        lines.append(f"**Entity IDs ({len(renames)}):**")
        lines += [f"- `{cur}` → `{target}`" for cur, target, _ in renames[:_MAX_LINES]]
        if len(renames) > _MAX_LINES:
            lines.append(f"- … and {len(renames) - _MAX_LINES} more")
    if plan["keep"]:
        lines.append(f"Already right: {len(plan['keep'])} entity ID(s); their settings are restored too.")
    if plan["blocked"]:
        lines.append(f"**Still in use, can't take yet ({len(plan['blocked'])}):**")
        lines += [f"- `{target}` (held by `{held}`)" for _, target, held in plan["blocked"][:_MAX_LINES]]
        if plan["old_device_id"]:
            lines.append(
                f"The old device is still in Home Assistant: [open it](/config/devices/device/{plan['old_device_id']}), "
                "delete it, then submit again to finish."
            )
    if plan["missing"]:
        lines.append(f"No match on the new device for {len(plan['missing'])} old entity(ies); those are skipped.")
    if not lines:
        lines.append("Nothing to change: the new device already matches.")
    return "\n".join(lines), bool(plan["blocked"])


class NotesRepairFlow(RepairsFlow):
    """Pick a device's notes (unmatched issue), then restore its old identity."""

    def __init__(self, manager: NotesManager, device_id: str | None, record_id: str | None) -> None:
        self._manager = manager
        self._device_id = device_id
        self._rid = record_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self._rid is not None:
            return await self.async_step_restore()
        return await self.async_step_pick()

    async def async_step_pick(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        assert self._device_id is not None
        device = self._manager.device(self._device_id)
        if device is None:
            return self.async_abort(reason="device_gone")
        book = self._manager.book
        unavailable = self._manager.unavailable
        errors: dict[str, str] = {}

        # The repairs manager opens the flow with an empty dict, not None.
        if user_input and "record" in user_input:
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
                if choice != NEW_DEVICE and book.restore_pending(choice):
                    self._rid = choice
                    return await self.async_step_restore()
                return self.async_create_entry(data={})

        options = []
        for rid, rec in book.candidates(device, unavailable):
            where = "unavailable, still in HA" if rec["device_id"] else "removed"
            label = " · ".join(p for p in (rec["name"], rec["area"], book.summary(rec), where) if p)
            options.append(SelectOptionDict(value=rid, label=label))
        options.append(SelectOptionDict(value=NEW_DEVICE, label="None of these: it's a new device"))
        return self.async_show_form(
            step_id="pick",
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

    async def async_step_restore(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        assert self._rid is not None
        book = self._manager.book
        if self._rid not in book.records or not book.restore_pending(self._rid):
            return self.async_abort(reason="nothing_to_restore")
        rec = book.records[self._rid]
        errors: dict[str, str] = {}

        if user_input and "restore" in user_input:
            if not user_input["restore"]:
                self._manager.decline_restore(self._rid)
                return self.async_create_entry(data={})
            plan = self._manager.restore(self._rid)
            if not plan["blocked"]:
                return self.async_create_entry(data={})
            errors["base"] = "blocked"

        preview, _ = describe_plan(self._manager, self._rid)
        device = self._manager.devices.get(rec["device_id"])
        return self.async_show_form(
            step_id="restore",
            data_schema=vol.Schema({vol.Required("restore", default=True): BooleanSelector()}),
            description_placeholders={
                "device": device.name if device else "?",
                "old": rec["identity"].get("name") or "?",
                "plan": preview,
            },
            errors=errors,
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    manager: NotesManager = hass.config_entries.async_loaded_entries(DOMAIN)[0].runtime_data
    data = data or {}
    return NotesRepairFlow(manager, data.get("device_id"), data.get("record_id"))
