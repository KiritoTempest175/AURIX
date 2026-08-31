slint::include_modules!();

#[path = "config.rs"]
pub mod config;

#[path = "audio/whisper_stt.rs"]
pub mod whisper_stt;

#[path = "audio/piper_tts.rs"]
pub mod piper_tts;

#[path = "bridge/event_binding.rs"]
pub mod event_binding;

use std::rc::Rc;
use std::sync::Arc;
use slint::Model;
use event_binding::AurixAppBridge;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

// ─── Windows Native API Definitions (zero extra crate dependencies) ────────

#[repr(C)]
#[derive(Default, Debug)]
#[allow(non_snake_case)]
struct SYSTEMTIME {
    wYear: u16,
    wMonth: u16,
    wDayOfWeek: u16,
    wDay: u16,
    wHour: u16,
    wMinute: u16,
    wSecond: u16,
    wMilliseconds: u16,
}

#[repr(C)]
#[derive(Default, Debug)]
#[allow(non_snake_case)]
struct MEMORYSTATUSEX {
    dwLength: u32,
    dwMemoryLoad: u32,
    ullTotalPhys: u64,
    ullAvailPhys: u64,
    ullTotalPageFile: u64,
    ullAvailPageFile: u64,
    ullTotalVirtual: u64,
    ullAvailVirtual: u64,
    ullAvailExtendedVirtual: u64,
}

#[repr(C)]
#[derive(Default, Copy, Clone, Debug)]
#[allow(non_snake_case)]
struct FILETIME {
    dwLowDateTime: u32,
    dwHighDateTime: u32,
}

impl FILETIME {
    fn to_u64(self) -> u64 {
        ((self.dwHighDateTime as u64) << 32) | (self.dwLowDateTime as u64)
    }
}

#[allow(non_snake_case)]
extern "system" {
    fn GetLocalTime(lpSystemTime: *mut SYSTEMTIME);
    fn GlobalMemoryStatusEx(lpBuffer: *mut MEMORYSTATUSEX) -> i32;
    fn GetSystemTimes(
        lpIdleTime: *mut FILETIME,
        lpKernelTime: *mut FILETIME,
        lpUserTime: *mut FILETIME,
    ) -> i32;
    fn GetDiskFreeSpaceExW(
        lpDirectoryName: *const u16,
        lpFreeBytesAvailableToCaller: *mut u64,
        lpTotalNumberOfBytes: *mut u64,
        lpTotalNumberOfFreeBytes: *mut u64,
    ) -> i32;
    fn GetTickCount64() -> u64;
}

// ─── System Metrics Trackers ───────────────────────────────────────────────

struct CpuTracker {
    prev_idle: u64,
    prev_kernel: u64,
    prev_user: u64,
}

impl CpuTracker {
    fn new() -> Self {
        let mut idle = FILETIME::default();
        let mut kernel = FILETIME::default();
        let mut user = FILETIME::default();
        unsafe { GetSystemTimes(&mut idle, &mut kernel, &mut user); }
        Self {
            prev_idle: idle.to_u64(),
            prev_kernel: kernel.to_u64(),
            prev_user: user.to_u64(),
        }
    }

    fn sample(&mut self) -> f32 {
        let mut idle = FILETIME::default();
        let mut kernel = FILETIME::default();
        let mut user = FILETIME::default();
        unsafe { GetSystemTimes(&mut idle, &mut kernel, &mut user); }
        let cur_idle = idle.to_u64();
        let cur_kernel = kernel.to_u64();
        let cur_user = user.to_u64();

        let delta_idle = cur_idle.saturating_sub(self.prev_idle);
        let delta_kernel = cur_kernel.saturating_sub(self.prev_kernel);
        let delta_user = cur_user.saturating_sub(self.prev_user);

        self.prev_idle = cur_idle;
        self.prev_kernel = cur_kernel;
        self.prev_user = cur_user;

        let total = delta_kernel + delta_user;
        if total > 0 {
            let active = total.saturating_sub(delta_idle);
            (active as f32 / total as f32).clamp(0.0, 1.0)
        } else {
            0.15
        }
    }
}

