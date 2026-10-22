"""The notebook: user-defined fields, and per-device records holding their values.

Pure Python, no Home Assistant imports, so it tests offline.

A record belongs to one physical device. It is attached to the HA device it currently
is (device_id), or waiting (device_id None) after that HA device was deleted, typically
for a factory reset, until the device shows up again. Records keep a copy of the
device's last name, area, maker, model, serial and connections (MAC, Zigbee address…)
so a waiting record can still be told apart and matched.

Matching a waiting record to a device, strongest first:
1. the record's device_id still exists;
2. its serial number or a connection matches exactly one current device;
3. the same Matter setup code is entered on a device (that code identifies the physical
   device, so the whole record moves there).
Devices with neither (Govee, Shelly) get a repair issue offering same-model records.

A field shows on a device when the device is in the field's scope, or the device has a
value for it, or the user added it to that device ("picked").
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
import re
from typing import Any
import uuid

from .codes import CodeError, format_manual, parse as parse_code

TEXT = "text"
LONG_TEXT = "long_text"
DATE = "date"
NUMBER = "number"
BOOLEAN = "boolean"
LINK = "link"
MATTER_CODE = "matter_code"
FIELD_TYPES = (TEXT, LONG_TEXT, DATE, NUMBER, BOOLEAN, LINK, MATTER_CODE)
# Types whose stored values are all strings that each other type accepts as-is.
_STRING_TYPES = {TEXT, LONG_TEXT, LINK}

SCOPE_ALL = "all"
SCOPE_INTEGRATIONS = "integrations"
SCOPE_PICKED = "picked"
SCOPES = (SCOPE_ALL, SCOPE_INTEGRATIONS, SCOPE_PICKED)

ATTACHED = "attached"
WAITING = "waiting"
MISSING = "missing"

MAX_TEXT = 255  # an HA entity state
MAX_LONG_TEXT = 10000

_JUNK_SERIALS = {"NONE", "UNKNOWN", "TEST_SN", "N/A", "NA", "SERIAL", "SN"}
_TRUE = {"true", "on", "yes", "1"}
_FALSE = {"false", "off", "no", "0"}


class NoteError(ValueError):
    """A value or edit the notebook refuses; the message says why."""


def norm_serial(serial: str | None) -> str | None:
    """Upper-cased serial, or None for blanks and placeholders vendors ship."""
    if serial is None:
        return None
    s = serial.strip().upper()
    if not s or s in _JUNK_SERIALS or set(s) <= {"0", "F", "-"}:
        return None
    return s


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "field"


@dataclass(frozen=True)
class Device:
    """What the notebook needs to know about one HA device."""

    id: str
    name: str
    area: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    connections: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    integration: str | None = None
    area_id: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---- values ----------------------------------------------------------------------


def coerce(ftype: str, raw: Any) -> Any:
    """Validate a value for a field type and return what is stored; None clears."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if ftype in (TEXT, LONG_TEXT, LINK):
        s = str(raw).strip()
        limit = MAX_LONG_TEXT if ftype == LONG_TEXT else MAX_TEXT
        if len(s) > limit:
            raise NoteError(f"Too long: {len(s)} characters, the limit is {limit}")
        if ftype == LINK and not re.match(r"https?://\S+$", s):
            raise NoteError("A link starts with http:// or https:// and has no spaces")
        return s
    if ftype == DATE:
        if isinstance(raw, date):
            return raw.isoformat()
        try:
            return date.fromisoformat(str(raw).strip()).isoformat()
        except ValueError:
            raise NoteError("A date is written YYYY-MM-DD") from None
    if ftype == NUMBER:
        if isinstance(raw, bool):
            raise NoteError("Not a number")
        try:
            n = float(raw)
        except (TypeError, ValueError):
            raise NoteError("Not a number") from None
        return int(n) if n.is_integer() else n
    if ftype == BOOLEAN:
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        raise NoteError("Use yes or no")
    if ftype == MATTER_CODE:
        try:
            code = parse_code(str(raw))
        except CodeError as err:
            raise NoteError(str(err)) from None
        return code.qr or code.manual
    raise NoteError(f"Unknown field type {ftype}")


