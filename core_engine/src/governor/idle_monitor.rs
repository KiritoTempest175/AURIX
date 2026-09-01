// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/governor/idle_monitor.rs
// ─────────────────────────────────────────────────────────────────────────────
// LUNA Idle and Session Lock Monitor.
//
// Uses the Windows API (GetLastInputInfo + GetTickCount64 / WTSRegisterSessionNotification)
// behind a clean, testable `IdleMonitor` trait.
//
// NOTE: Lock Detection Architecture Decision:
// The legacy foreground-window heuristic (`GetForegroundWindow() == NULL`) was replaced
// with native Windows Terminal Services session notifications (`WTSRegisterSessionNotification`)
// registered against a hidden message-only window (`HWND_MESSAGE`). The legacy heuristic
// was prone to both false-positives (desktop workspace transitions, fullscreen/exclusive games)
// and false-negatives (LogonUI window handle actively present during lock screen).
// Because `PowerState::Locked` triggers full-throttle unthrottled background AI training,
// rock-solid session lock tracking via `WM_WTSSESSION_CHANGE` is strictly required.
// ─────────────────────────────────────────────────────────────────────────────

use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Instant;

/// Global atomic tracking user session lock state.
static SESSION_LOCKED: AtomicBool = AtomicBool::new(false);

/// Trait abstracting OS-level user activity and session lock detection.
pub trait IdleMonitor: Send + Sync {
    /// Returns elapsed time in seconds since the last keyboard or mouse input.
    fn get_idle_seconds(&self) -> u64;

    /// Returns true if the user session or screen is currently locked.
    fn is_screen_locked(&self) -> bool;
}

#[cfg(windows)]
pub struct WindowsIdleMonitor {
    hwnd: isize,
    thread_handle: Option<std::thread::JoinHandle<()>>,
}


#[cfg(windows)]
impl WindowsIdleMonitor {
    pub fn new() -> Self {
        use std::sync::mpsc::channel;

        let (tx, rx) = channel();
        let thread_handle = std::thread::Builder::new()
            .name("luna-session-lock-listener".to_string())
            .spawn(move || unsafe {
                use windows_sys::Win32::Foundation::*;
                use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
                use windows_sys::Win32::System::RemoteDesktop::{
                    WTSRegisterSessionNotification, WTSUnRegisterSessionNotification,
                    NOTIFY_FOR_THIS_SESSION,
                };
                use windows_sys::Win32::UI::WindowsAndMessaging::*;

                unsafe extern "system" fn session_wnd_proc(
                    hwnd: HWND,
                    msg: u32,
                    wparam: WPARAM,
                    lparam: LPARAM,
                ) -> LRESULT {
                    match msg {
                        WM_WTSSESSION_CHANGE => {
                            if wparam == 7usize {
                                SESSION_LOCKED.store(true, Ordering::SeqCst);
                            } else if wparam == 8usize {
                                SESSION_LOCKED.store(false, Ordering::SeqCst);
                            }
                            0
                        }
                        WM_CLOSE => {
                            DestroyWindow(hwnd);
                            0
                        }
                        WM_DESTROY => {
                            WTSUnRegisterSessionNotification(hwnd);
                            PostQuitMessage(0);
                            0
                        }
                        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
                    }
                }

                let class_name: Vec<u16> = "LUNA_Session_Monitor_Class\0".encode_utf16().collect();
                let hinstance = GetModuleHandleW(std::ptr::null());
                let wc = WNDCLASSW {
                    style: 0,
                    lpfnWndProc: Some(session_wnd_proc),
                    cbClsExtra: 0,
                    cbWndExtra: 0,
                    hInstance: hinstance,
                    hIcon: 0,
                    hCursor: 0,
                    hbrBackground: 0,
                    lpszMenuName: std::ptr::null(),
                    lpszClassName: class_name.as_ptr(),
                };
                RegisterClassW(&wc);

                let hwnd = CreateWindowExW(
                    0,
                    class_name.as_ptr(),
                    std::ptr::null(),
                    0,
                    0,
                    0,
                    0,
                    0,
                    HWND_MESSAGE,
                    0,
                    hinstance,
                    std::ptr::null(),
                );

                if hwnd != 0 {
                    WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION);
                }

                let _ = tx.send(hwnd);

                let mut msg: MSG = std::mem::zeroed();
                while GetMessageW(&mut msg, 0, 0, 0) > 0 {
                    TranslateMessage(&msg);
                    DispatchMessageW(&msg);
                }
            })
            .ok();

        let hwnd = rx.recv().unwrap_or(0);

        WindowsIdleMonitor {
            hwnd,
            thread_handle,
        }
    }
}

#[cfg(windows)]
impl Drop for WindowsIdleMonitor {
    fn drop(&mut self) {
        if self.hwnd != 0 {
            unsafe {
                use windows_sys::Win32::UI::WindowsAndMessaging::{PostMessageW, WM_CLOSE};
                PostMessageW(self.hwnd, WM_CLOSE, 0, 0);
            }
        }
        if let Some(handle) = self.thread_handle.take() {
            let _ = handle.join();
        }
    }
}

#[cfg(windows)]
impl Default for WindowsIdleMonitor {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(windows)]
impl IdleMonitor for WindowsIdleMonitor {
    fn get_idle_seconds(&self) -> u64 {
        use windows_sys::Win32::System::SystemInformation::GetTickCount64;
        use windows_sys::Win32::UI::Input::KeyboardAndMouse::{GetLastInputInfo, LASTINPUTINFO};

        unsafe {
            let mut lii = LASTINPUTINFO {
                cbSize: std::mem::size_of::<LASTINPUTINFO>() as u32,
                dwTime: 0,
            };

            if GetLastInputInfo(&mut lii) != 0 {
                let current_tick = GetTickCount64();
                return current_tick.saturating_sub(lii.dwTime as u64) / 1000;
            }
        }
        0
    }

    fn is_screen_locked(&self) -> bool {
        SESSION_LOCKED.load(Ordering::SeqCst)
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
