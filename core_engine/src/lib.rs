// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/lib.rs — LUNA Core Engine PyO3 FFI Bridge
// ─────────────────────────────────────────────────────────────────────────────
// Root entrypoint for the `core_engine` (and `luna_core` / `aurix_core`) native
// Python extension module.
// ─────────────────────────────────────────────────────────────────────────────

use pyo3::prelude::*;

pub mod ffi;
pub mod governor {
    pub mod atomic_state;
    pub mod idle_monitor;
    pub mod monitor;
    pub mod power_state;
}

pub mod observers {
    pub mod terminal_hook;
    pub mod uia_tree;
}

pub mod sandbox {
    pub mod file_jail;
}

/// The `core_engine` Python native module.
#[pymodule]
fn core_engine(_py: Python, m: &PyModule) -> PyResult<()> {
    ffi::register_ffi_bindings(m)
}
