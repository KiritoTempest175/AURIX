# core_engine/__init__.py
#
# Bridges Python imports to the compiled Rust/PyO3 extension (.pyd).
# If the extension is not compiled yet, raises an actionable ImportError.

import importlib.machinery
import importlib.util
import os
import sys

_found_pyd = None
_dir = os.path.dirname(os.path.abspath(__file__))
_candidates = [
    os.path.join(_dir, "..", "core_engine.pyd"),
    os.path.join(_dir, "core_engine.pyd"),
    os.path.join(_dir, "..", "target", "release", "core_engine.dll"),
]

for _cand in _candidates:
    if os.path.isfile(_cand):
        _found_pyd = os.path.abspath(_cand)
        break

if not _found_pyd:
    raise ImportError(
        "core_engine .pyd extension not compiled. "
        "Run: .\\scripts\\build_engine.ps1  (from the AURIX directory)"
    )

try:
    _loader = importlib.machinery.ExtensionFileLoader("core_engine", _found_pyd)
    _spec = importlib.util.spec_from_loader("core_engine", _loader)
    _mod = importlib.util.module_from_spec(_spec)
    _loader.exec_module(_mod)

    for _attr in dir(_mod):
        if not _attr.startswith("__"):
            globals()[_attr] = getattr(_mod, _attr)
    if hasattr(_mod, "__all__"):
        __all__ = _mod.__all__
except Exception as _err:
    raise ImportError(
        f"Failed to load compiled core_engine extension from {_found_pyd}: {_err}\n"
        "Run: .\\scripts\\build_engine.ps1"
    ) from _err

