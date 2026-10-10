// Device-independent governor tests; no 6 GiB/12 GiB ceilings.
use core_engine::governor::atomic_state::SystemState;
use core_engine::governor::monitor::memory_pressure;

#[test]
fn pressure_is_relative_to_total_memory() {
    let gib = 1024_u64 * 1024 * 1024;
    assert!(!memory_pressure(4 * gib, 8 * gib));
    assert!(!memory_pressure(16 * gib, 64 * gib));
    assert!(memory_pressure(100 * 1024 * 1024, 8 * gib));
}

#[test]
fn pressure_flag_recovers() {
    let state = SystemState::new();
    state.pause();
    assert!(state.check_suspended());
    state.resume();
    assert!(!state.check_suspended());
}
