# SB Device Notes

Home Assistant custom integration: your own fields on devices (a Matter setup code, a
warranty date, notes, anything you define), kept when a device is deleted and
re-attached when it comes back, e.g. after a factory reset.

## Fields

Create, edit and delete fields under **Settings → Devices & services → SB Device Notes →
Configure**. Each field has:

- **Type:** text (≤255 characters), long text, date, number, yes/no, link, or Matter
  setup code. Each shows on the device page as the matching control (text box, date
  picker, number box, switch). Long text shows read-only (first 255 characters); edit it
  with `sb_device_notes.set`.
- **Scope:** which devices show it: all devices, devices of chosen integrations, or only
  devices you add it to (Configure → *Add a field to a device*). A device with a value
  always shows the field. For an "only devices I add it to" field, clearing the value
  takes it off the device again.

Renaming a field keeps its values and entity IDs. Text, long text and link convert into
each other; other types can't change. Deleting a field asks first and deletes its values.

First run creates: **Matter setup code** (Matter devices), and **Notes**, **Warranty
until**, **Purchased**, **Where bought**, **Manual** (only devices you add them to). It
also imports Matter Codes 0.1 data (`.storage/matter_codes`).

## Matter setup codes

Manual pairing codes end in a Verhoeff check digit, which catches every single mistyped
digit; passcodes the Matter spec forbids are rejected; `MT:` QR payloads are decoded.

## Across factory resets

When a device is deleted its values stay, as *waiting*, with the device's last name,
area, model, serial and connections (MAC, Zigbee address). When a device appears with the
same serial or connection, they re-attach. For devices that report neither (Govee,
Shelly), a Repairs prompt offers same-model waiting notes; or enter the device's Matter
setup code, which brings its notes along (one code, one physical device).

## Lists

Each field has a summary sensor, `sensor.sb_device_notes_<field>` (state: how many devices
have a value; `rows`: every value, waiting first, then devices showing the field with no
value, then by area). [`dashboard/matter-setup-code-card.yaml`](dashboard/matter-setup-code-card.yaml)
is a Markdown card for the Matter setup code; point it at another field's sensor for a
list of that field.

## Actions

| Action | Does |
|---|---|
| `sb_device_notes.set` | `device_id`, `field` (name or id), `value`; no value clears |
| `sb_device_notes.add_to_device` | Show a field on a device without a value yet |
| `sb_device_notes.add_waiting` | Notes for a device not in HA right now (`name`, `values`, optional `manufacturer`, `model`, `area`, `serial`) |
| `sb_device_notes.forget` | Delete a device's (or a waiting record's) notes |
| `sb_device_notes.add_field` / `update_field` / `delete_field` | Manage fields from scripts (`delete_field` needs `confirm: true`) |

Storage: `.storage/sb_device_notes`, so it's in every HA backup. Requires HA 2026.10+.

## Tests

```
cd tests && python3 test_codes.py && python3 test_model.py   # or: pytest tests
```
