// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/lib.rs — PyO3 FFI Bridge
// ─────────────────────────────────────────────────────────────────────────────
// This is the root of the `aurix_core` native Python module.  It registers
// all Rust subsystems (governor, observers, sandbox) with PyO3 so that
// Python can import and use them via:
//
//   import aurix_core
//
// The module exposes both class-based and function-based APIs:
//
//   Classes (struct-based, stateful):
//     aurix_core.SystemState()       — thread-safe suspend/resume flag
//     aurix_core.UIATreeObserver()   — Windows UI Automation polling
//     aurix_core.TerminalHook()      — headless child process execution
//
//   Functions (legacy, stateless):
//     aurix_core.start_hardware_monitor()  — spawn background governor
//     aurix_core.check_suspend_flag()      — read global suspend flag
//     aurix_core.validate_path(path)       — security sandbox check
//     aurix_core.get_focused_element_info()— one-shot UIA query
//     aurix_core.execute_and_intercept(cmd)— one-shot command execution
//
// Blueprint invariant: Everything runs in-process.  Zero network sockets,
// zero localhost HTTP, zero WebView.  Python imports this as a native
// `.pyd` (Windows) / `.so` (Linux) extension module built by Maturin.
// ─────────────────────────────────────────────────────────────────────────────

use pyo3::prelude::*;

/// The governor module tracks hardware usage (RAM/VRAM)
/// and triggers graceful suspension of the AI if thresholds are exceeded.
pub mod governor {
    pub mod monitor;
    pub mod atomic_state;
}

/// The observers module hooks into the OS to capture
/// UI tree changes and terminal standard I/O in real-time.
pub mod observers {
    pub mod uia_tree;
    pub mod terminal_hook;
}

/// The sandbox module restricts the agent's filesystem
/// access and execution capabilities to prevent destructive behavior.
pub mod sandbox {
    pub mod file_jail;
}

/// The `aurix_core` Python native module.
///
/// This function is called automatically by Python when `import aurix_core`
/// is executed.  It registers all exported classes and functions.
///
/// # Architecture Notes
/// - `Bound<'_, PyModule>` is the PyO3 0.20+ API for module references.
/// - Classes are added with `m.add_class::<T>()` which registers the type
///   so Python can instantiate it with `T()`.
/// - Functions are added with `m.add_function(wrap_pyfunction!(...))`.
/// - The module name in `#[pymodule]` must match the `[lib] name` in
///   Cargo.toml for the import to work.
#[pymodule]
fn core_engine(_py: Python, m: &PyModule) -> PyResult<()> {
    // ── Register PyO3 Classes ────────────────────────────────────────────
    // These allow Python to create stateful instances:
    //   state = aurix_core.SystemState()
    //   observer = aurix_core.UIATreeObserver()
    //   hook = aurix_core.TerminalHook()
    m.add_class::<governor::atomic_state::SystemState>()?;
    m.add_class::<observers::uia_tree::UIATreeObserver>()?;
    m.add_class::<observers::terminal_hook::TerminalHook>()?;

    // ── Register Legacy Free Functions ───────────────────────────────────
    // These provide a simpler, stateless API for one-shot operations.

    // Governor functions
    m.add_function(wrap_pyfunction!(governor::monitor::start_hardware_monitor, m)?)?;
    m.add_function(wrap_pyfunction!(governor::atomic_state::check_suspend_flag, m)?)?;

    // Sandbox functions
    m.add_function(wrap_pyfunction!(sandbox::file_jail::validate_path, m)?)?;

    // Observer functions
    m.add_function(wrap_pyfunction!(observers::uia_tree::get_focused_element_info, m)?)?;
    m.add_function(wrap_pyfunction!(observers::terminal_hook::execute_and_intercept, m)?)?;

    Ok(())
}
