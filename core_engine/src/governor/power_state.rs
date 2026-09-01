// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/governor/power_state.rs
// ─────────────────────────────────────────────────────────────────────────────
// LUNA Adaptive Power Governor v2 — State Definitions and Atomic Signaling.
//
// States:
//   0 = Active     (User is interacting; conservative ceilings, inference prioritized)
//   1 = Idle       (User away > 5m; boosted ceilings, increased LoRA rank)
//   2 = Locked     (Screen/Session locked; full training up to safe hardware limits)
//   3 = Suspending (OS shutdown/sleep signal; emergency checkpoint & clean exit)
// ─────────────────────────────────────────────────────────────────────────────

use pyo3::prelude::*;
use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};
use std::sync::Arc;

/// Power state enum representing LUNA system execution mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum PowerState {
    Active = 0,
    Idle = 1,
    Locked = 2,
    Suspending = 3,
}

impl PowerState {
    pub fn from_u8(val: u8) -> Self {
        match val {
            1 => PowerState::Idle,
            2 => PowerState::Locked,
            3 => PowerState::Suspending,
            _ => PowerState::Active,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            PowerState::Active => "ACTIVE",
            PowerState::Idle => "IDLE",
            PowerState::Locked => "LOCKED",
            PowerState::Suspending => "SUSPENDING",
        }
    }
}

// Global atomic flags for zero-cost polling across threads
static GLOBAL_POWER_STATE: AtomicU8 = AtomicU8::new(PowerState::Active as u8);
static GLOBAL_SUSPEND_FLAG: AtomicBool = AtomicBool::new(false);

/// Update global power state.
pub fn set_power_state(state: PowerState) {
    GLOBAL_POWER_STATE.store(state as u8, Ordering::SeqCst);
}

/// Read global power state.
pub fn get_power_state() -> PowerState {
    PowerState::from_u8(GLOBAL_POWER_STATE.load(Ordering::SeqCst))
}

/// Set global workload suspension flag.
pub fn set_suspend_flag(suspend: bool) {
    GLOBAL_SUSPEND_FLAG.store(suspend, Ordering::SeqCst);
}

/// Read global workload suspension flag.
pub fn get_suspend_flag() -> bool {
    GLOBAL_SUSPEND_FLAG.load(Ordering::SeqCst)
}

// ─── PyO3 Class Export ────────────────────────────────────────────────────────

/// System state manager exposed to Python for querying and controlling power states.
#[pyclass]
#[derive(Clone)]
pub struct SystemState {
    power_state: Arc<AtomicU8>,
    is_suspended: Arc<AtomicBool>,
}

#[pymethods]
impl SystemState {
    #[new]
    pub fn new() -> Self {
        set_power_state(PowerState::Active);
        set_suspend_flag(false);
        SystemState {
            power_state: Arc::new(AtomicU8::new(PowerState::Active as u8)),
            is_suspended: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Return integer code of current power state (0=Active, 1=Idle, 2=Locked, 3=Suspending).
    pub fn get_power_state(&self) -> u8 {
        GLOBAL_POWER_STATE.load(Ordering::SeqCst)
    }

    /// Return string name of current power state.
    pub fn get_power_state_name(&self) -> String {
        get_power_state().as_str().to_string()
    }

    /// Set power state from Python.
    pub fn set_power_state(&self, state_val: u8) {
        let state = PowerState::from_u8(state_val);
        self.power_state.store(state as u8, Ordering::SeqCst);
        set_power_state(state);
    }

    /// Check if AI workload is currently suspended due to resource limits.
    pub fn check_suspended(&self) -> bool {
        GLOBAL_SUSPEND_FLAG.load(Ordering::SeqCst)
    }

    /// Request suspension of AI workload.
    pub fn pause(&self) {
        self.is_suspended.store(true, Ordering::SeqCst);
        set_suspend_flag(true);
    }

    /// Resume AI workload execution.
    pub fn resume(&self) {
        self.is_suspended.store(false, Ordering::SeqCst);
        set_suspend_flag(false);
    }

    /// Check if system is currently in idle or locked mode (favorable for background training).
    pub fn is_idle_or_locked(&self) -> bool {
        let st = get_power_state();
        st == PowerState::Idle || st == PowerState::Locked
    }

    /// Check if system is receiving shutdown/hibernate signal.
    pub fn is_suspending(&self) -> bool {
        get_power_state() == PowerState::Suspending
    }

    fn __repr__(&self) -> String {
        format!(
            "SystemState(power_state={}, is_suspended={})",
            self.get_power_state_name(),
            self.check_suspended()
        )
    }
}

impl SystemState {
    /// Create a clone sharing the same underlying atomic state Arc pointers.
    pub fn shared_clone(&self) -> Self {
        self.clone()
    }
}

impl Default for SystemState {
    fn default() -> Self {
        Self::new()
    }
}
