// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/governor/atomic_state.rs
// ─────────────────────────────────────────────────────────────────────────────
// Thread-safe state flags for cross-runtime signaling between the Rust
// hardware governor and the Python QLoRA training loop.
//
// Architecture: The `SystemState` struct wraps an `Arc<AtomicBool>` so that
// clones of the struct share the same underlying flag. This allows the Rust
// monitor thread to call `pause()` while the Python side independently polls
// `check_suspended()` — all without locks, GIL contention, or IPC sockets.
//
// Blueprint invariant: Zero network sockets. All communication is in-process
// via shared atomic memory.
// ─────────────────────────────────────────────────────────────────────────────

use pyo3::prelude::*;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

// ─── Global Static Flag ─────────────────────────────────────────────────────
// A process-wide singleton flag that the background monitor thread writes to
// and the Python runtime reads from. This exists alongside the struct-based
// API so that the monitor thread (which cannot hold a PyObject reference
// without the GIL) can signal suspension without touching Python at all.
// ─────────────────────────────────────────────────────────────────────────────
static GLOBAL_SUSPEND_FLAG: AtomicBool = AtomicBool::new(false);

/// Update the global suspend flag from any Rust thread.
///
/// The monitor loop calls this when RAM or VRAM exceeds blueprint limits.
/// `Ordering::SeqCst` is used here (upgraded from Relaxed) because this flag
/// is the critical safety gate — we need all threads to observe the write
/// immediately and in program order.
pub fn set_suspend_flag(suspend: bool) {
    GLOBAL_SUSPEND_FLAG.store(suspend, Ordering::SeqCst);
}

/// Read the global suspend flag. Used internally and by the legacy function API.
pub fn get_suspend_flag() -> bool {
    GLOBAL_SUSPEND_FLAG.load(Ordering::SeqCst)
}

// ─── Legacy PyO3 Function Export ─────────────────────────────────────────────
// Kept for backward compatibility: Python can call `aurix_core.check_suspend_flag()`
// without needing to instantiate a SystemState object.
// ─────────────────────────────────────────────────────────────────────────────

/// Reads the global suspend flag for the Python runtime.
///
/// This is a zero-cost poll: no GIL lock contention, no memory allocation.
/// The Python QLoRA loop should call this at the top of each micro-batch
/// iteration to decide whether to yield the GPU.
#[pyfunction]
pub fn check_suspend_flag() -> bool {
    get_suspend_flag()
}

// ─── SystemState PyClass ─────────────────────────────────────────────────────
// A cloneable, thread-safe state handle exposed to Python as a first-class
// object.  Multiple Python threads or Rust threads can hold clones of the
// same SystemState and all see the same underlying boolean.
// ─────────────────────────────────────────────────────────────────────────────

/// Thread-safe suspension state shared between the Rust governor and Python.
///
/// # Usage from Python
/// ```python
/// from aurix_core import SystemState
///
/// state = SystemState()
/// print(state.check_suspended())  # False
/// state.pause()
/// print(state.check_suspended())  # True
/// state.resume()
/// ```
///
/// # Thread Safety
/// The inner `Arc<AtomicBool>` is `Send + Sync`, so this struct can be
/// freely shared across threads on both the Rust and Python sides.
#[pyclass]
#[derive(Clone)]
pub struct SystemState {
    /// The shared atomic boolean — `true` means "the AI workload is suspended".
    /// Wrapped in Arc so that `.clone()` shares the same flag rather than
    /// creating an independent copy.
    is_suspended: Arc<AtomicBool>,
}

#[pymethods]
impl SystemState {
    /// Construct a new `SystemState` with the suspension flag set to `false`.
    ///
    /// Also synchronises the global static flag so that the monitor thread
    /// and the struct-based API agree on initial state.
    #[new]
    pub fn new() -> Self {
        set_suspend_flag(false);
        SystemState {
            is_suspended: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Activate suspension — tell the Python training loop to yield resources.
    ///
    /// This sets both the struct-local flag AND the global static flag so that
    /// code using either API observes the same state.
    pub fn pause(&self) {
        self.is_suspended.store(true, Ordering::SeqCst);
        set_suspend_flag(true);
    }

    /// Deactivate suspension — allow the training loop to resume.
    pub fn resume(&self) {
        self.is_suspended.store(false, Ordering::SeqCst);
        set_suspend_flag(false);
    }

    /// Non-blocking poll of the current suspension state.
    ///
    /// Returns `true` if the system is currently suspended (hardware limits
    /// exceeded), `false` otherwise.
    pub fn check_suspended(&self) -> bool {
        self.is_suspended.load(Ordering::SeqCst)
    }

    /// Python `__repr__` for debugging convenience.
    fn __repr__(&self) -> String {
        format!("SystemState(is_suspended={})", self.check_suspended())
    }
}

// ─── Rust-only helpers (not exposed to Python) ──────────────────────────────

impl Default for SystemState {
    fn default() -> Self {
        Self::new()
    }
}

impl SystemState {
    /// Create a cheap clone that shares the same underlying flag.
    /// This is used by the monitor thread to hold a reference without
    /// needing the GIL.
    pub fn shared_clone(&self) -> Self {
        self.clone()
    }
}

// ─── Unit Tests ──────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_initial_state_is_not_suspended() {
        let state = SystemState::new();
        assert!(!state.check_suspended(), "Initial state must be unsuspended");
    }

    #[test]
    fn test_pause_sets_suspended() {
        let state = SystemState::new();
        state.pause();
        assert!(state.check_suspended(), "After pause(), state must be suspended");
    }

    #[test]
    fn test_resume_clears_suspended() {
        let state = SystemState::new();
        state.pause();
        state.resume();
        assert!(!state.check_suspended(), "After resume(), state must be unsuspended");
    }

    #[test]
    fn test_clones_share_same_flag() {
        let state_a = SystemState::new();
        let state_b = state_a.shared_clone();

        state_a.pause();
        assert!(state_b.check_suspended(), "Clone must observe the pause");

        state_b.resume();
        assert!(!state_a.check_suspended(), "Original must observe the resume");
    }

    #[test]
    fn test_global_flag_synchronised() {
        let state = SystemState::new();
        assert!(!get_suspend_flag());

        state.pause();
        assert!(get_suspend_flag(), "Global flag must reflect struct pause()");

        state.resume();
        assert!(!get_suspend_flag(), "Global flag must reflect struct resume()");
    }
}
