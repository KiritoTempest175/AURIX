// ─────────────────────────────────────────────────────────────────────────────
// tests/rust/test_power_governor.rs
// ─────────────────────────────────────────────────────────────────────────────
// Rust Integration Tests for LUNA Power Governor & State Management.
// ─────────────────────────────────────────────────────────────────────────────

use core_engine::governor::atomic_state::{
    check_power_state, check_power_state_name, check_suspend_flag, get_power_state,
    get_suspend_flag, set_power_state, set_suspend_flag, PowerState, SystemState,
};
use core_engine::sandbox::file_jail::secure_path_resolve;
use std::path::Path;

#[test]
fn test_power_state_transitions() {
    let state = SystemState::new();

    assert_eq!(state.get_power_state_name(), "ACTIVE");
    assert!(!state.check_suspended());

    // Switch to Idle
    state.set_power_state(PowerState::Idle as u8);
    assert_eq!(state.get_power_state_name(), "IDLE");
    assert!(state.is_idle_or_locked());

    // Switch to Locked
    state.set_power_state(PowerState::Locked as u8);
    assert_eq!(state.get_power_state_name(), "LOCKED");
    assert!(state.is_idle_or_locked());

    // Switch to Suspending
    state.set_power_state(PowerState::Suspending as u8);
    assert_eq!(state.get_power_state_name(), "SUSPENDING");
    assert!(state.is_suspending());
}

#[test]
fn test_workload_pause_resume() {
    let state = SystemState::new();

    assert!(!state.check_suspended());
    state.pause();
    assert!(state.check_suspended());
    assert!(check_suspend_flag());

    state.resume();
    assert!(!state.check_suspended());
    assert!(!check_suspend_flag());
}
