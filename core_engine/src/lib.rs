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

/// A Python module implemented in Rust.
/// This acts as the PyO3 FFI bridge, exposing zero-copy abstractions
/// and functions directly to the Python continuous learning engine.
#[pymodule]
fn core_engine(_py: Python, m: &PyModule) -> PyResult<()> {
    // Expose governor functions
    m.add_function(wrap_pyfunction!(governor::monitor::start_hardware_monitor, m)?)?;
    m.add_function(wrap_pyfunction!(governor::atomic_state::check_suspend_flag, m)?)?;
    
    // Expose sandbox functions
    m.add_function(wrap_pyfunction!(sandbox::file_jail::validate_path, m)?)?;
    
    // Expose observer functions
    m.add_function(wrap_pyfunction!(observers::uia_tree::get_focused_element_info, m)?)?;
    m.add_function(wrap_pyfunction!(observers::terminal_hook::execute_and_intercept, m)?)?;
    
    Ok(())
}
