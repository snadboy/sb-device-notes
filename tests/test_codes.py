"""Offline checks for codes.py.   python3 tests/test_codes.py   (or pytest)"""

from _load import codes as C

# Matter spec / connectedhomeip test device: passcode 20202021, discriminator 3840.
QR = "MT:Y.K9042C00KA0648G00"
MANUAL = "34970112332"


def _raises(text, fragment):
    try:
        C.parse(text)
    except C.CodeError as err:
        assert fragment in str(err), str(err)
        return
    raise AssertionError(f"{text!r} parsed")


def test_manual():
    c = C.parse("3497-011-2332")
    assert c.manual == MANUAL and c.passcode == 20202021 and c.short_discriminator == 15
    assert c.formatted == "3497-011-2332"
    assert C.parse(" 3497 011 2332 ").manual == MANUAL
    assert C.parse("3497.011.2332").manual == MANUAL


def test_qr():
    c = C.parse(QR)
    assert (c.manual, c.passcode, c.discriminator) == (MANUAL, 20202021, 3840)
    assert (c.vendor_id, c.product_id) == (0xFFF1, 0x8000)
    assert c.qr == QR
    assert C.parse(QR.lower().replace("mt:", "mt:")).manual == MANUAL


def test_long_code():
    assert C.build_manual(20202021, 3840, 65521, 32769) == "749701123365521327694"
    c = C.parse("749701123365521327694")
    assert (c.vendor_id, c.product_id, c.passcode) == (65521, 32769, 20202021)


def test_check_digit_catches_every_single_digit_error():
    for i in range(11):
        for d in "0123456789":
            if d != MANUAL[i]:
                bad = MANUAL[:i] + d + MANUAL[i + 1 :]
                assert not C.verhoeff_valid(bad), bad


def test_rejects():
    _raises("34970112333", "check digit")
    _raises("3497011233", "11 or 21 digits")
    _raises("8298-200-7398", "")  # an 8 misread for a 0: fails the check digit
    _raises("abc", "11 or 21 digits, or a QR")
    _raises("", "No code")
    _raises("MT:Y.K9042C00KA0648G0", "length")
    # 12345678 is a forbidden passcode
    _raises(C.build_manual(12345678, 0), "not allow")


def test_zero_for_eight_fix():
    assert C.parse("0298-200-7398").manual == "02982007398"
    assert C.parse("1077-981-9175").manual == "10779819175"


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            n += 1
    print(f"{n} passed")
