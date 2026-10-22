"""Glue between the notebook and Home Assistant: storage, registries, repair issues."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.homeassistant import exposed_entities
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
    label_registry as lr,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    ISSUE_PREFIX,
    RESTORE_PREFIX,
    LEGACY_STORAGE_KEY,
    SIGNAL_UPDATED,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .model import Device, Notebook, assign_keys, new_notebook, norm_serial, plan_restore

_LOGGER = logging.getLogger(__name__)


class NotesManager:
    """Holds the notebook and the current devices; keeps them in step."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.book = Notebook()
        self.devices: dict[str, Device] = {}
        self.unavailable: set[str] = set()
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
            self.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _changed),
            self.hass.bus.async_listen(ar.EVENT_AREA_REGISTRY_UPDATED, _changed),
            self._debouncer.async_shutdown,
        ]

    # ---- devices ---------------------------------------------------------------

    def _read_devices(self) -> dict[str, Device]:
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        found: dict[str, Device] = {}
        for dev in dev_reg.devices:  # iterates entries in HA 2026.10+
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
                area_id=dev.area_id,
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
        changed = self.book.reconcile(list(self.devices.values()))
        for rid, rec in self.book.records.items():
            if (dev := self.devices.get(rec["device_id"])) is not None:
                changed |= self.book.update_identity(rid, dev, self.entity_snapshot(dev.id))
        if changed:
            self._save()
        self._sync_issues()
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)

    # ---- identity snapshot / restore ----------------------------------------------

    def entity_snapshot(self, device_id: str) -> list[dict[str, Any]]:
        """The device's entities as the notebook keeps them (with match keys)."""
        ent_reg = er.async_get(self.hass)
        out = []
        for e in er.async_entries_for_device(ent_reg, device_id, include_disabled_entities=True):
            try:
                settings = exposed_entities.async_get_entity_settings(self.hass, e.entity_id)
            except Exception:  # noqa: BLE001 - exposure is a nice-to-have
                settings = {}
            out.append(
                {
                    "platform": e.platform,
                    "domain": e.domain,
                    "translation_key": e.translation_key,
                    "original_name": e.original_name,
                    "unique_id": e.unique_id,
                    "entity_id": e.entity_id,
                    "name": e.name,
                    "icon": e.icon,
                    "area_id": e.area_id,
                    "hidden_by": e.hidden_by,
                    "disabled_by": e.disabled_by,
                    "labels": sorted(e.labels),
                    "aliases": [None if a is er.COMPUTED_NAME else a for a in e.aliases],
                    "expose": {
                        a: v["should_expose"]
                        for a, v in settings.items()
                        if isinstance(v, dict) and "should_expose" in v
                    },
                }
            )
        return assign_keys(out)

    def unavailable_devices(self) -> set[str]:
        """Devices holding a record whose entities are all unavailable (reset, unplugged)."""
        ent_reg = er.async_get(self.hass)
        out = set()
        for rec in self.book.records.values():
            if not (device_id := rec["device_id"]):
                continue
            states = [
                self.hass.states.get(e.entity_id)
                for e in er.async_entries_for_device(ent_reg, device_id)
                if e.platform != DOMAIN
            ]
            if states and all(s is None or s.state == STATE_UNAVAILABLE for s in states):
                out.add(device_id)
        return out

    def _holder(self, entity_id: str) -> str | None:
        if er.async_get(self.hass).async_get(entity_id) or self.hass.states.get(entity_id):
            return entity_id
        return None

    def restore_plan(self, rid: str) -> dict[str, Any]:
        rec = self.book.records[rid]
        ident = rec["identity"]
        plan = plan_restore(ident["entities"], self.entity_snapshot(rec["device_id"]), self._holder)
        old_device = dr.async_get(self.hass).async_get(ident["device_id"])
        plan["old_device_id"] = old_device.id if old_device else None
        return plan

    @callback
    def restore(self, rid: str) -> dict[str, Any]:
        """Put the old device's name, area and entity settings on the record's new device.
        Settles the identity unless some entity IDs are still held by someone else (the
        old device, usually), so a retry after deleting it finishes the job."""
        rec = self.book.records[rid]
        ident = rec["identity"]
        dev_reg = dr.async_get(self.hass)
        ent_reg = er.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        label_reg = lr.async_get(self.hass)

        device_update: dict[str, Any] = {}
        if ident.get("name"):
            device_update["name_by_user"] = ident["name"]
        if ident.get("area_id") and area_reg.async_get_area(ident["area_id"]):
            device_update["area_id"] = ident["area_id"]
        if device_update:
            dev_reg.async_update_device(rec["device_id"], **device_update)

        plan = self.restore_plan(rid)
        work = [(cur, target, snap) for cur, target, snap in plan["renames"]]
        work += [(cur, cur, snap) for cur, snap in plan["keep"]]
        for cur, target, snap in work:
            update: dict[str, Any] = {
                "name": snap["name"],
                "icon": snap["icon"],
                "labels": {lab for lab in snap["labels"] if label_reg.async_get_label(lab)},
                "aliases": [er.COMPUTED_NAME if a is None else a for a in snap["aliases"]],
            }
            if snap["area_id"] is None or area_reg.async_get_area(snap["area_id"]):
                update["area_id"] = snap["area_id"]
            entry = ent_reg.async_get(cur)
            if entry is not None:
                # Mirror the user's choices only; leave integration defaults alone.
                if snap["hidden_by"] == er.RegistryEntryHider.USER:
                    update["hidden_by"] = er.RegistryEntryHider.USER
                elif entry.hidden_by == er.RegistryEntryHider.USER:
                    update["hidden_by"] = None
                if snap["disabled_by"] == er.RegistryEntryDisabler.USER:
                    update["disabled_by"] = er.RegistryEntryDisabler.USER
                elif snap["disabled_by"] is None and entry.disabled_by is not None:
                    update["disabled_by"] = None
            if target != cur:
                update["new_entity_id"] = target
            try:
                ent_reg.async_update_entity(cur, **update)
            except ValueError as err:
                _LOGGER.warning("Couldn't restore %s as %s: %s", cur, target, err)
                plan["blocked"].append((cur, target, str(err)))
                continue
            for assistant, should in snap["expose"].items():
                try:
                    exposed_entities.async_expose_entity(self.hass, assistant, target, should)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Couldn't restore %s exposure for %s: %s", assistant, target, err)

        if not plan["blocked"]:
            self.book.settle_identity(rid)
        self.changed()
        return plan

    @callback
    def decline_restore(self, rid: str) -> None:
        self.book.settle_identity(rid)
        self.changed()

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
        unavailable = self.unavailable_devices()
        self.unavailable = unavailable
        want = {
            f"{ISSUE_PREFIX}{d.id}": d
            for d in self.book.unmatched(list(self.devices.values()), unavailable)
        }
        restores = {f"{RESTORE_PREFIX}{rid}": rid for rid in self.book.pending_restores()}
        for domain, issue_id in list(issue_reg.issues):
            if domain == DOMAIN and issue_id not in want and issue_id not in restores:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        for issue_id, rid in restores.items():
            rec = self.book.records[rid]
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=True,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="restore_settings" if self.book.same_device_restore(rid) else "restore_identity",
                translation_placeholders={
                    "old": rec["identity"].get("name") or "?",
                    "device": self.devices[rec["device_id"]].name if rec["device_id"] in self.devices else "?",
                },
                data={"record_id": rid},
            )
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
                    "count": str(len(self.book.candidates(dev, unavailable))),
                },
                data={"device_id": dev.id},
            )
