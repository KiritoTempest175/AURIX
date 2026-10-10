// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/governor/monitor.rs
// ─────────────────────────────────────────────────────────────────────────────
// Hardware Resource Governor v2 — Adaptive idle-aware polling loop.
//
// Continuously monitors host RAM (sysinfo), GPU VRAM (NVML), GPU temperature,
// and user idle time / screen lock status (IdleMonitor).
// Dynamically transitions PowerState between Active, Idle, Locked, and Suspending.
// ─────────────────────────────────────────────────────────────────────────────

use pyo3::prelude::*;
use std::thread;
use std::time::Duration;
use sysinfo::System;
use nvml_wrapper::Nvml;

use crate::governor::atomic_state::{set_power_state, set_suspend_flag, PowerState};
use crate::governor::idle_monitor::create_idle_monitor;

// Adaptive memory pressure, relative to actual installed hardware.
// No absolute memory quotas or mandatory GPU model.
const MIN_FREE_PERCENT: u64 = 5;
const GPU_THERMAL_WARNING_CELSIUS: u32 = 85;
const IDLE_THRESHOLD_SECONDS: u64 = 300;
const ACTIVE_POLL_INTERVAL_MS: u64 = 2500;
const IDLE_POLL_INTERVAL_MS: u64 = 5000;

/// Low free-memory indicator for background-work yielding, not an allocation cap.
pub fn memory_pressure(free_bytes: u64, total_bytes: u64) -> bool {
    total_bytes > 0 && (free_bytes as u128) * 100 < (total_bytes as u128) * MIN_FREE_PERCENT as u128
}

/// NVML is optional: inspect all NVIDIA devices, never enforce index zero.
/// Non-NVIDIA/CPU-only systems continue with system RAM metrics.
fn gpu_snapshot(nvml: &Nvml) -> (Option<u64>, Option<u64>, Option<u32>) {
    let mut sample: Option<(u64, u64, Option<u32>)> = None;
    if let Ok(count) = nvml.device_count() {
        for index in 0..count {
            if let Ok(device) = nvml.device_by_index(index) {
                if let Ok(mem) = device.memory_info() {
                    let temp = device.temperature(
                        nvml_wrapper::enum_wrappers::device::TemperatureSensor::Gpu
                    ).ok();
                    let more_pressured = sample.map_or(true, |(used, total, _)| {
                        total == 0 || (mem.used as u128) * (total as u128)
                            > (used as u128) * (mem.total as u128)
                    });
                    if more_pressured {
                        sample = Some((mem.used, mem.total, temp));
                    }
                }
            }
        }
    }
    match sample {
        Some((used, total, temp)) => (Some(used), Some(total), temp),
        None => (None, None, None),
    }
}

/// Snapshot of system hardware state.
#[derive(Debug, Clone, Copy)]
pub struct ResourceSnapshot {
    pub used_ram_bytes: u64,
    pub total_ram_bytes: u64,
    pub used_vram_bytes: Option<u64>,
    pub total_vram_bytes: Option<u64>,
    pub gpu_temperature_c: Option<u32>,
    pub idle_seconds: u64,
    pub is_screen_locked: bool,
    pub power_state: PowerState,
    pub suspend_triggered: bool,
}

/// Starts the adaptive background hardware governor thread.
#[pyfunction]
pub fn start_hardware_monitor() {
    thread::spawn(move || {
        let mut sys = System::new_all();
        let nvml_opt = Nvml::init().ok();
        let idle_monitor = create_idle_monitor();

        if nvml_opt.is_none() {
            eprintln!("[LUNA Governor] INFO: NVML not detected. Running RAM-only power governor.");
        }

        loop {
            sys.refresh_memory();
            let used_ram = sys.used_memory();

            let idle_sec = idle_monitor.get_idle_seconds();
            let screen_locked = idle_monitor.is_screen_locked();

            // 1. Determine Target Power State based on user activity
            let current_power_state = if screen_locked {
                PowerState::Locked
            } else if idle_sec >= IDLE_THRESHOLD_SECONDS {
                PowerState::Idle
            } else {
                PowerState::Active
            };

            set_power_state(current_power_state);

            // Relative pressure yields background work only when the host
            // genuinely runs low on memory. There is no fixed GiB ceiling.
            let mut should_suspend = memory_pressure(
                sys.available_memory(), sys.total_memory()
            );

            // GPU telemetry is optional. Unknown/non-NVIDIA hardware must
            // never be rejected simply because NVML is unavailable.
            if let Some(ref nvml) = nvml_opt {
                let (used, total, temp) = gpu_snapshot(nvml);
                if let (Some(used), Some(total)) = (used, total) {
                    if memory_pressure(total.saturating_sub(used), total) {
                        should_suspend = true;
                    }
                }
                if let Some(temp) = temp {
                    if temp >= GPU_THERMAL_WARNING_CELSIUS {
                        should_suspend = true;
                    }
                }
            }

            // 5. Update global atomic suspend flag
            set_suspend_flag(should_suspend);

            thread::sleep(Duration::from_millis(
                if current_power_state == PowerState::Active {
                    ACTIVE_POLL_INTERVAL_MS
                } else {
                    IDLE_POLL_INTERVAL_MS
                }
            ));
        }
    });
}

/// Single-shot diagnostic snapshot.
pub fn snapshot_resources() -> ResourceSnapshot {
    let mut sys = System::new_all();
    sys.refresh_memory();
    let idle_monitor = create_idle_monitor();

    let used_ram = sys.used_memory();
    let total_ram = sys.total_memory();
    let idle_sec = idle_monitor.get_idle_seconds();
    let screen_locked = idle_monitor.is_screen_locked();

    let (used_vram, total_vram, gpu_temp) = Nvml::init()
        .map(|nvml| gpu_snapshot(&nvml))
        .unwrap_or((None, None, None));

    let power_state = if screen_locked {
        PowerState::Locked
    } else if idle_sec >= IDLE_THRESHOLD_SECONDS {
        PowerState::Idle
    } else {
        PowerState::Active
    };

    let suspend_triggered = memory_pressure(sys.available_memory(), total_ram)
        || match (used_vram, total_vram) {
            (Some(used), Some(total)) => memory_pressure(total.saturating_sub(used), total),
            _ => false,
        }
        || gpu_temp.map_or(false, |temp| temp >= GPU_THERMAL_WARNING_CELSIUS);

    ResourceSnapshot {
        used_ram_bytes: used_ram,
        total_ram_bytes: total_ram,
        used_vram_bytes: used_vram,
        total_vram_bytes: total_vram,
        gpu_temperature_c: gpu_temp,
        idle_seconds: idle_sec,
        is_screen_locked: screen_locked,
        power_state,
        suspend_triggered,
    }
}

#[cfg(test)]
mod pressure_tests {
    use super::memory_pressure;
    #[test]
    fn adapts_to_different_memory_sizes() {
        let gib = 1024_u64 * 1024 * 1024;
        assert!(!memory_pressure(2 * gib, 8 * gib));
        assert!(!memory_pressure(30 * gib, 128 * gib));
        assert!(memory_pressure(100 * 1024 * 1024, 8 * gib));
        assert!(memory_pressure(2 * gib, 128 * gib));
    }
    #[test]
    fn missing_memory_metrics_do_not_trigger() {
        assert!(!memory_pressure(0, 0));
    }
}
