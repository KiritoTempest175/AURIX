# core_engine/__init__.py
#
# This file intentionally left minimal.
# The real `core_engine` module is a compiled Rust/PyO3 extension (.pyd).
#
# If this __init__.py is what Python loads instead of core_engine.pyd, it means
# the Rust extension hasn't been compiled yet. Raise an ImportError so callers
# get an explicit, actionable message instead of an AttributeError later.
#
# To build the extension:
#   cd AURIX/AURIX
#   scripts\build_engine.ps1
#
raise ImportError(
    "core_engine .pyd extension not compiled. "
    "Run: .\\scripts\\build_engine.ps1  (from the AURIX/AURIX directory)"
)
