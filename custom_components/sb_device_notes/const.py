"""Constants for SB Device Notes."""

DOMAIN = "sb_device_notes"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1
LEGACY_STORAGE_KEY = "matter_codes"  # Matter Codes 0.1, imported on first run

# Fired after every refresh: entities re-render, platforms add/remove entities.
SIGNAL_UPDATED = f"{DOMAIN}_updated"

ISSUE_PREFIX = "unmatched_"
RESTORE_PREFIX = "restore_"
SUMMARY_PREFIX = "summary__"

PANEL_URL = "sb-device-notes"
STATIC_URL = "/sb_device_notes_static"

# The config entry's title is the one line of our own text the integration page shows, so it
# says how to reach the page (the entry's ⚙ opens it). Fits a phone screen.
ENTRY_TITLE = "Tap ⚙ to view, edit, scan codes"
OLD_ENTRY_TITLE = "SB Device Notes"