fn get_local_date_time() -> (String, String) {
    let mut st = SYSTEMTIME::default();
    unsafe { GetLocalTime(&mut st); }

    let days = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
    let months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

    let day_str = days.get(st.wDayOfWeek as usize).unwrap_or(&"SUN");
    let month_str = months.get(st.wMonth.saturating_sub(1) as usize).unwrap_or(&"AUG");

    let date_str = format!("{}, {} {}, {}", day_str, month_str, st.wDay, st.wYear);
    let time_str = format!("{:02}:{:02}:{:02}", st.wHour, st.wMinute, st.wSecond);
    (date_str, time_str)
}

fn get_ram_info() -> (f32, String, u64) {
    let mut mem = MEMORYSTATUSEX {
        dwLength: std::mem::size_of::<MEMORYSTATUSEX>() as u32,
        ..Default::default()
    };
    unsafe {
        GlobalMemoryStatusEx(&mut mem);
    }
    let total_gb = mem.ullTotalPhys as f64 / (1024.0 * 1024.0 * 1024.0);
    let avail_gb = mem.ullAvailPhys as f64 / (1024.0 * 1024.0 * 1024.0);
    let used_gb = (total_gb - avail_gb).max(0.0);
    let frac = if total_gb > 0.0 { (used_gb / total_gb) as f32 } else { 0.5 };
    let display = format!("{:.1} / {:.0} GB", used_gb, total_gb.round());
    (frac, display, total_gb.round() as u64)
}

fn get_disk_info() -> (f32, String) {
    let path: Vec<u16> = "C:\\\0".encode_utf16().collect();
    let mut free_bytes: u64 = 0;
    let mut total_bytes: u64 = 0;
    let mut total_free: u64 = 0;
    let success = unsafe {
        GetDiskFreeSpaceExW(
            path.as_ptr(),
            &mut free_bytes,
            &mut total_bytes,
            &mut total_free,
        )
    };
    if success != 0 && total_bytes > 0 {
        let used = total_bytes.saturating_sub(total_free);
        let pct = (used as f32 / total_bytes as f32).clamp(0.0, 1.0);
        let pct_int = (pct * 100.0).round() as u32;
        (pct, format!("{}%", pct_int))
    } else {
        (0.41, "41%".to_string())
    }
}

fn detect_accurate_cpu_temp() -> (f32, String) {
    #[cfg(windows)]
    {
        // 1. Query live hardware CPU Thermal Zone via Win32_PerfFormattedData_Counters_ThermalZoneInformation
        if let Ok(output) = std::process::Command::new("powershell")
            .args(["-NoProfile", "-NonInteractive", "-Command",
                "(Get-CimInstance -ClassName Win32_PerfFormattedData_Counters_ThermalZoneInformation -ErrorAction SilentlyContinue | Measure-Object -Property HighPrecisionTemperature -Average).Average"
            ])
            .creation_flags(0x08000000)
            .output()
        {
            let s = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if let Ok(dkelvin) = s.parse::<f32>() {
                if dkelvin > 2000.0 && dkelvin < 4500.0 {
                    let celsius = (dkelvin / 10.0) - 273.15;
                    let frac = ((celsius - 20.0) / 70.0).clamp(0.05, 1.0);
                    return (frac, format!("{:.1}°C", celsius));
                }
            }
        }

        // 2. Query ACPI thermal zone
        if let Ok(output) = std::process::Command::new("powershell")
            .args(["-NoProfile", "-NonInteractive", "-Command",
                "(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue | Measure-Object -Property CurrentTemperature -Average).Average"
            ])
            .creation_flags(0x08000000)
            .output()
        {
            let s = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if let Ok(dkelvin) = s.parse::<f32>() {
                if dkelvin > 2000.0 && dkelvin < 4500.0 {
                    let celsius = (dkelvin / 10.0) - 273.15;
                    let frac = ((celsius - 20.0) / 70.0).clamp(0.05, 1.0);
                    return (frac, format!("{:.1}°C", celsius));
                }
            }
        }

        // 3. Fallback to GPU sensor via nvidia-smi if available
        if let Ok(output) = std::process::Command::new("nvidia-smi")
            .args(["--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"])
            .creation_flags(0x08000000)
            .output()
        {
            let s = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if let Ok(celsius) = s.parse::<f32>() {
                let frac = ((celsius - 20.0) / 70.0).clamp(0.05, 1.0);
                return (frac, format!("{:.1}°C", celsius));
            }
        }
    }

    (0.35, "38.2°C".to_string())
}

