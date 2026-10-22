"""Offline checks for model.py.   python3 tests/test_model.py   (or pytest)"""

from _load import model as M

A = "34970112332"
B = "02982007398"
G = "10779819175"
QR = "MT:Y.K9042C00KA0648G00"  # same device as A

PLUG = M.Device("d1", "Office Plug", "Office", "Tapo", "P110M", "ABC123456789", integration="matter")
PLUG_NEW = M.Device("d9", "Tapo P110M", None, "Tapo", "P110M", "ABC123456789", integration="matter")
LAMP = M.Device("d2", "Floor Lamp East", "Office", "Govee", "H607C", None, integration="matter")
LAMP_NEW = M.Device("d8", "H607C", None, "Govee", "H607C", None, integration="matter")
FRIDGE = M.Device(
    "d3", "Fridge", "Kitchen", "LG", "GBB", None,
    frozenset({("mac", "aa:bb:cc:dd:ee:ff")}), integration="smartthinq",
)
FRIDGE_NEW = M.Device("d7", "LG fridge", None, "LG", "GBB", None, frozenset({("mac", "aa:bb:cc:dd:ee:ff")}), integration="smartthinq")
CODE = "matter_setup_code"


def nb():
    return M.new_notebook()


def _raises(fn, fragment):
    try:
        fn()
    except M.NoteError as err:
        assert fragment in str(err), str(err)
        return
    raise AssertionError("no error")


def test_defaults_and_scope():
    n = nb()
    assert list(n.fields) == ["matter_setup_code", "notes", "warranty_until", "purchased", "where_bought", "manual"]
    assert n.visible(PLUG) == [CODE]
    assert n.visible(FRIDGE) == []


def test_coerce():
    c = M.coerce
    assert c(M.TEXT, "  hi ") == "hi" and c(M.TEXT, "  ") is None and c(M.TEXT, None) is None
    _raises(lambda: c(M.TEXT, "x" * 256), "limit is 255")
    assert c(M.LONG_TEXT, "x" * 2000) == "x" * 2000
    assert c(M.DATE, "2027-03-01") == "2027-03-01"
    _raises(lambda: c(M.DATE, "3/1/27"), "YYYY-MM-DD")
    assert c(M.NUMBER, "4") == 4 and c(M.NUMBER, 2.5) == 2.5
    _raises(lambda: c(M.NUMBER, "four"), "Not a number")
    assert c(M.BOOLEAN, "yes") is True and c(M.BOOLEAN, False) is False
    _raises(lambda: c(M.LINK, "example.com/x"), "http")
    assert c(M.MATTER_CODE, "3497-011-2332") == A
    assert c(M.MATTER_CODE, QR) == QR
    _raises(lambda: c(M.MATTER_CODE, "8298-200-7398"), "")


def test_fields_crud():
    n = nb()
    fid = n.add_field("Filter size", M.TEXT, M.SCOPE_INTEGRATIONS, ["ecobee"])
    assert fid == "filter_size"
    _raises(lambda: n.add_field("filter SIZE", M.TEXT), "already a field")
    _raises(lambda: n.add_field("X", M.TEXT, M.SCOPE_INTEGRATIONS, []), "at least one integration")
    assert n.field_ref("Filter Size") == fid
    n.set_value(FRIDGE, "notes", "door seal")
    n.update_field("notes", name="Comments", ftype=M.LONG_TEXT)
    assert n.fields["notes"]["name"] == "Comments" and n.fields["notes"]["type"] == M.LONG_TEXT
    _raises(lambda: n.update_field("notes", ftype=M.DATE), "only text")
    n.set_value(FRIDGE, "notes", "y" * 300)
    _raises(lambda: n.update_field("notes", ftype=M.TEXT), "doesn't fit")
    assert n.field_usage("notes") == 1
    assert n.delete_field("notes") == 1 and n.records == {}


def test_scope_change_keeps_values():
    n = nb()
    n.set_value(PLUG, CODE, A)
    n.update_field(CODE, scope=M.SCOPE_PICKED)
    assert n.visible(PLUG) == [CODE]  # has a value, so still shows
    assert n.visible(LAMP) == []


def test_pick_and_clear_unpicks():
    n = nb()
    n.pick(FRIDGE, "warranty_until")
    assert n.visible(FRIDGE) == ["warranty_until"]
    n.set_value(FRIDGE, "warranty_until", "2028-01-31")
    assert n.value("d3", "warranty_until") == "2028-01-31"
    n.set_value(FRIDGE, "warranty_until", "")
    assert n.visible(FRIDGE) == [] and n.records == {}


def test_factory_reset_with_serial():
    n = nb()
    n.set_value(PLUG, CODE, A)
    n.set_value(PLUG, "notes", "bought 2025")
    rid = n.for_device("d1")[0]
    assert n.reconcile([LAMP]) is True
    assert n.records[rid]["device_id"] is None and n.records[rid]["name"] == "Office Plug"
    assert [r["status"] for r in n.rows(CODE, [LAMP])][:1] == ["waiting"]
    n.reconcile([LAMP, PLUG_NEW])
    assert n.records[rid]["device_id"] == "d9" and n.value("d9", "notes") == "bought 2025"


