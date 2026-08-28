// ─────────────────────────────────────────────────────────────────────────────
// tests/test_governor_limits.rs — Governor Threshold Stress Tests
// ─────────────────────────────────────────────────────────────────────────────
// Verifies that the SystemState suspend flag behaves correctly when the
// hardware governor detects resource usage exceeding blueprint limits.
//
// These tests simulate threshold breaches by directly manipulating the
// SystemState struct rather than waiting for actual hardware spikes.
// This makes them deterministic and CI-friendly.
//
// Blueprint limits:
//   RAM  ≤ 12.0 GiB  (MAX_RAM_BYTES  = 12 * 1024^3)
//   VRAM ≤  6.0 GiB  (MAX_VRAM_BYTES =  6 * 1024^3)
// ─────────────────────────────────────────────────────────────────────────────

use core_engine::governor::atomic_state::SystemState;

/// Simulate a >12GB RAM spike and verify the suspend flag activates.
///
/// In production, the monitor thread calls `state.pause()` when
/// `sysinfo::System::used_memory() >= MAX_RAM_BYTES`.  Here we simulate
/// that decision path directly to test the state machine in isolation.
#[test]
fn test_ram_spike_triggers_suspension() {
    let state = SystemState::new();

    // Pre-condition: system is not suspended.
    assert!(
        !state.check_suspended(),
        "PRECONDITION FAILED: SystemState must start unsuspended"
    );

    // ── Simulate governor detecting RAM > 12GB ──────────────────────────
    // In the real monitor loop, this is:
    //   if used_ram >= MAX_RAM_BYTES { state.pause(); }
    // We call pause() directly to isolate the state-machine logic from
    // actual hardware readings.
    let simulated_ram_bytes: u64 = 13 * 1024 * 1024 * 1024; // 13 GB
    let max_ram_bytes: u64 = 12 * 1024 * 1024 * 1024;       // 12 GB limit

    if simulated_ram_bytes >= max_ram_bytes {
        state.pause();
    }

    // Post-condition: the AI workload MUST be suspended.
    assert!(
        state.check_suspended(),
        "SystemState MUST be suspended when RAM ({} bytes) exceeds limit ({} bytes)",
        simulated_ram_bytes,
        max_ram_bytes
    );
}

/// Simulate a >6GB VRAM spike and verify the suspend flag activates.
#[test]
fn test_vram_spike_triggers_suspension() {
    let state = SystemState::new();

    assert!(!state.check_suspended());

    let simulated_vram_bytes: u64 = 7 * 1024 * 1024 * 1024; // 7 GB
    let max_vram_bytes: u64 = 6 * 1024 * 1024 * 1024;       // 6 GB limit

    if simulated_vram_bytes >= max_vram_bytes {
        state.pause();
    }

    assert!(
        state.check_suspended(),
        "SystemState MUST be suspended when VRAM ({} bytes) exceeds limit ({} bytes)",
        simulated_vram_bytes,
        max_vram_bytes
    );
}

/// Verify that when metrics drop back below thresholds, the flag clears.
#[test]
fn test_resume_when_metrics_recover() {
    let state = SystemState::new();

    // Simulate spike → pause.
    state.pause();
    assert!(state.check_suspended());

    // Simulate recovery → metrics are now below threshold.
    let simulated_ram_bytes: u64 = 8 * 1024 * 1024 * 1024; // 8 GB (under 12 GB)
    let max_ram_bytes: u64 = 12 * 1024 * 1024 * 1024;

    if simulated_ram_bytes < max_ram_bytes {
        state.resume();
    }

    assert!(
        !state.check_suspended(),
        "SystemState MUST resume when metrics return below thresholds"
    );
}

/// Verify that cloned handles observe the same suspension state.
/// This simulates the monitor thread (holding a clone) signaling the
/// main Python thread (holding the original).
#[test]
fn test_cross_thread_governor_signal() {
    let main_state = SystemState::new();
    let monitor_clone = main_state.shared_clone();

    // Monitor thread detects spike and pauses.
    let handle = std::thread::spawn(move || {
        let simulated_ram: u64 = 15 * 1024 * 1024 * 1024; // 15 GB
        let limit: u64 = 12 * 1024 * 1024 * 1024;
        if simulated_ram >= limit {
            monitor_clone.pause();
        }
    });

    handle.join().expect("Monitor thread panicked");

    assert!(
        main_state.check_suspended(),
        "Main thread must observe the monitor thread's pause() call"
    );
}
