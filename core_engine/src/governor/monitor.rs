// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/governor/monitor.rs
// ─────────────────────────────────────────────────────────────────────────────
// Hardware Resource Governor — background polling loop.
//
// This module spawns a dedicated OS thread that polls host RAM via `sysinfo`
// and GPU VRAM via `nvml-wrapper` at a configurable interval (default 1000ms).
// When either metric exceeds the blueprint-mandated hard ceilings, it writes
// `true` to the global `AtomicBool` suspend flag so the Python QLoRA loop
// yields the GPU within one micro-batch iteration.
//
// Design rationale:
// - `std::thread::spawn` instead of `tokio` because the monitor is a simple
//   sleep-poll loop with no async I/O. Adding a full async runtime would
//   increase RSS by ~2MB for zero benefit.
// - The thread is detached (the `JoinHandle` is intentionally dropped) so it
//   lives for the entire process lifetime. This is safe because it only reads
//   hardware counters and writes to an atomic flag.
// - `sysinfo::System` is NOT `Send` on some platforms, so we construct it
//   *inside* the spawned thread rather than moving it in.
// ─────────────────────────────────────────────────────────────────────────────

use pyo3::prelude::*;
use std::thread;
use std::time::Duration;
use sysinfo::System;
use nvml_wrapper::Nvml;
use crate::governor::atomic_state::set_suspend_flag;

// ─── Blueprint v2.0 Hard Ceilings ───────────────────────────────────────────
// These constants are the absolute safety boundaries. If either is exceeded
// the governor MUST suspend the AI workload immediately.
//
// RAM: 12 GB out of 16 GB host (75% utilisation ceiling)
// VRAM: 6 GB out of 8 GB device (75% utilisation ceiling)
// ─────────────────────────────────────────────────────────────────────────────

/// Maximum allowed system RAM usage in bytes (12 GiB).
const MAX_RAM_BYTES: u64 = 12 * 1024 * 1024 * 1024;

/// Maximum allowed GPU VRAM usage in bytes (6 GiB).
const MAX_VRAM_BYTES: u64 = 6 * 1024 * 1024 * 1024;

/// Polling interval in milliseconds. Blueprint specifies 1000ms.
/// Shorter intervals increase CPU overhead; longer intervals risk
/// overshooting the ceiling before the governor reacts.
const POLL_INTERVAL_MS: u64 = 1000;

/// GPU device index to monitor. Index 0 is the primary discrete GPU.
const GPU_DEVICE_INDEX: u32 = 0;

// ─── Resource Snapshot ──────────────────────────────────────────────────────
// A plain data struct capturing one point-in-time reading.
// Not exported to Python — this is an internal diagnostic tool.
// ─────────────────────────────────────────────────────────────────────────────

/// A snapshot of current hardware resource usage at a single point in time.
/// Used internally for structured logging and threshold comparison.
#[derive(Debug, Clone, Copy)]
pub struct ResourceSnapshot {
    /// System RAM currently in use, in bytes.
    pub used_ram_bytes: u64,
    /// Total system RAM available, in bytes.
    pub total_ram_bytes: u64,
    /// GPU VRAM currently in use, in bytes.  `None` if no NVIDIA GPU detected.
    pub used_vram_bytes: Option<u64>,
    /// Total GPU VRAM, in bytes.  `None` if no NVIDIA GPU detected.
    pub total_vram_bytes: Option<u64>,
    /// Whether the governor has decided to suspend the workload.
    pub suspend_triggered: bool,
}

// ─── Legacy PyFunction Export ───────────────────────────────────────────────

