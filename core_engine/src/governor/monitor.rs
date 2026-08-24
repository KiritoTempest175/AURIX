use pyo3::prelude::*;
use std::thread;
use std::time::Duration;
use sysinfo::System;
use nvml_wrapper::Nvml;
use crate::governor::atomic_state::set_suspend_flag;

/// Hardware Resource Governor Limits
/// As per Architecture Blueprint v2.0
const MAX_RAM_BYTES: u64 = 12 * 1024 * 1024 * 1024; // 12GB Hard Ceiling
const MAX_VRAM_BYTES: u64 = 6 * 1024 * 1024 * 1024; // 6GB Hard Stop

/// Starts a background thread to monitor system hardware resources.
/// 
/// This function uses `sysinfo` to track host RAM and `nvml-wrapper` to track VRAM.
/// If either metric exceeds the defined maximums, it flags the atomic state 
/// to suspend the Python QLoRA training loop, ensuring zero multitasking degradation.
#[pyfunction]
pub fn start_hardware_monitor() {
    thread::spawn(move || {
        let mut sys = System::new_all();
        
        // Attempt to initialize NVML for GPU monitoring.
        // We handle the Result gracefully because some systems might not have NVIDIA GPUs.
        let nvml_opt = Nvml::init().ok();

        loop {
            // Refresh RAM data
            sys.refresh_memory();
            let used_ram = sys.used_memory();

            let mut suspend_needed = false;

            if used_ram >= MAX_RAM_BYTES {
                suspend_needed = true;
            }

            // Check VRAM if NVML initialized successfully
            if let Some(ref nvml) = nvml_opt {
                // Assuming we monitor the first device (index 0)
                if let Ok(device) = nvml.device_by_index(0) {
                    if let Ok(memory_info) = device.memory_info() {
                        if memory_info.used >= MAX_VRAM_BYTES {
                            suspend_needed = true;
                        }
                    }
                }
            }

            // Update the atomic state based on current metrics
            set_suspend_flag(suspend_needed);

            // Sleep for 500ms before next poll to avoid high CPU overhead
            thread::sleep(Duration::from_millis(500));
        }
    });
}
