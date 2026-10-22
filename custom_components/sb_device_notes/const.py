"""Constants for SB Device Notes."""

DOMAIN = "sb_device_notes"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1
LEGACY_STORAGE_KEY = "matter_codes"  # Matter Codes 0.1, imported on first run

# Fired after every refresh: entities re-render, platforms add/remove entities.
SIGNAL_UPDATED = f"{DOMAIN}_updated"

ISSUE_PREFIX = "unmatched_"
SUMMARY_PREFIX = "summary__"
