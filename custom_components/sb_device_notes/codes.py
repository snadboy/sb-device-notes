"""Matter onboarding codes: parse, check and format. Pure Python, no Home Assistant imports.

Two forms are accepted:
- the manual pairing code, 11 digits (or 21 with vendor/product id), ending in a
  Verhoeff check digit, printed as e.g. 3497-011-2332;
- the QR payload, "MT:" followed by base-38 text.

A QR payload carries more than the manual code (the full 12-bit discriminator, vendor
and product id), so a manual code can be derived from a QR payload but not the reverse.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

# Verhoeff tables (dihedral group D5).
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)

_BASE38 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-."

# Passcodes the Matter spec forbids.
_BAD_PASSCODES = {int(str(n) * 8) for n in range(10)} | {12345678, 87654321}

# Custom commissioning flow: the manual code must then carry vendor and product id.
_FLOW_CUSTOM = 2


class CodeError(ValueError):
    """The text is not a valid Matter setup code; the message says why."""


@dataclass(frozen=True)
class SetupCode:
    """A parsed setup code. `manual` is always set; `qr` only when a QR payload was given."""

    manual: str
    passcode: int
    qr: str | None = None
    discriminator: int | None = None  # 12-bit, QR only
    vendor_id: int | None = None
    product_id: int | None = None

    @property
    def short_discriminator(self) -> int:
        return short_discriminator(self.manual)

    @property
    def formatted(self) -> str:
        return format_manual(self.manual)


def verhoeff_digit(digits: str) -> str:
    """Return the check digit to append to `digits`."""
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def verhoeff_valid(digits: str) -> bool:
    """True when the last digit of `digits` is its correct Verhoeff check digit."""
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def format_manual(manual: str) -> str:
    """3497-011-2332 for 11 digits (how the codes are printed); longer codes in more groups."""
    if len(manual) == 11:
        return f"{manual[:4]}-{manual[4:7]}-{manual[7:]}"
    return f"{manual[:4]}-{manual[4:7]}-{manual[7:11]}-{manual[11:16]}-{manual[16:]}"


def short_discriminator(manual: str) -> int:
    """The 4-bit discriminator a manual code carries."""
    return ((int(manual[0]) & 0b11) << 2) | (int(manual[1:6]) >> 14)


def build_manual(
    passcode: int,
    discriminator: int,
    vendor_id: int | None = None,
    product_id: int | None = None,
) -> str:
    """Build the manual code from its parts (discriminator is the full 12 bits)."""
    long = vendor_id is not None and product_id is not None
    first = (int(long) << 2) | (discriminator >> 10)
    chunk2 = ((discriminator & 0x300) << 6) | (passcode & 0x3FFF)
    chunk3 = passcode >> 14
    body = f"{first}{chunk2:05d}{chunk3:04d}"
    if long:
        body += f"{vendor_id:05d}{product_id:05d}"
    return body + verhoeff_digit(body)


def _check_passcode(passcode: int) -> None:
    if not 1 <= passcode <= 99999998 or passcode in _BAD_PASSCODES:
        raise CodeError("That code decodes to a passcode Matter does not allow; check it was copied right")


def parse_manual(digits: str) -> SetupCode:
    """Parse an 11- or 21-digit manual code (digits only)."""
    if len(digits) not in (11, 21):
        raise CodeError(f"A manual pairing code is 11 or 21 digits; this one has {len(digits)}")
    if not verhoeff_valid(digits):
        raise CodeError("The check digit (the last digit) doesn't match: a digit is probably mistyped")
    first = int(digits[0])
    if first > 7:
        raise CodeError("A manual pairing code never starts with 8 or 9")
    long = bool(first & 0b100)
    if long != (len(digits) == 21):
        want = 21 if long else 11
        raise CodeError(f"The first digit says this code should be {want} digits long")
    chunk2 = int(digits[1:6])
    if chunk2 > 0xFFFF:
        raise CodeError("Digits 2–6 are out of range: a digit is probably mistyped")
    passcode = (int(digits[6:10]) << 14) | (chunk2 & 0x3FFF)
    _check_passcode(passcode)
    vid = pid = None
    if long:
        vid, pid = int(digits[10:15]), int(digits[15:20])
    return SetupCode(manual=digits, passcode=passcode, vendor_id=vid, product_id=pid)


def _base38_decode(text: str) -> bytes:
    out = bytearray()
    for i in range(0, len(text), 5):
        chunk = text[i : i + 5]
        size = {5: 3, 4: 2, 2: 1}.get(len(chunk))
        if size is None:
            raise CodeError("The QR payload is the wrong length")
        value = 0
        for ch in reversed(chunk):
            idx = _BASE38.find(ch)
            if idx < 0:
                raise CodeError(f"'{ch}' can't appear in a Matter QR payload")
            value = value * 38 + idx
        if value >= 1 << (8 * size):
            raise CodeError("The QR payload is corrupt")
        out += value.to_bytes(size, "little")
    return bytes(out)


def parse_qr(text: str) -> SetupCode:
    """Parse an "MT:" QR payload. Only the first device of a multi-device payload is used."""
    payload = text.strip()[3:].split("*")[0].upper()
    raw = _base38_decode(payload)
    if len(raw) < 11:
        raise CodeError("The QR payload is too short")
    bits = int.from_bytes(raw[:11], "little")
    version = bits & 0b111
    if version != 0:
        raise CodeError(f"Unknown QR payload version {version}")
    vid = (bits >> 3) & 0xFFFF
    pid = (bits >> 19) & 0xFFFF
    flow = (bits >> 35) & 0b11
    discriminator = (bits >> 45) & 0xFFF
    passcode = (bits >> 57) & 0x7FFFFFF
    _check_passcode(passcode)
    if flow == _FLOW_CUSTOM:
        manual = build_manual(passcode, discriminator, vid, pid)
    else:
        manual = build_manual(passcode, discriminator)
    return SetupCode(
        manual=manual,
        passcode=passcode,
        qr="MT:" + payload,
        discriminator=discriminator,
        vendor_id=vid,
        product_id=pid,
    )


def parse(text: str) -> SetupCode:
    """Parse whatever the user typed or pasted: a manual code (spaces, dashes and dots
    allowed) or an MT: QR payload."""
    s = (text or "").strip()
    if not s:
        raise CodeError("No code given")
    if s[:3].upper() == "MT:":
        return parse_qr(s)
    digits = re.sub(r"[\s\-.]", "", s)
    if not digits.isdigit():
        raise CodeError("A setup code is 11 or 21 digits, or a QR payload starting MT:")
    return parse_manual(digits)
