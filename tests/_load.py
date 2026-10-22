"""Import the pure modules without running the package __init__ (which needs Home Assistant)."""

import importlib
import pathlib
import sys
import types

_PKG = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "sb_device_notes"
if "sb_device_notes" not in sys.modules:
    _pkg = types.ModuleType("sb_device_notes")
    _pkg.__path__ = [str(_PKG)]
    sys.modules["sb_device_notes"] = _pkg

codes = importlib.import_module("sb_device_notes.codes")
model = importlib.import_module("sb_device_notes.model")
