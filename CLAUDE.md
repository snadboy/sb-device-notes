# sb-device-notes

Home Assistant custom integration **SB Device Notes** (domain `sb_device_notes`): user-defined
fields on devices (Matter setup code, warranty, notes…), kept across factory resets.
Grew out of "Matter Codes" 0.1 (domain `matter_codes`), which replaced the
" MTR xxxx-xxx-xxxx" device labels.

**Public repo.** Never commit real setup codes, serials or device names: tests use made-up
valid codes (`codes.build_manual`). History was restarted on going public (2026-10-22) to
drop the real codes the early commits had.

## Repository
- Remote: https://github.com/snadboy/sb-device-notes (public; was ha-matter-codes)
- Local: ~/projects/git/sb-device-notes
- Main branch: main

## Deploy
| | |
|---|---|
| HA | 2026.10.0 on `homeassistant` |
| HACS | custom repository (integration). Release = bump `manifest.json` version → commit, push → `gh release create vX.Y.Z` → HACS update → FULL HA restart (Python) |
| Quick test deploy | `tar czf - --exclude=__pycache__ -C custom_components sb_device_notes \| ssh snadboy@homeassistant "cd /homeassistant/custom_components && sudo tar xzf -"` + full restart |
| Storage | `.storage/sb_device_notes`; first run imports `.storage/matter_codes` (Matter Codes 0.1). Backup of that file: `/homeassistant/matter_codes.storage.bak-20261022` |

## Status
- 2026-10-22: Matter Codes 0.1 deployed; all 46 MTR label codes migrated (42 attached, 4
  waiting = labels on no device; 2 labels had a 0 misread as 8, stored corrected with a
  note). 18 Matter devices have no code.
- 2026-10-22: 0.2.0 = generalized into SB Device Notes; public, HACS custom repo id
  **1429873358**, config entry `01M5J7SYFZXK90VJ2ZSGPD0WW4`. Matter Codes entry + files
  removed. Import verified: 42/42 codes on the SAME `text.*_matter_setup_code` entity IDs,
  4 waiting, 2 notes. Date round trip (add/set/bad value rejected/clear) verified live.
  Monitor → Home card repointed to `sensor.sb_device_notes_matter_setup_code`.
- 2026-10-22: 0.2.1 (deprecation fix: iterate `dev_reg.devices`, not `.values()`) installed
  via HACS; loads on the next HA restart (not restarted for it).

- 2026-10-22: Re-pair test (Floor Lamp Office Closet H607C, Govee, no serial): code followed
  via Repairs once the old device was deleted. Found + fixed in 0.2.2: repair flow opened with
  `{}` (KeyError → 500); blank maker/model matched other blanks (esp32/crowpanel prompts).
- 2026-10-22: 0.3.0: identity snapshot per record (device name/area + entity IDs/settings/
  exposure, keyed by platform|domain|translation_key|original_name|n) and a restore step in
  Repairs (+ `restore_<record>` issue, `sb_device_notes.restore`). Unavailable same-model
  devices are now candidates (pair-before-delete). Snapshot capture verified live (42
  records). First live restore 2026-10-22 (Floor Lamp Office East H607C): name, area, all
  entity IDs, group membership and Assist exposure came back. Gotchas seen: (1) the restore
  dialog rendered blank: the browser held pre-0.3.0 translations (server served them fine,
  checked with `frontend/get_translations`); a refresh fixes it. (2) The old lamp had two
  Identify buttons, the new one one: it took the first old key's ID (`…_identify_1`).

- 2026-10-22: Serial-device re-pair (Shelf Power P110M): HA revived the SAME device ID by
  serial (name, area, entity IDs back) but entities were new (node C2), so entity settings
  reset and 0.3.0 saw nothing to restore and overwrote the snapshot. 0.3.1: `reissued()`
  (≥ half of matched entity keys have new unique IDs) → keep snapshot, `identity.repaired`,
  issue `restore_settings`. Shelf Power's own pre-repair snapshot was already lost.

## Next steps
- [x] MTR labels deleted 2026-10-22 (40 left by then; user OK'd). 4 waiting codes forgotten. 0/8 fixes confirmed by user; their notes cleared.
- [ ] 18 devices without codes: SB Todos task "Record Matter setup codes for 18 devices" (Homelab, id 1xhmmvcyl57d), one subtask per device.
- [x] Re-pair tests done 2026-10-22: Govee ×2 (repair pick + restore), P110M Shelf (serial; HA revived same device → 0.3.1).
- [ ] Next serial-device re-pair: confirm the 0.3.1 `restore_settings` prompt appears and restores exposure.
- [ ] Next re-pair: confirm the restore dialog shows its text (blank once from a stale browser cache).
- [x] 0.4.0 sidebar page `/sb-device-notes` (websocket.py + frontend/sb-device-notes.js, SB UI Kit
      rows). Verified headless (uv + playwright, chrome-headless-shell-1248, hassTokens in
      localStorage): list/search/chips/copy/edit/bad-code error/add-field/clear, Fields add/dup/delete,
      390 px phone layout. No console errors.
- [x] 0.4.1: sidebar entry/page title "SB Device Notes" (user). Monitor → Home Markdown card removed 2026-10-22 (user); `dashboard/matter-setup-code-card.yaml` stays in the repo as an optional extra.

## Build / test
- `cd tests && python3 test_codes.py && python3 test_model.py` (offline; 21 checks)
- `python3 -m py_compile custom_components/sb_device_notes/*.py`

## Design notes
- `codes.py` and `model.py` are pure (no HA imports) so they test offline; tests load them
  through a stub package (`tests/_load.py`) to skip `__init__.py`.
- Field entities link to their device with `self.device_entry = …` (HA 2026.10), NOT
  `device_info`: device_info would claim the device for this config entry (HA 2026.x devices
  have a single `config_entry_id`), and deleting the device would then not remove it. With
  device_entry, deleting works; `entity.py` then removes our entity.
- Entity unique_id `<device_id>__<field_id>`; named after the field (dynamic `name`), so a
  field rename renames entities but keeps entity IDs. Platform per type: text (text, link,
  matter_code), date, number, switch (yes/no), sensor (long text, read-only; + one
  `summary__<field_id>` sensor per field on the "SB Device Notes" service device).
- A field shows on a device if in scope (all / integrations / picked), or the device has a
  value, or it was picked. Clearing a picked field's value un-picks it.
- Matching a waiting record: device_id exists → unique serial → unique connection → same
  Matter code entered (moves/merges the whole record). Duplicate serials/connections across
  current devices are ignored.
- Repair issue `unmatched_<device_id>`: device with no record AND a waiting record with the
  same manufacturer+model; "new device" answer remembered in `dismissed`.
- Type changes only among text / long text / link, and only if every value fits.
