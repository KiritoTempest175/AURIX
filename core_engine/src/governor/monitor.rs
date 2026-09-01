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

// ─── Hardware Ceilings (Configurable defaults) ──────────────────────────────
const ACTIVE_MAX_RAM_BYTES: u64 = 12 * 1024 * 1024 * 1024;  // 12.0 GiB Active
const IDLE_MAX_RAM_BYTES: u64 = 135 * 1024 * 1024 * 102;   // 13.5 GiB Idle
const ABSOLUTE_MAX_RAM_BYTES: u64 = 14 * 1024 * 1024 * 1024;// 14.0 GiB Absolute

const ACTIVE_MAX_VRAM_BYTES: u64 = 6 * 1024 * 1024 * 1024;  // 6.0 GiB Active
const IDLE_MAX_VRAM_BYTES: u64 = 7 * 1024 * 1024 * 1024;    // 7.0 GiB Idle
const ABSOLUTE_MAX_VRAM_BYTES: u64 = 7372800000;            // ~7.03 GiB Absolute (7.2GB ceiling)

const GPU_THERMAL_LIMIT_CELSIUS: u32 = 82;                  // GPU core temp ceiling
const IDLE_THRESHOLD_SECONDS: u64 = 300;                    // 5 minutes
const POLL_INTERVAL_MS: u64 = 1000;                         // 1000ms cadence
const GPU_DEVICE_INDEX: u32 = 0;

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

            // 2. Select dynamic RAM / VRAM thresholds based on current power state
            let (max_ram, max_vram) = match current_power_state {
                PowerState::Active => (ACTIVE_MAX_RAM_BYTES, ACTIVE_MAX_VRAM_BYTES),
                PowerState::Idle | PowerState::Locked => (IDLE_MAX_RAM_BYTES, IDLE_MAX_VRAM_BYTES),
                PowerState::Suspending => (0, 0),
            };

            let mut should_suspend = false;

            // 3. RAM Limit Verification
            if used_ram >= max_ram || used_ram >= ABSOLUTE_MAX_RAM_BYTES {
                eprintln!(
                    "[LUNA Governor] RAM CEILING BREACH ({:?}): {:.2} GB / {:.2} GB limit",
                    current_power_state,
                    used_ram as f64 / (1024.0 * 1024.0 * 1024.0),
                    max_ram as f64 / (1024.0 * 1024.0 * 1024.0),
                );
                should_suspend = true;
            }

            // 4. VRAM & Thermal Verification
            if let Some(ref nvml) = nvml_opt {
                if let Ok(device) = nvml.device_by_index(GPU_DEVICE_INDEX) {
                    // Check VRAM
                    if let Ok(mem_info) = device.memory_info() {
                        if mem_info.used >= max_vram || mem_info.used >= ABSOLUTE_MAX_VRAM_BYTES {
                            eprintln!(
                                "[LUNA Governor] VRAM CEILING BREACH ({:?}): {:.2} GB / {:.2} GB limit",
                                current_power_state,
                                mem_info.used as f64 / (1024.0 * 1024.0 * 1024.0),
                                max_vram as f64 / (1024.0 * 1024.0 * 1024.0),
                            );
                            should_suspend = true;
                        }
                    }

                    // Check Thermal Throttle
                    if let Ok(temp) = device.temperature(nvml_wrapper::enum_wrappers::device::TemperatureSensor::Gpu) {
                        if temp >= GPU_THERMAL_LIMIT_CELSIUS {
                            eprintln!(
                                "[LUNA Governor] GPU THERMAL THROTTLE TRIGGERED: {} C >= {} C ceiling",
                                temp, GPU_THERMAL_LIMIT_CELSIUS
                            );
                            should_suspend = true;
                        }
                    }
                }
            }

            // 5. Update global atomic suspend flag
            set_suspend_flag(should_suspend);

            thread::sleep(Duration::from_millis(POLL_INTERVAL_MS));
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

    let (used_vram, total_vram, gpu_temp) = match Nvml::init() {
        Ok(nvml) => {
            if let Ok(device) = nvml.device_by_index(GPU_DEVICE_INDEX) {
                let mem = device.memory_info().ok();
                let temp = device.temperature(nvml_wrapper::enum_wrappers::device::TemperatureSensor::Gpu).ok();
                (mem.as_ref().map(|m| m.used), mem.as_ref().map(|m| m.total), temp)
            } else {
                (None, None, None)
            }
        }
        Err(_) => (None, None, None),
    };

    let power_state = if screen_locked {
        PowerState::Locked
    } else if idle_sec >= IDLE_THRESHOLD_SECONDS {
        PowerState::Idle
    } else {
        PowerState::Active
    };

    let max_ram = match power_state {
        PowerState::Active => ACTIVE_MAX_RAM_BYTES,
        _ => IDLE_MAX_RAM_BYTES,
    };
    let max_vram = match power_state {
        PowerState::Active => ACTIVE_MAX_VRAM_BYTES,
        _ => IDLE_MAX_VRAM_BYTES,
    };

    let suspend_triggered = used_ram >= max_ram
        || used_vram.map_or(false, |v| v >= max_vram)
        || gpu_temp.map_or(false, |t| t >= GPU_THERMAL_LIMIT_CELSIUS);

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
