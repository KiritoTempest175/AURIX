// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/governor/idle_monitor.rs
// ─────────────────────────────────────────────────────────────────────────────
// LUNA Idle and Session Lock Monitor.
//
// Uses the Windows API (GetLastInputInfo / workstation lock detection)
// behind a clean, testable `IdleMonitor` trait.
// ─────────────────────────────────────────────────────────────────────────────

use std::time::Instant;

/// Trait abstracting OS-level user activity and session lock detection.
pub trait IdleMonitor: Send + Sync {
    /// Returns elapsed time in seconds since the last keyboard or mouse input.
    fn get_idle_seconds(&self) -> u64;

    /// Returns true if the user session or screen is currently locked.
    fn is_screen_locked(&self) -> bool;
}

#[cfg(windows)]
pub struct WindowsIdleMonitor;

#[cfg(windows)]
impl WindowsIdleMonitor {
    pub fn new() -> Self {
        WindowsIdleMonitor
    }
}

#[cfg(windows)]
impl IdleMonitor for WindowsIdleMonitor {
    fn get_idle_seconds(&self) -> u64 {
        use windows_sys::Win32::System::SystemInformation::GetTickCount;
        use windows_sys::Win32::UI::Input::KeyboardAndMouse::{GetLastInputInfo, LASTINPUTINFO};

        unsafe {
            let mut lii = LASTINPUTINFO {
                cbSize: std::mem::size_of::<LASTINPUTINFO>() as u32,
                dwTime: 0,
            };

            if GetLastInputInfo(&mut lii) != 0 {
                let current_tick = GetTickCount();
                if current_tick >= lii.dwTime {
                    return ((current_tick - lii.dwTime) / 1000) as u64;
                }
            }
        }
        0
    }

    fn is_screen_locked(&self) -> bool {
        use windows_sys::Win32::UI::WindowsAndMessaging::GetForegroundWindow;

        unsafe {
            // When Windows is locked (Win+L / UAC secure desktop / screensaver),
            // GetForegroundWindow returns NULL (0)
            let hwnd = GetForegroundWindow();
            hwnd == 0
        }
    }
}

/// Fallback monitor for testing or non-Windows environments.
pub struct FallbackIdleMonitor {
    _start_time: Instant,
}

impl FallbackIdleMonitor {
    pub fn new() -> Self {
        FallbackIdleMonitor {
            _start_time: Instant::now(),
        }
    }
}

impl IdleMonitor for FallbackIdleMonitor {
    fn get_idle_seconds(&self) -> u64 {
        0
    }

    fn is_screen_locked(&self) -> bool {
        false
    }
}

/// Factory function to return platform-appropriate IdleMonitor.
pub fn create_idle_monitor() -> Box<dyn IdleMonitor> {
    #[cfg(windows)]
    {
        Box::new(WindowsIdleMonitor::new())
    }
    #[cfg(not(windows))]
    {
        Box::new(FallbackIdleMonitor::new())
    }
}
