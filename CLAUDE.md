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
- 2026-10-22: 0.2.0 = generalized into SB Device Notes. Not yet running: waiting on the user
  to delete the Matter Codes config entry (the auto-mode classifier blocked me), so the new
  `text.*_matter_setup_code` entities can take the same entity IDs.

## Next steps
- [ ] User deletes the Matter Codes entry → restart → add SB Device Notes → verify 42
      codes on the same entity IDs + 4 waiting → repoint the Monitor → Home card at
      `sensor.sb_device_notes_matter_setup_code` (`rows`, key `value`) → remove
      `/homeassistant/custom_components/matter_codes` and the stray `device_notes` copy.
- [ ] Delete the 46 MTR labels: ON HOLD (user). Do not delete until asked.
- [ ] User re-pair test: a P110M (serial) and a Govee (repair prompt / re-enter code).
- [ ] Sidebar panel: table of devices × fields, search, inline edit, add field to device,
      tap-to-copy; then retire the Markdown card.

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