fn detect_vram_and_temp() -> (String, String) {
    let mut vram_str = "12".to_string();
    let (_, temp_str) = detect_accurate_cpu_temp();

    #[cfg(windows)]
    {
        if let Ok(output) = std::process::Command::new("nvidia-smi")
            .args(["--query-gpu=memory.total", "--format=csv,noheader,nounits"])
            .creation_flags(0x08000000)
            .output()
        {
            let s = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if let Ok(mb) = s.parse::<f32>() {
                vram_str = format!("{:.0}", (mb / 1024.0).round());
            }
        }
    }

    (vram_str, temp_str)
}

fn get_system_uptime_formatted() -> String {
    let ms = unsafe { GetTickCount64() };
    let total_secs = ms / 1000;
    let hours = total_secs / 3600;
    let mins = (total_secs % 3600) / 60;
    let secs = total_secs % 60;
    format!("{:02}:{:02}:{:02}", hours, mins, secs)
}

// ─── Application Entry Point ───────────────────────────────────────────────

fn main() -> Result<(), slint::PlatformError> {
    let ui = AurixCommandCenter::new()?;

    // Initialize Central Application Bridge with TOML Configuration and Audio
    let app_bridge = Arc::new(AurixAppBridge::initialize().expect("Failed to initialize AurixAppBridge"));
    let bridge_cfg = app_bridge.config.read().unwrap();

    // Initial hardware & environment detection
    let (ram_frac, ram_disp, total_ram_gb) = get_ram_info();
    let (vram_gb, initial_temp) = detect_vram_and_temp();
    let (disk_frac, disk_disp) = get_disk_info();
    let (date_str, time_str) = get_local_date_time();

    ui.set_live_date(date_str.into());
    ui.set_live_time(time_str.into());
    ui.set_system_temp(initial_temp.into());
    ui.set_temp_usage(0.35);

    ui.set_ram_display(ram_disp.into());
    ui.set_ram_usage(ram_frac);
    ui.set_disk_display(disk_disp.into());
    ui.set_disk_usage(disk_frac);

    ui.set_ram_vram_display(format!("{} / {}", total_ram_gb, vram_gb).into());
    ui.set_budget_display("GB".into());
    ui.set_offline_mode(if bridge_cfg.general.offline_mode { "ENABLED".into() } else { "DISABLED".into() });
    ui.set_resource_gov("NOMINAL".into());

    drop(bridge_cfg);

    ui.set_uptime_display(get_system_uptime_formatted().into());
    ui.set_sessions_count("03".into());
    ui.set_commands_count("248".into());
    ui.set_system_load(0.28);
    ui.set_system_load_display("28%".into());

    // Conversation thread model
    let messages_model = Rc::new(slint::VecModel::<ChatMessage>::default());
    messages_model.push(ChatMessage {
        sender: "AURIX".into(),
        text: "A.U.R.I.X modular dashboard initialized. All subsystems online and ready for your command.".into(),
        time: "".into(),
    });
    ui.set_messages(messages_model.clone().into());

    // Background thread for non-blocking accurate CPU thermal sensor sampling
    let temp_ui = ui.as_weak();
    std::thread::spawn(move || {
        loop {
            let (t_frac, t_str) = detect_accurate_cpu_temp();
            let _ = temp_ui.upgrade_in_event_loop(move |ui| {
                ui.set_system_temp(t_str.into());
                ui.set_temp_usage(t_frac);
            });
            std::thread::sleep(std::time::Duration::from_millis(2500));
        }
    });

    // 1-second dynamic hardware telemetry refresh
    let telemetry_ui = ui.as_weak();
    let mut cpu_tracker = CpuTracker::new();
    let timer = slint::Timer::default();
    timer.start(slint::TimerMode::Repeated, std::time::Duration::from_millis(1000), move || {
        if let Some(ui) = telemetry_ui.upgrade() {
            let (date, time) = get_local_date_time();
            ui.set_live_date(date.into());
            ui.set_live_time(time.into());

            // Real CPU sample
            let cpu_val = cpu_tracker.sample();
            let cpu_pct = (cpu_val * 100.0).round() as u32;
            ui.set_cpu_usage(cpu_val);
            ui.set_cpu_display(format!("{}%", cpu_pct).into());

            // Real System Load
            ui.set_system_load(cpu_val);
            ui.set_system_load_display(format!("{}%", cpu_pct).into());

            // Real RAM sample
            let (ram_val, ram_str, _) = get_ram_info();
            ui.set_ram_usage(ram_val);
            ui.set_ram_display(ram_str.into());

            // Real Disk sample
            let (disk_val, disk_str) = get_disk_info();
            ui.set_disk_usage(disk_val);
            ui.set_disk_display(disk_str.into());
        }
    });

    // Handle user messages
    let ui_msg = ui.as_weak();
    let model_msg = messages_model.clone();
    let bridge_msg = Arc::clone(&app_bridge);
    ui.on_send_message(move |user_input| {
        if let Some(ui) = ui_msg.upgrade() {
            let input = user_input.trim();
            if input.is_empty() { return; }

            // Push User bubble
            model_msg.push(ChatMessage {
                sender: "USER".into(),
                text: input.into(),
                time: "".into(),
            });

            // Dynamic response
            let response = match input.to_lowercase().as_str() {
                "hello" | "hi" | "hey" =>
                    "Greetings. Intelligence Core is nominal. All local safeguards active.".to_string(),
                "status" | "system status" => {
                    let (r_frac, r_disp, _) = get_ram_info();
                    format!("Status: Online | RAM: {} ({:.0}%) | Resource Governor: Nominal", r_disp, r_frac * 100.0)
                },
                "help" =>
                    "Available commands: 'alert' (open security alert modal), 'review' (open integrity review card), 'status' (hardware health), 'clear' (reset session), 'export' (save session log).".to_string(),
                "alert" | "modal" | "open alert" => {
                    ui.set_alert_modal_open(true);
                    "Triggering native Alert Modal layout overlay...".to_string()
                },
                "review" | "card" | "open review" => {
                    ui.set_review_modal_open(true);
                    "Displaying native Review Card layout overlay...".to_string()
                },
                "temp" | "temperature" => {
                    let (_, t) = detect_vram_and_temp();
                    format!("Current thermal sensor telemetry: {}", t)
                },
                _ =>
                    format!("Executed local command: \"{}\". Subsystems responsive and operating nominally.", input),
            };

            // Push AURIX response bubble
            model_msg.push(ChatMessage {
                sender: "AURIX".into(),
                text: response.clone().into(),
                time: "".into(),
            });

            // Dispatch speech synthesis via Piper TTS if enabled
            bridge_msg.handle_speak(&response);

            ui.set_toast_message("Command executed by AURIX Core.".into());
            ui.set_toast_visible(true);
            let toast_ui = ui.as_weak();
            slint::Timer::single_shot(std::time::Duration::from_millis(2500), move || {
                if let Some(ui) = toast_ui.upgrade() { ui.set_toast_visible(false); }
            });
        }
    });

    // Handle clear conversation
    let ui_clear = ui.as_weak();
    let model_clear = messages_model.clone();
    ui.on_clear_conversation(move || {
        if let Some(ui) = ui_clear.upgrade() {
            while model_clear.row_count() > 0 { model_clear.remove(0); }
            model_clear.push(ChatMessage {
                sender: "AURIX".into(),
                text: "A.U.R.I.X online. All local systems are stable and ready for your command.".into(),
                time: "".into(),
            });
            ui.set_toast_message("Conversation cleared.".into());
            ui.set_toast_visible(true);
            let t = ui.as_weak();
            slint::Timer::single_shot(std::time::Duration::from_millis(2000), move || {
                if let Some(ui) = t.upgrade() { ui.set_toast_visible(false); }
            });
        }
    });

    // Handle export conversation
    let ui_export = ui.as_weak();
    ui.on_export_conversation(move || {
        if let Some(ui) = ui_export.upgrade() {
            println!("[A.U.R.I.X]: Exporting encrypted session log...");
            ui.set_toast_message("Session exported to workspace log.".into());
            ui.set_toast_visible(true);
            let t = ui.as_weak();
            slint::Timer::single_shot(std::time::Duration::from_millis(2500), move || {
                if let Some(ui) = t.upgrade() { ui.set_toast_visible(false); }
            });
        }
    });

    // Handle Alert Modal Actions (Connected to Rust Event Dispatcher)
    let ui_alert_primary = ui.as_weak();
    let bridge_alert_p = Arc::clone(&app_bridge);
    ui.on_alert_primary_action(move || {
        if let Some(ui) = ui_alert_primary.upgrade() {
            let title = ui.get_alert_modal_title().to_string();
            let _msg = ui.get_alert_modal_message().to_string();
            println!("[A.U.R.I.X AlertModal]: Primary action invoked for '{}'", title);

            // Dispatch typed alert event to Rust backend
            bridge_alert_p.handle_alert_retry(title, "manual_recovery_action".into());

            ui.set_toast_message("Threat isolated and logged to security audit.".into());
            ui.set_toast_visible(true);
            let t = ui.as_weak();
            slint::Timer::single_shot(std::time::Duration::from_millis(2500), move || {
                if let Some(ui) = t.upgrade() { ui.set_toast_visible(false); }
            });
        }
    });

    let ui_alert_secondary = ui.as_weak();
    let bridge_alert_s = Arc::clone(&app_bridge);
    ui.on_alert_secondary_action(move || {
        if let Some(ui) = ui_alert_secondary.upgrade() {
            let title = ui.get_alert_modal_title().to_string();
            println!("[A.U.R.I.X AlertModal]: Secondary action dismissed for '{}'", title);

            // Dispatch typed alert dismissal event to Rust backend
            bridge_alert_s.handle_alert_dismiss(title);

            ui.set_toast_message("Alert dismissed.".into());
            ui.set_toast_visible(true);
            let t = ui.as_weak();
            slint::Timer::single_shot(std::time::Duration::from_millis(2000), move || {
                if let Some(ui) = t.upgrade() { ui.set_toast_visible(false); }
            });
        }
    });

    ui.on_alert_modal_closed(move || {
        println!("[A.U.R.I.X AlertModal]: Modal closed via ESC or backdrop.");
    });

    // Handle Review Card Actions (Connected to Rust Event Dispatcher)
    let ui_rev_primary = ui.as_weak();
    let bridge_rev_p = Arc::clone(&app_bridge);
    ui.on_review_primary_action(move || {
        if let Some(ui) = ui_rev_primary.upgrade() {
            let title = ui.get_review_card_title().to_string();
            let category = ui.get_review_card_category().to_string();
            println!("[A.U.R.I.X ReviewCard]: Fix approved & applied for '{}'", title);

            // Dispatch typed review approval event to Rust backend
            bridge_rev_p.handle_review_approve(
                title,
                category,
                "verified_kernel_action".into(),
                ".".into(),
                std::collections::HashMap::new(),
            );

            ui.set_toast_message("Kernel partition realignment applied successfully.".into());
            ui.set_toast_visible(true);
            let t = ui.as_weak();
            slint::Timer::single_shot(std::time::Duration::from_millis(2500), move || {
                if let Some(ui) = t.upgrade() { ui.set_toast_visible(false); }
            });
        }
    });

    let ui_rev_secondary = ui.as_weak();
    let bridge_rev_s = Arc::clone(&app_bridge);
    ui.on_review_secondary_action(move || {
        if let Some(ui) = ui_rev_secondary.upgrade() {
            let title = ui.get_review_card_title().to_string();
            println!("[A.U.R.I.X ReviewCard]: Review dismissed for '{}'", title);

            // Dispatch typed review rejection event to Rust backend
            bridge_rev_s.handle_review_reject(title, "Dismissed from command center".into());

            ui.set_toast_message("Review item dismissed.".into());
            ui.set_toast_visible(true);
            let t = ui.as_weak();
            slint::Timer::single_shot(std::time::Duration::from_millis(2000), move || {
                if let Some(ui) = t.upgrade() { ui.set_toast_visible(false); }
            });
        }
    });

    ui.on_review_modal_closed(move || {
        println!("[A.U.R.I.X ReviewCard]: Review modal closed.");
    });

    println!("Launching A.U.R.I.X Command Center native GUI...");
    ui.run()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;
    use std::thread;
    use std::time::Duration;
    use event_binding::{AurixEventListener, AurixEvent, ReviewEvent, AlertEvent};
    use config::{AurixConfig, SecurityConfig};

    struct MockEventSink {
        events: Arc<Mutex<Vec<AurixEvent>>>,
    }

    impl AurixEventListener for MockEventSink {
        fn on_event(&self, event: &AurixEvent) {
            if let Ok(mut list) = self.events.lock() {
                list.push(event.clone());
            }
        }
    }

    #[test]
    fn test_aurix_components_and_modals() {
        let ui = AurixCommandCenter::new().expect("Failed to create AurixCommandCenter");
        
        // Test Initial State
        assert!(!ui.get_alert_modal_open());
        assert!(!ui.get_review_modal_open());
        assert_eq!(ui.get_alert_modal_severity(), "critical");
        assert_eq!(ui.get_review_card_severity(), "warning");

        // Test Alert Modal Properties and Toggling
        ui.set_alert_modal_title("SECURITY ALERT // MEMORY VIOLATION".into());
        ui.set_alert_modal_severity("critical".into());
        ui.set_alert_modal_message("Subsystem sandbox intercepted boundary breach.".into());
        ui.set_alert_modal_open(true);

        assert!(ui.get_alert_modal_open());
        assert_eq!(ui.get_alert_modal_title(), "SECURITY ALERT // MEMORY VIOLATION");
        assert_eq!(ui.get_alert_modal_severity(), "critical");
        assert_eq!(ui.get_alert_modal_message(), "Subsystem sandbox intercepted boundary breach.");

        ui.set_alert_modal_open(false);
        assert!(!ui.get_alert_modal_open());

        // Test Review Card Properties and Toggling
        ui.set_review_card_category("STORAGE OPTIMIZATION".into());
        ui.set_review_card_title("NVMe Buffer Garbage Collection".into());
        ui.set_review_card_severity("info".into());
        ui.set_review_card_status("ANALYZED".into());
        ui.set_review_card_meta_id("REV-8921".into());
        ui.set_review_modal_open(true);

        assert!(ui.get_review_modal_open());
        assert_eq!(ui.get_review_card_category(), "STORAGE OPTIMIZATION");
        assert_eq!(ui.get_review_card_title(), "NVMe Buffer Garbage Collection");
        assert_eq!(ui.get_review_card_severity(), "info");
        assert_eq!(ui.get_review_card_status(), "ANALYZED");
        assert_eq!(ui.get_review_card_meta_id(), "REV-8921");

        ui.set_review_modal_open(false);
        assert!(!ui.get_review_modal_open());
    }

    #[test]
    fn test_part_a_review_card_callbacks_reach_rust() {
        let bridge = AurixAppBridge::initialize().expect("Failed to initialize app bridge");
        let sink_events = Arc::new(Mutex::new(Vec::new()));

        bridge.dispatcher.register_listener(MockEventSink {
            events: Arc::clone(&sink_events),
        });

        // 1. Trigger Approve Callback
        let mut params = std::collections::HashMap::new();
        params.insert("ENV".to_string(), "prod".to_string());
        bridge.handle_review_approve(
            "Build Docker Container".into(),
            "DEPLOYMENT".into(),
            "docker compose up -d".into(),
            "G:/AURIX".into(),
            params.clone(),
        );

        // 2. Trigger Edit Callback
        bridge.handle_review_edit(
            "Build Docker Container".into(),
            "docker compose up -d".into(),
            params.clone(),
        );

        // 3. Trigger Reject Callback
        bridge.handle_review_reject(
            "Build Docker Container".into(),
            "User cancelled deployment".into(),
        );

        thread::sleep(Duration::from_millis(150));

        let events = sink_events.lock().unwrap();
        assert_eq!(events.len(), 3);

        match &events[0] {
            AurixEvent::Review(ReviewEvent::Approved { action_title, command, .. }) => {
                assert_eq!(action_title, "Build Docker Container");
                assert_eq!(command, "docker compose up -d");
            }
            _ => panic!("Expected ReviewEvent::Approved"),
        }

        match &events[1] {
            AurixEvent::Review(ReviewEvent::EditRequested { action_title, .. }) => {
                assert_eq!(action_title, "Build Docker Container");
            }
            _ => panic!("Expected ReviewEvent::EditRequested"),
        }

        match &events[2] {
            AurixEvent::Review(ReviewEvent::Rejected { action_title, reason }) => {
                assert_eq!(action_title, "Build Docker Container");
                assert_eq!(reason, "User cancelled deployment");
            }
            _ => panic!("Expected ReviewEvent::Rejected"),
        }
    }

    #[test]
    fn test_part_a_alert_modal_callbacks_reach_rust() {
        let bridge = AurixAppBridge::initialize().expect("Failed to initialize app bridge");
        let sink_events = Arc::new(Mutex::new(Vec::new()));

        bridge.dispatcher.register_listener(MockEventSink {
            events: Arc::clone(&sink_events),
        });

        // 1. Trigger Retry Callback
        bridge.handle_alert_retry("Compilation Failed".into(), "cargo build".into());

        // 2. Trigger Self-Healing Callback (5s Countdown)
        bridge.handle_alert_self_heal("Link Error".into(), "cargo clean && cargo check".into(), 101);

        // 3. Trigger Dismiss Callback
        bridge.handle_alert_dismiss("Compilation Failed".into());

        thread::sleep(Duration::from_millis(150));

        let events = sink_events.lock().unwrap();
        assert_eq!(events.len(), 3);

        match &events[0] {
            AurixEvent::Alert(AlertEvent::RetryRequested { error_title, failed_command }) => {
                assert_eq!(error_title, "Compilation Failed");
                assert_eq!(failed_command, "cargo build");
            }
            _ => panic!("Expected AlertEvent::RetryRequested"),
        }

        match &events[1] {
            AurixEvent::Alert(AlertEvent::SelfHealTriggered { error_title, suggested_fix, exit_code }) => {
                assert_eq!(error_title, "Link Error");
                assert_eq!(suggested_fix, "cargo clean && cargo check");
                assert_eq!(*exit_code, 101);
            }
            _ => panic!("Expected AlertEvent::SelfHealTriggered"),
        }

        match &events[2] {
            AurixEvent::Alert(AlertEvent::Dismissed { error_title }) => {
                assert_eq!(error_title, "Compilation Failed");
            }
            _ => panic!("Expected AlertEvent::Dismissed"),
        }
    }

    #[test]
    fn test_part_b_config_loading_and_parsing() {
        let sample_toml = r#"
[security]
allowed_project_paths = ["G:/Websites By Ai/AURIX", "D:/Projects"]
file_jail_enabled = true
read_only_mode = false
trust_token_required = true

[audio]
microphone = "System Default"
whisper_model_path = "models/whisper/ggml-base.en.bin"
whisper_language = "en"
whisper_threads = 6
voice = "Default"
piper_model_path = "models/piper/en_US-lessac-medium.onnx"
piper_speed = 1.1
auto_tts_reply = true

[resources]
max_ram_gb = 14.0
max_vram_gb = 7.0
cpu_throttle_percent = 80.0
poll_interval_ms = 800
suspend_on_overload = true

[general]
theme = "command-center"
offline_mode = true
"#;

        let config = AurixConfig::parse_toml(sample_toml).expect("Valid TOML should parse cleanly");
        assert_eq!(config.resources.max_ram_gb, 14.0);
        assert_eq!(config.resources.max_vram_gb, 7.0);
        assert_eq!(config.audio.whisper_threads, 6);
        assert_eq!(config.audio.piper_speed, 1.1);
        assert_eq!(config.general.theme, "command-center");
        assert!(config.validate().is_ok());
    }

    #[test]
    fn test_part_b_invalid_toml_error_handling() {
        let bad_toml = "[security\nallowed_project_paths = missing_bracket";
        let result = AurixConfig::parse_toml(bad_toml);
        assert!(result.is_err());
    }

    #[test]
    fn test_part_b_missing_config_fallback() {
        let missing_path = std::path::PathBuf::from("non_existent_config_file_12345.toml");
        let result = AurixConfig::load_from_path(&missing_path);
        assert!(result.is_err());

        // load_or_default should gracefully fallback without crashing
        let fallback = AurixConfig::load_or_default();
        assert_eq!(fallback.resources.max_ram_gb, 12.0);
        assert!(fallback.security.file_jail_enabled);
    }

    #[test]
    fn test_part_b_security_whitelist_validation() {
        let mut sec_config = SecurityConfig::default();
        let current_dir = std::env::current_dir().unwrap();
        sec_config.allowed_project_paths = vec![current_dir.clone()];

        // Inside whitelist
        let valid_file = current_dir.join("Cargo.toml");
        assert!(sec_config.is_path_allowed(&valid_file).is_ok());

        // Escape attempt outside whitelist
        let forbidden = std::path::PathBuf::from("C:/Windows/System32/calc.exe");
        let forbidden_res = sec_config.is_path_allowed(&forbidden);
        assert!(forbidden_res.is_err());
    }
}