/// Starts the background hardware governor thread.
///
/// This is the primary entry point called from Python at agent boot:
/// ```python
/// import aurix_core
/// aurix_core.start_hardware_monitor()
/// ```
///
/// The thread runs for the lifetime of the process. If the monitor is called
/// multiple times, each call spawns an additional thread (idempotency guard
/// is recommended at the Python layer).
#[pyfunction]
pub fn start_hardware_monitor() {
    thread::spawn(move || {
        // ── Initialise sysinfo inside the thread ─────────────────────────
        // `System::new_all()` performs a full initial scan of all subsystems.
        // We only need memory, but the initial scan is negligible (~1ms).
        let mut sys = System::new_all();

        // ── Initialise NVML (NVIDIA Management Library) ──────────────────
        // This can fail on systems without an NVIDIA GPU, in CI runners,
        // or if the NVIDIA driver is not installed.  We degrade gracefully
        // to RAM-only monitoring rather than crashing.
        let nvml_opt = Nvml::init().ok();

        if nvml_opt.is_none() {
            eprintln!(
                "[AURIX Governor] WARNING: NVML initialisation failed. \
                 GPU VRAM monitoring is DISABLED. Only RAM will be governed."
            );
        }

        // ── Main polling loop ────────────────────────────────────────────
        loop {
            // Refresh only the memory subsystem (cheaper than refresh_all).
            sys.refresh_memory();
            let used_ram = sys.used_memory();

            // Start with the assumption that no suspension is needed.
            let mut should_suspend = false;

            // ── RAM check ────────────────────────────────────────────────
            // sysinfo returns memory in bytes on Windows.
            if used_ram >= MAX_RAM_BYTES {
                eprintln!(
                    "[AURIX Governor] RAM CEILING BREACHED: {:.2} GB / {:.2} GB limit",
                    used_ram as f64 / (1024.0 * 1024.0 * 1024.0),
                    MAX_RAM_BYTES as f64 / (1024.0 * 1024.0 * 1024.0),
                );
                should_suspend = true;
            }

            // ── VRAM check ───────────────────────────────────────────────
            // We query device 0 (the primary discrete GPU). If the system
            // has multiple GPUs, the blueprint only governs the one running
            // the QLoRA workload.
            if let Some(ref nvml) = nvml_opt {
                if let Ok(device) = nvml.device_by_index(GPU_DEVICE_INDEX) {
                    if let Ok(mem_info) = device.memory_info() {
                        if mem_info.used >= MAX_VRAM_BYTES {
                            eprintln!(
                                "[AURIX Governor] VRAM CEILING BREACHED: {:.2} GB / {:.2} GB limit",
                                mem_info.used as f64 / (1024.0 * 1024.0 * 1024.0),
                                MAX_VRAM_BYTES as f64 / (1024.0 * 1024.0 * 1024.0),
                            );
                            should_suspend = true;
                        }
                    }
                }
            }

            // ── Update the atomic suspend flag ───────────────────────────
            // This write is immediately visible to the Python QLoRA loop
            // polling `check_suspend_flag()` on any thread.
            set_suspend_flag(should_suspend);

            // ── Sleep until next poll ────────────────────────────────────
            thread::sleep(Duration::from_millis(POLL_INTERVAL_MS));
        }
    });
}

// ─── Diagnostic Function (Rust-only, not exported to Python) ────────────────

/// Take a single-shot resource snapshot without side effects.
///
/// This is useful for integration tests and diagnostics. It does NOT
/// modify the suspend flag.
pub fn snapshot_resources() -> ResourceSnapshot {
    let mut sys = System::new_all();
    sys.refresh_memory();

    let used_ram = sys.used_memory();
    let total_ram = sys.total_memory();

    let (used_vram, total_vram) = match Nvml::init() {
        Ok(nvml) => {
            if let Ok(device) = nvml.device_by_index(GPU_DEVICE_INDEX) {
                if let Ok(mem) = device.memory_info() {
                    (Some(mem.used), Some(mem.total))
                } else {
                    (None, None)
                }
            } else {
                (None, None)
            }
        }
        Err(_) => (None, None),
    };

    let suspend_triggered = used_ram >= MAX_RAM_BYTES
        || used_vram.map_or(false, |v| v >= MAX_VRAM_BYTES);

    ResourceSnapshot {
        used_ram_bytes: used_ram,
        total_ram_bytes: total_ram,
        used_vram_bytes: used_vram,
        total_vram_bytes: total_vram,
        suspend_triggered,
    }
}
