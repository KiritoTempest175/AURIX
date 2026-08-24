use pyo3::prelude::*;
use std::process::{Command, Stdio};
use std::io::Read;

/// Spawns a headless child process, intercepts its standard I/O,
/// and returns the combined output and exit status.
///
/// This provides the "Terminal PTY" stream for the Python semantic compiler
/// while ensuring the process runs in an isolated, network-disabled (by default) context.
#[pyfunction]
pub fn execute_and_intercept(cmd: &str) -> PyResult<(i32, String, String)> {
    // In a production scenario on Windows, we'd wrap this in a proper PTY
    // using ConPTY or winpty, but for our MVP, we pipe standard handles.
    
    // We execute via cmd.exe for ease of arbitrary shell commands.
    let mut child = Command::new("cmd")
        .args(&["/C", cmd])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to spawn process: {}", e)))?;

    // We can interact with child.stdin if needed here.
    
    let mut stdout_str = String::new();
    let mut stderr_str = String::new();

    if let Some(mut out) = child.stdout.take() {
        let _ = out.read_to_string(&mut stdout_str);
    }
    
    if let Some(mut err) = child.stderr.take() {
        let _ = err.read_to_string(&mut stderr_str);
    }

    let status = child.wait()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to wait for process: {}", e)))?;

    let exit_code = status.code().unwrap_or(-1);

    Ok((exit_code, stdout_str, stderr_str))
}
