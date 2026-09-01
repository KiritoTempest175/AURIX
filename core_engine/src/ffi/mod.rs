// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/ffi/mod.rs
// ─────────────────────────────────────────────────────────────────────────────
// PyO3 FFI module registrations for LUNA Core Engine.
// ─────────────────────────────────────────────────────────────────────────────

use pyo3::prelude::*;
use crate::governor;
use crate::observers;
use crate::sandbox;

/// Registers all core engine classes and functions onto the given Python module.
pub fn register_ffi_bindings(m: &PyModule) -> PyResult<()> {
    // Classes
    m.add_class::<governor::power_state::SystemState>()?;
    m.add_class::<observers::uia_tree::UIATreeObserver>()?;
    m.add_class::<observers::terminal_hook::TerminalHook>()?;

    // Governor Functions
    m.add_function(wrap_pyfunction!(governor::monitor::start_hardware_monitor, m)?)?;
    m.add_function(wrap_pyfunction!(governor::atomic_state::check_suspend_flag, m)?)?;
    m.add_function(wrap_pyfunction!(governor::atomic_state::check_power_state, m)?)?;
    m.add_function(wrap_pyfunction!(governor::atomic_state::check_power_state_name, m)?)?;

    // Sandbox Functions
    m.add_function(wrap_pyfunction!(sandbox::file_jail::validate_path, m)?)?;

    // Observer Functions
    m.add_function(wrap_pyfunction!(observers::uia_tree::get_focused_element_info, m)?)?;
    m.add_function(wrap_pyfunction!(observers::terminal_hook::execute_and_intercept, m)?)?;

    Ok(())
}