def display(ftype: str, value: Any) -> str | None:
    """How a stored value reads in a list."""
    if value is None:
        return None
    if ftype == MATTER_CODE:
        return format_manual(parse_code(value).manual)
    if ftype == BOOLEAN:
        return "Yes" if value else "No"
    return str(value)


def code_identity(value: str) -> str:
    """The manual code a stored Matter value stands for (QR and manual forms compare equal)."""
    return parse_code(value).manual



# ---- identity: what a device was called, so a re-paired one can be restored ---------
#
# A record's "identity" is a snapshot of the HA device it belongs to: device name and
# area, and for each entity its entity ID and the user's settings. It follows the device
# while the record stays on it. When the record moves to a different HA device (a
# re-pair), the identity stays put: that's the "restore pending" state, until the user
# restores it onto the new device or declines.
#
# Entities are matched across devices by key: platform, domain, translation key and
# original name, plus an index among entities sharing those (ordered by unique_id).
# Unique IDs themselves change on re-pairing, so they can't be the key.


def assign_keys(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add "key" to each entry dict (platform, domain, translation_key, original_name, unique_id)."""
    seen: Counter[str] = Counter()
    out = []
    for e in sorted(entries, key=lambda e: str(e.get("unique_id"))):
        base = "|".join(
            str(e.get(k) or "") for k in ("platform", "domain", "translation_key", "original_name")
        )
        out.append({**e, "key": f"{base}|{seen[base]}"})
        seen[base] += 1
    return out


def merge_entities(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """New snapshot entries replace old ones with the same key; old ones not seen now are
    kept (an entity removed moments before its device must not drop out of the snapshot)."""
    merged = {e["key"]: e for e in old}
    merged.update({e["key"]: e for e in new})
    return sorted(merged.values(), key=lambda e: e["key"])


def plan_restore(
    snapshot: list[dict[str, Any]],
    current: list[dict[str, Any]],
    holder: Any,
) -> dict[str, list]:
    """Match a snapshot onto a device's current entities.

    `current`: dicts with key and entity_id. `holder(entity_id)`: who else holds an
    entity ID (an entity ID string) or None if it's free.
    Returns renames [(current_id, target_id, snap)], keep [(current_id, snap)] (already
    right), blocked [(current_id, target_id, held_by)], missing [snap] (no such entity now).
    """
    by_key = {e["key"]: e for e in current}
    plan: dict[str, list] = {"renames": [], "keep": [], "blocked": [], "missing": []}
    for snap in snapshot:
        cur = by_key.get(snap["key"])
        if cur is None:
            plan["missing"].append(snap)
        elif cur["entity_id"] == snap["entity_id"]:
            plan["keep"].append((cur["entity_id"], snap))
        elif (held := holder(snap["entity_id"])) and held != cur["entity_id"]:
            plan["blocked"].append((cur["entity_id"], snap["entity_id"], held))
        else:
            plan["renames"].append((cur["entity_id"], snap["entity_id"], snap))
    return plan


# ---- the notebook ------------------------------------------------------------------


class Notebook:
    """Fields and records."""

    def __init__(
        self,
        fields: dict[str, dict[str, Any]] | None = None,
        records: dict[str, dict[str, Any]] | None = None,
        dismissed: Iterable[str] = (),
    ) -> None:
        self.fields: dict[str, dict[str, Any]] = fields or {}
        self.records: dict[str, dict[str, Any]] = records or {}
        # Devices the user said have none of the waiting records (repair flow "new device").
        self.dismissed: set[str] = set(dismissed)

    def to_store(self) -> dict[str, Any]:
        return {"fields": self.fields, "records": self.records, "dismissed": sorted(self.dismissed)}

    # ---- fields ----------------------------------------------------------------

    def field_ref(self, ref: str) -> str:
        """A field id from an id or a name (case-insensitive)."""
        if ref in self.fields:
            return ref
        for fid, f in self.fields.items():
            if f["name"].lower() == ref.strip().lower():
                return fid
        raise NoteError(f"No field called {ref!r}")

    def _check_name(self, name: str, skip: str | None = None) -> str:
        name = name.strip()
        if not name:
            raise NoteError("A field needs a name")
        for fid, f in self.fields.items():
            if fid != skip and f["name"].lower() == name.lower():
                raise NoteError(f"There is already a field called {f['name']}")
        return name

    @staticmethod
    def _check_scope(scope: str, integrations: Iterable[str]) -> list[str]:
        if scope not in SCOPES:
            raise NoteError(f"Scope is one of {', '.join(SCOPES)}")
        domains = sorted(set(integrations))
        if scope == SCOPE_INTEGRATIONS and not domains:
            raise NoteError("Pick at least one integration for this scope")
        return domains if scope == SCOPE_INTEGRATIONS else []

    def add_field(
        self,
        name: str,
        ftype: str,
        scope: str = SCOPE_PICKED,
        integrations: Iterable[str] = (),
        fid: str | None = None,
    ) -> str:
        name = self._check_name(name)
        if ftype not in FIELD_TYPES:
            raise NoteError(f"Type is one of {', '.join(FIELD_TYPES)}")
        domains = self._check_scope(scope, integrations)
        base = fid or slugify(name)
        fid, n = base, 2
        while fid in self.fields:
            fid, n = f"{base}_{n}", n + 1
        self.fields[fid] = {
            "name": name,
            "type": ftype,
            "scope": scope,
            "integrations": domains,
            "created": _now(),
        }
        return fid

    def update_field(
        self,
        fid: str,
        *,
        name: str | None = None,
        ftype: str | None = None,
        scope: str | None = None,
        integrations: Iterable[str] | None = None,
    ) -> None:
        f = self.fields[fid]
        if name is not None:
            f["name"] = self._check_name(name, skip=fid)
        if ftype is not None and ftype != f["type"]:
            if not {ftype, f["type"]} <= _STRING_TYPES:
                raise NoteError(
                    f"Can't change {f['type']} to {ftype}: only text, long text and link convert"
                )
            for rec in self.records.values():
                if fid in rec["values"]:
                    try:
                        coerce(ftype, rec["values"][fid])
                    except NoteError as err:
                        raise NoteError(f"{rec['name']}'s value doesn't fit: {err}") from None
            f["type"] = ftype
        if scope is not None or integrations is not None:
            new_scope = scope or f["scope"]
            f["integrations"] = self._check_scope(
                new_scope, f["integrations"] if integrations is None else integrations
            )
            f["scope"] = new_scope

    def field_usage(self, fid: str) -> int:
        """How many records hold a value for the field."""
        return sum(fid in r["values"] for r in self.records.values())

    def delete_field(self, fid: str) -> int:
        del self.fields[fid]
        n = 0
        for rec in self.records.values():
            n += rec["values"].pop(fid, None) is not None
            if fid in rec["picked"]:
                rec["picked"].remove(fid)
        self._prune()
        return n

    def in_scope(self, fid: str, device: Device) -> bool:
        f = self.fields[fid]
        if f["scope"] == SCOPE_ALL:
            return True
        if f["scope"] == SCOPE_INTEGRATIONS:
            return device.integration in f["integrations"]
        return False

    def visible(self, device: Device) -> list[str]:
        """Fields that show on this device, in field order."""
        found = self.for_device(device.id)
        rec = found[1] if found else None
        return [
            fid
            for fid in self.fields
            if self.in_scope(fid, device) or (rec and (fid in rec["values"] or fid in rec["picked"]))
        ]

    # ---- records -----------------------------------------------------------------

    def for_device(self, device_id: str) -> tuple[str, dict[str, Any]] | None:
        for rid, rec in self.records.items():
            if rec["device_id"] == device_id:
                return rid, rec
        return None

    def value(self, device_id: str, fid: str) -> Any:
        found = self.for_device(device_id)
        return found[1]["values"].get(fid) if found else None

    def waiting(self) -> list[tuple[str, dict[str, Any]]]:
        return [(rid, r) for rid, r in self.records.items() if r["device_id"] is None]

    def _new_record(self) -> tuple[str, dict[str, Any]]:
        rid = uuid.uuid4().hex
        rec: dict[str, Any] = {
            "device_id": None,
            "name": None,
            "area": None,
            "manufacturer": None,
            "model": None,
            "serial": None,
            "connections": [],
            "values": {},
            "picked": [],
            "identity": None,
            "updated": _now(),
        }
        self.records[rid] = rec
        return rid, rec

    def _record_for(self, device: Device) -> tuple[str, dict[str, Any]]:
        if found := self.for_device(device.id):
            return found
        rid, rec = self._new_record()
        rec["device_id"] = device.id
        self._snapshot(rec, device)
        self.dismissed.discard(device.id)
        return rid, rec

    @staticmethod
    def _snapshot(rec: dict[str, Any], dev: Device) -> bool:
        new = {
            "name": dev.name,
            "area": dev.area,
            "manufacturer": dev.manufacturer,
            "model": dev.model,
            "serial": dev.serial or rec.get("serial"),
            "connections": sorted(list(c) for c in dev.connections) or rec.get("connections", []),
        }
        if all(rec.get(k) == v for k, v in new.items()):
            return False
        rec.update(new)
        return True

    def _prune(self) -> None:
        for rid in [r for r, rec in self.records.items() if not rec["values"] and not rec["picked"]]:
            del self.records[rid]

    def _find_code(self, manual: str, skip: str | None) -> str | None:
        """The record (other than `skip`) holding this Matter code in any code field."""
        code_fields = [fid for fid, f in self.fields.items() if f["type"] == MATTER_CODE]
        for rid, rec in self.records.items():
            if rid == skip:
                continue
            for fid in code_fields:
                if (v := rec["values"].get(fid)) is not None and code_identity(v) == manual:
                    return rid
        return None

    def _merge_into(self, target: str, source: str) -> None:
        """Fold record `source` into `target`; target's values win."""
        src, dst = self.records.pop(source), self.records[target]
        for fid, v in src["values"].items():
            dst["values"].setdefault(fid, v)
        dst["picked"] = sorted(set(dst["picked"]) | set(src["picked"]))

    def set_value(self, device: Device, fid: str, raw: Any) -> None:
        """Set (or with an empty value, clear) a field on a device."""
        f = self.fields.get(fid)
        if f is None:
            raise NoteError(f"No field {fid!r}")
        value = coerce(f["type"], raw)
        mine = self.for_device(device.id)

        if value is not None and f["type"] == MATTER_CODE:
            other = self._find_code(code_identity(value), skip=mine[0] if mine else None)
            if other:
                # This physical device's record exists already: it moves here.
                if mine:
                    self._merge_into(other, mine[0])
                rec = self.records[other]
                rec["device_id"] = device.id
                self._snapshot(rec, device)
                self.dismissed.discard(device.id)
                mine = (other, rec)

        if value is None:
            if mine:
                mine[1]["values"].pop(fid, None)
                if f["scope"] == SCOPE_PICKED and fid in mine[1]["picked"]:
                    mine[1]["picked"].remove(fid)
                mine[1]["updated"] = _now()
                self._prune()
            return
        rid, rec = mine or self._record_for(device)
        rec["values"][fid] = value
        rec["updated"] = _now()

    def pick(self, device: Device, fid: str) -> None:
        """Add a field to a device (so it shows even without a value)."""
        if fid not in self.fields:
            raise NoteError(f"No field {fid!r}")
        _, rec = self._record_for(device)
        if fid not in rec["picked"]:
            rec["picked"].append(fid)
            rec["updated"] = _now()

    def add_waiting(
        self,
        name: str,
        values: dict[str, Any],
        *,
        area: str | None = None,
        manufacturer: str | None = None,
        model: str | None = None,
        serial: str | None = None,
    ) -> str:
        """A record for a device that isn't in Home Assistant right now."""
        if not values:
            raise NoteError("Give at least one value")
        coerced = {}
        for ref, raw in values.items():
            fid = self.field_ref(ref)
            v = coerce(self.fields[fid]["type"], raw)
            if v is None:
                continue
            if self.fields[fid]["type"] == MATTER_CODE and (
                other := self._find_code(code_identity(v), skip=None)
            ):
                raise NoteError(f"{display(MATTER_CODE, v)} is already stored for {self.records[other]['name']}")
            coerced[fid] = v
        rid, rec = self._new_record()
        rec.update(
            name=name,
            area=area,
            manufacturer=manufacturer,
            model=model,
            serial=norm_serial(serial),
            values=coerced,
        )
        return rid

    def forget(self, rid: str) -> None:
        if rid not in self.records:
            raise NoteError("No such record")
        del self.records[rid]

    def attach(self, rid: str, device: Device) -> None:
        """Attach a record to a device (repair flow); it may come off an unavailable old device."""
        rec = self.records[rid]
        if mine := self.for_device(device.id):
            if mine[0] == rid:
                return
            self._merge_into(rid, mine[0])
        rec["device_id"] = device.id
        rec["updated"] = _now()
        self._snapshot(rec, device)
        self.dismissed.discard(device.id)

    # ---- matching -------------------------------------------------------------------

    def reconcile(self, devices: list[Device]) -> bool:
        """Attach and detach records to match the current devices. True if anything changed."""
        changed = False
        by_id = {d.id: d for d in devices}
        serials = Counter(d.serial for d in devices if d.serial)
        by_serial = {d.serial: d for d in devices if d.serial and serials[d.serial] == 1}
        conns = Counter(c for d in devices for c in d.connections)
        by_conn = {c: d for d in devices for c in d.connections if conns[c] == 1}
        claimed: set[str] = set()

        for rec in self.records.values():
            dev = by_id.get(rec["device_id"]) if rec["device_id"] else None
            if dev and dev.id not in claimed:
                claimed.add(dev.id)
                changed |= self._snapshot(rec, dev)
            elif rec["device_id"] is not None:
                rec["device_id"] = None
                rec["updated"] = _now()
                changed = True

        for rec in self.records.values():
            if rec["device_id"] is not None:
                continue
            dev = by_serial.get(rec["serial"]) if rec.get("serial") else None
            if dev is None:
                dev = next(
                    (by_conn[c] for c in map(tuple, rec.get("connections", [])) if c in by_conn), None
                )
            if dev and dev.id not in claimed:
                claimed.add(dev.id)
                rec["device_id"] = dev.id
                rec["updated"] = _now()
                self._snapshot(rec, dev)
                changed = True

        gone = self.dismissed - (by_id.keys() - claimed)
        if gone:
            self.dismissed -= gone
            changed = True
        return changed

    def candidates(
        self, device: Device, unavailable: frozenset[str] | set[str] = frozenset()
    ) -> list[tuple[str, dict[str, Any]]]:
        """Records that could belong to `device`: same maker and model, and either waiting
        or still on an old device that is unavailable (paired again before the old one was
        deleted). A device reporting neither maker nor model matches nothing."""
        if not (device.manufacturer and device.model):
            return []
        return [
            (rid, r)
            for rid, r in self.records.items()
            if (r["device_id"] is None or (r["device_id"] in unavailable and r["device_id"] != device.id))
            and r.get("manufacturer") == device.manufacturer
            and r.get("model") == device.model
        ]

    def unmatched(
        self, devices: list[Device], unavailable: frozenset[str] | set[str] = frozenset()
    ) -> list[Device]:
        """Devices with no record where another device's record might be theirs."""
        return [
            d
            for d in devices
            if d.id not in self.dismissed
            and d.id not in unavailable
            and self.for_device(d.id) is None
            and self.candidates(d, unavailable)
        ]

    # ---- identity ---------------------------------------------------------------------

    def restore_pending(self, rid: str) -> bool:
        """The record moved to a new HA device and its old identity hasn't been applied."""
        rec = self.records[rid]
        ident = rec.get("identity")
        return bool(
            rec["device_id"] and ident and ident.get("device_id") and ident["device_id"] != rec["device_id"]
        )

    def pending_restores(self) -> list[str]:
        return [rid for rid in self.records if self.restore_pending(rid)]

    def update_identity(
        self, rid: str, device: Device, entities: list[dict[str, Any]]
    ) -> bool:
        """Refresh a record's identity from its current device, unless a restore is
        pending (then the identity describes the old device and must stay)."""
        rec = self.records[rid]
        if rec["device_id"] != device.id or self.restore_pending(rid):
            return False
        old = rec.get("identity") or {}
        new = {
            "device_id": device.id,
            "name": device.name,
            "area_id": device.area_id,
            "area": device.area,
            "entities": merge_entities(old.get("entities", []) if old.get("device_id") == device.id else [], entities),
        }
        if new == old:
            return False
        rec["identity"] = new
        return True

    def settle_identity(self, rid: str) -> None:
        """Restored or declined: the identity now follows the record's current device."""
        rec = self.records[rid]
        if rec.get("identity"):
            rec["identity"]["device_id"] = rec["device_id"]
            rec["identity"]["entities"] = []

    def summary(self, rec: dict[str, Any]) -> str:
        """One line naming a record's values, for pick lists."""
        parts = []
        for fid, f in self.fields.items():
            if (v := rec["values"].get(fid)) is not None:
                parts.append(display(f["type"], v) if f["type"] == MATTER_CODE else f"{f['name']}: {display(f['type'], v)}")
        return " · ".join(parts)

    # ---- lists --------------------------------------------------------------------------

    def rows(self, fid: str, devices: list[Device]) -> list[dict[str, Any]]:
        """One field across devices: waiting values, devices showing the field with no
        value, then set values; each by area and name."""
        ftype = self.fields[fid]["type"]
        out: list[dict[str, Any]] = []
        for rid, rec in self.records.items():
            if (v := rec["values"].get(fid)) is not None:
                out.append(
                    {
                        "status": ATTACHED if rec["device_id"] else WAITING,
                        "name": rec["name"],
                        "area": rec["area"],
                        "manufacturer": rec["manufacturer"],
                        "model": rec["model"],
                        "value": display(ftype, v),
                        "device_id": rec["device_id"],
                        "record_id": rid,
                    }
                )
        for dev in devices:
            if fid in self.visible(dev) and self.value(dev.id, fid) is None:
                out.append(
                    {
                        "status": MISSING,
                        "name": dev.name,
                        "area": dev.area,
                        "manufacturer": dev.manufacturer,
                        "model": dev.model,
                        "value": None,
                        "device_id": dev.id,
                        "record_id": None,
                    }
                )
        order = {WAITING: 0, MISSING: 1, ATTACHED: 2}
        out.sort(key=lambda r: (order[r["status"]], r["area"] or "~", (r["name"] or "").lower()))
        return out


# ---- first run --------------------------------------------------------------------------

DEFAULT_FIELDS = (
    # (id, name, type, scope, integrations)
    ("matter_setup_code", "Matter setup code", MATTER_CODE, SCOPE_INTEGRATIONS, ("matter",)),
    ("notes", "Notes", TEXT, SCOPE_PICKED, ()),
    ("warranty_until", "Warranty until", DATE, SCOPE_PICKED, ()),
    ("purchased", "Purchased", DATE, SCOPE_PICKED, ()),
    ("where_bought", "Where bought", TEXT, SCOPE_PICKED, ()),
    ("manual", "Manual", LINK, SCOPE_PICKED, ()),
)


def new_notebook(legacy: dict[str, Any] | None = None) -> Notebook:
    """A first-run notebook with the default fields, importing Matter Codes 0.1 data."""
    nb = Notebook()
    for fid, name, ftype, scope, domains in DEFAULT_FIELDS:
        nb.add_field(name, ftype, scope, domains, fid=fid)
    if legacy:
        for rid, old in (legacy.get("records") or {}).items():
            values: dict[str, Any] = {"matter_setup_code": old.get("qr") or old["code"]}
            if old.get("notes"):
                values["notes"] = old["notes"]
            nb.records[rid] = {
                "device_id": old.get("device_id"),
                "name": old.get("name"),
                "area": old.get("area"),
                "manufacturer": old.get("manufacturer"),
                "model": old.get("model"),
                "serial": old.get("serial"),
                "connections": [],
                "values": values,
                "picked": [],
                "identity": None,
                "updated": old.get("updated") or _now(),
            }
        nb.dismissed = set(legacy.get("dismissed") or ())
    return nb
