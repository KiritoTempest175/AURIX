use pyo3::prelude::*;
use std::sync::atomic::{AtomicBool, Ordering};

/// A global, thread-safe boolean flag indicating whether the background 
/// deep learning tasks should suspend to free up hardware resources.
static SUSPEND_FLAG: AtomicBool = AtomicBool::new(false);

/// Updates the suspend flag from the Rust governor thread.
/// 
/// Uses `Ordering::Relaxed` because this flag doesn't synchronize other 
/// memory accesses, it just acts as a simple boolean signal.
pub fn set_suspend_flag(suspend: bool) {
    SUSPEND_FLAG.store(suspend, Ordering::Relaxed);
}

/// Reads the suspend flag for the Python runtime.
/// 
/// This is exposed as a PyO3 function so the Python QLoRA background 
/// loop can quickly poll this state without GIL locking on the Rust side.
#[pyfunction]
pub fn check_suspend_flag() -> bool {
    SUSPEND_FLAG.load(Ordering::Relaxed)
}
