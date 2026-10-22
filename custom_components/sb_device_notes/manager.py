"""Glue between the notebook and Home Assistant: storage, registries, repair issues."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    issue_registry as ir,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    ISSUE_PREFIX,
    LEGACY_STORAGE_KEY,
    SIGNAL_UPDATED,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .model import Device, Notebook, new_notebook, norm_serial

_LOGGER = logging.getLogger(__name__)


class NotesManager:
    """Holds the notebook and the current devices; keeps them in step."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.book = Notebook()
        self.devices: dict[str, Device] = {}
        self._debouncer = Debouncer(hass, _LOGGER, cooldown=1, immediate=False, function=self.refresh)

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data is None:
            legacy = await Store(self.hass, 1, LEGACY_STORAGE_KEY).async_load()
            self.book = new_notebook(legacy)
            if legacy:
                _LOGGER.info("Imported %d Matter Codes records", len(self.book.records))
            await self._store.async_save(self.book.to_store())
        else:
            self.book = Notebook(data["fields"], data["records"], data.get("dismissed", ()))
        self.refresh()

    @callback
    def async_listen(self) -> list:
        """Registry listeners; returns their unsubscribe callbacks."""

        @callback
        def _changed(_event: Event) -> None:
            self._debouncer.async_schedule_call()

        return [
            self.hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _changed),
            self.hass.bus.async_listen(ar.EVENT_AREA_REGISTRY_UPDATED, _changed),
            self._debouncer.async_shutdown,
        ]

    # ---- devices ---------------------------------------------------------------

    def _read_devices(self) -> dict[str, Device]:
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        found: dict[str, Device] = {}
        for dev in dev_reg.devices.values():
            if dev.entry_type is dr.DeviceEntryType.SERVICE:
                continue
            entry = self.hass.config_entries.async_get_entry(dev.config_entry_id)
            if entry is None or entry.domain == DOMAIN:
                continue
            area = area_reg.async_get_area(dev.area_id) if dev.area_id else None
            found[dev.id] = Device(
                id=dev.id,
                name=dev.name_by_user or dev.name or dev.id,
                area=area.name if area else None,
                manufacturer=dev.manufacturer,
                model=dev.model,
                serial=norm_serial(dev.serial_number),
                connections=frozenset(dev.connections),
                integration=entry.domain,
            )
        return found

    def device(self, device_id: str) -> Device | None:
        """A current device, or None. Re-reads the registry for one added moments ago
        that the debounced refresh hasn't picked up yet."""
        if device_id not in self.devices:
            self.devices = self._read_devices()
        return self.devices.get(device_id)

    def visible_pairs(self, types: set[str]) -> set[tuple[str, str]]:
        """(device_id, field_id) for every field of these types showing on a device."""
        fields = self.book.fields
        return {
            (dev.id, fid)
            for dev in self.devices.values()
            for fid in self.book.visible(dev)
            if fields[fid]["type"] in types
        }

    # ---- refresh / save --------------------------------------------------------

    @callback
    def refresh(self) -> None:
        self.devices = self._read_devices()
        if self.book.reconcile(list(self.devices.values())):
            self._save()
        self._sync_issues()
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)

    @callback
    def changed(self) -> None:
        """Call after editing the notebook."""
        self._save()
        self.refresh()

    def _save(self) -> None:
        self._store.async_delay_save(self.book.to_store, 1)

    async def async_flush(self) -> None:
        await self._store.async_save(self.book.to_store())

    # ---- repair issues -----------------------------------------------------------

    def _sync_issues(self) -> None:
        issue_reg = ir.async_get(self.hass)
        want = {f"{ISSUE_PREFIX}{d.id}": d for d in self.book.unmatched(list(self.devices.values()))}
        for domain, issue_id in list(issue_reg.issues):
            if domain == DOMAIN and issue_id not in want:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        for issue_id, dev in want.items():
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=True,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="unmatched_device",
                translation_placeholders={
                    "device": dev.name,
                    "model": " ".join(p for p in (dev.manufacturer, dev.model) if p) or "?",
                    "count": str(len(self.book.candidates(dev))),
                },
                data={"device_id": dev.id},
            )