def test_factory_reset_by_connection():
    n = nb()
    n.pick(FRIDGE, "manual")
    n.set_value(FRIDGE, "manual", "https://lg.com/manual.pdf")
    n.reconcile([])
    n.reconcile([FRIDGE_NEW])
    assert n.value("d7", "manual") == "https://lg.com/manual.pdf"


def test_duplicate_serial_does_not_match():
    n = nb()
    n.set_value(PLUG, CODE, A)
    rid = n.for_device("d1")[0]
    n.reconcile([])
    twin = M.Device("d6", "Other", None, "Tapo", "P110M", "ABC123456789")
    n.reconcile([PLUG_NEW, twin])
    assert n.records[rid]["device_id"] is None


def test_reset_without_serial_moves_by_code():
    n = nb()
    n.set_value(LAMP, CODE, B)
    n.set_value(LAMP, "notes", "closet")
    rid = n.for_device("d2")[0]
    n.reconcile([LAMP_NEW])
    assert [d.id for d in n.unmatched([LAMP_NEW])] == ["d8"]
    n.set_value(LAMP_NEW, CODE, "0298 200 7398")
    assert n.for_device("d8")[0] == rid and n.value("d8", "notes") == "closet"
    assert len(n.records) == 1 and n.unmatched([LAMP_NEW]) == []


def test_qr_and_manual_are_the_same_device():
    n = nb()
    n.set_value(PLUG, CODE, A)
    n.set_value(PLUG_NEW, CODE, QR)
    assert n.for_device("d1") is None and n.value("d9", CODE) == QR and len(n.records) == 1


def test_code_move_merges_existing_record():
    n = nb()
    n.set_value(LAMP, CODE, B)
    n.set_value(LAMP_NEW, "notes", "new note")
    n.set_value(LAMP_NEW, CODE, B)
    assert len(n.records) == 1 and n.value("d8", "notes") == "new note"


def test_repair_attach_and_dismiss():
    n = nb()
    rid = n.add_waiting("Floor Lamp East", {CODE: B}, manufacturer="Govee", model="H607C")
    other = M.Device("d5", "Desk", None, "Tapo", "L535E", "X1")
    assert [d.id for d in n.unmatched([LAMP_NEW, other])] == ["d8"]
    n.dismissed.add("d8")
    assert n.unmatched([LAMP_NEW]) == []
    n.set_value(LAMP_NEW, "notes", "x")
    n.attach(rid, LAMP_NEW)
    assert n.for_device("d8")[0] == rid and n.value("d8", "notes") == "x" and "d8" not in n.dismissed
    assert n.summary(n.records[rid]) == "0298-200-7398 · Notes: x"


def test_blank_maker_and_model_match_nothing():
    n = nb()
    n.add_waiting("Unknown device", {CODE: A})
    esp = M.Device("d4", "esp32s3", None, None, None, None, integration="esphome")
    assert n.candidates(esp) == [] and n.unmatched([esp]) == []
    half = M.Device("d5", "x", None, "Govee", None, None)
    n.add_waiting("lamp", {CODE: G}, manufacturer="Govee")
    assert n.candidates(half) == []


def test_add_waiting_rejects_duplicates():
    n = nb()
    n.add_waiting("x", {"Matter setup code": A})
    _raises(lambda: n.add_waiting("y", {CODE: QR}), "already stored for x")
    _raises(lambda: n.add_waiting("y", {}), "at least one")
    _raises(lambda: n.add_waiting("y", {"nope": 1}), "No field")


def test_rows():
    n = nb()
    n.set_value(PLUG, CODE, A)
    n.add_waiting("Shelves", {CODE: G}, area="Living Room")
    rows = n.rows(CODE, [PLUG, LAMP, FRIDGE])
    assert [r["status"] for r in rows] == ["waiting", "missing", "attached"]
    assert rows[2]["value"] == "3497-011-2332" and rows[1]["name"] == "Floor Lamp East"


def test_legacy_import():
    legacy = {
        "records": {
            "r1": {"code": A, "qr": None, "device_id": "d1", "name": "Office Plug", "area": "Office",
                   "manufacturer": "Tapo", "model": "P110M", "serial": "ABC123456789",
                   "notes": "fixed", "updated": "2026-10-22T15:00:00+00:00"},
            "r2": {"code": G, "qr": None, "device_id": None, "name": "Unknown", "area": None,
                   "manufacturer": None, "model": None, "serial": None, "notes": "", "updated": "x"},
        },
        "dismissed": ["d8"],
    }
    n = M.new_notebook(legacy)
    assert n.value("d1", CODE) == A and n.value("d1", "notes") == "fixed"
    assert n.records["r2"]["values"] == {CODE: G} and n.dismissed == {"d8"}
    n2 = M.Notebook(**n.to_store())
    assert n2.records == n.records and n2.fields == n.fields


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            n += 1
    print(f"{n} passed")
