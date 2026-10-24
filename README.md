# SB Device Notes

Home Assistant custom integration: your own fields on devices (a Matter setup code, a
warranty date, notes, anything you define), kept when a device is deleted and
re-attached when it comes back, e.g. after a factory reset.

## The SB Device Notes page

A page (admins) that lists every device with its notes. Open it from the sidebar
(**SB Device Notes**), or tap ⚙ on the integration (*Settings → Devices & services → SB Device
Notes*, the entry titled "Tap ⚙ to view, edit, scan codes").

- **Search** by name, area, model or value (a code matches with or without dashes).
- **Filter**: *With notes*, *Missing a value* (of the chosen field, or any field the device
  shows), *Waiting* (notes of removed devices), *All devices*; and pick one field to show.
- **Copy** any value with its copy button, e.g. a setup code for the pairing screen.
- **Tap a device** to edit its fields in place, or add a field to it. Mistyped codes are
  rejected with the reason.
- **Quick entry**: under *Missing a value*, each device shows an empty box for what it's
  missing. Type and press Enter: it saves and moves to the next device.
- **Scan a Matter QR code**: the **Scan** button next to a Matter code box reads the code with
  the camera, using the Home Assistant app's own scanner (the one HA uses to add Matter devices),
  or in a browser that has the BarcodeDetector API (Chrome on Android, Safari) over https. Where
  the camera can't be used, tapping it says why. The full QR payload is stored, and the 11-digit
  code derived from it.
- **Fields tab**: create, edit and delete fields.

Requires the [SB UI Kit](https://github.com/snadboy/sb-ui-kit) integration (shared row style).

## On the device page

Each field is also an entity on its device (a Matter code is a text box there, with a key icon).
Home Assistant gives that page no room for anything else, so scanning lives on the SB Device
Notes page; a code mistyped on the device page is rejected with the reason and a pointer to it.

## Fields

Create, edit and delete fields on the page's **Fields** tab. Each field has:

- **Type:** text (≤255 characters), long text, date, number, yes/no, link, or Matter
  setup code. Each shows on the device page as the matching control (text box, date
  picker, number box, switch). Long text shows read-only (first 255 characters); edit it
  with `sb_device_notes.set`.
- **Scope:** which devices show it: all devices, devices of chosen integrations, or only
  devices you add it to (*+ Add a field…* in the device's editor). A device with a value
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

## Restoring a re-added device

While a device has notes, SB Device Notes keeps a snapshot of it: name, area, and each
entity's ID, custom name, icon, area, labels, aliases, hidden/disabled choice and voice
exposure. When the notes move to a new HA device (picked in Repairs, matched by serial or
MAC, or a Matter code entered on it), Repairs offers **"Make <new> <old> again?"**, with a
preview, to put all of that back. Entities are matched by what they are (platform, kind,
translation key, name), since their unique IDs change on re-pairing; anything without a
match is listed, never guessed.

Devices that report a serial number usually come back as the *same* HA device (HA revives
it by serial, with its name and area), but with new entities whose settings are back to
defaults. When all of a device's entities reappear with new unique IDs, Repairs offers
**"Restore <device>'s entity settings?"** from the snapshot taken before.

If the device is paired again before the old one is deleted, the old one shows as
*unavailable, still in HA* in the pick list, and entity IDs it still holds are listed as
"still in use": delete the old device and submit again (or run `sb_device_notes.restore`).

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
| `sb_device_notes.restore` | Restore a re-added device's old name, area and entity IDs |
| `sb_device_notes.forget` | Delete a device's (or a waiting record's) notes |
| `sb_device_notes.add_field` / `update_field` / `delete_field` | Manage fields from scripts (`delete_field` needs `confirm: true`) |

Storage: `.storage/sb_device_notes`, so it's in every HA backup. Requires HA 2026.10+.

## Tests

```
cd tests && python3 test_codes.py && python3 test_model.py   # or: pytest tests
```
