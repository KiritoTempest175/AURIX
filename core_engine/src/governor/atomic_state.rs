// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/governor/atomic_state.rs
// ─────────────────────────────────────────────────────────────────────────────
// Bridge module re-exporting power state primitives for backward compatibility
// and module cohesion.
// ─────────────────────────────────────────────────────────────────────────────

pub use crate::governor::power_state::{
    get_power_state, get_suspend_flag, set_power_state, set_suspend_flag, PowerState, SystemState,
};
use pyo3::prelude::*;

/// Legacy PyFunction reading global suspend flag.
#[pyfunction]
pub fn check_suspend_flag() -> bool {
    get_suspend_flag()
}

/// PyFunction reading global power state integer.
#[pyfunction]
pub fn check_power_state() -> u8 {
    get_power_state() as u8
}

/// PyFunction reading global power state name string.
#[pyfunction]
pub fn check_power_state_name() -> String {
    get_power_state().as_str().to_string()
}
