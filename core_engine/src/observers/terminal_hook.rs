// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/observers/terminal_hook.rs
// ─────────────────────────────────────────────────────────────────────────────
// Child Process PTY Interceptor — spawns sandboxed shell commands and
// captures their stdout, stderr, and exit code.
//
// This module provides the "Terminal Observer" stream for the continuous
// learning pipeline.  Every command the AURIX agent executes is routed
// through this interceptor so the semantic compiler can correlate terminal
// output with UI state (from uia_tree.rs) to produce grounded training data.
//
// Blueprint invariant: Processes are spawned headless with piped handles.
// On Windows we use `cmd.exe /C` for shell dispatch.  The
// `CREATE_NO_WINDOW` flag prevents console flicker.
// ─────────────────────────────────────────────────────────────────────────────

use pyo3::prelude::*;
use std::process::{Command, Stdio};
use std::io::Read;
use serde::Serialize;

// ─── Windows-specific constants ─────────────────────────────────────────────
// CREATE_NO_WINDOW (0x08000000) prevents the child process from spawning
// a visible console window on the desktop.
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

// ─── Command Result DTO ─────────────────────────────────────────────────────

/// Structured result of a shell command execution.
/// Serializable for logging into the telemetry pipeline.
#[derive(Serialize, Debug, Clone)]
pub struct CommandResult {
    /// The original command string that was executed.
    pub command: String,
    /// Process exit code.  `-1` if the process was killed by a signal.
    pub exit_code: i32,
    /// Captured standard output (UTF-8 lossy decoded).
    pub stdout: String,
    /// Captured standard error (UTF-8 lossy decoded).
    pub stderr: String,
    /// Whether the command completed successfully (exit code 0).
    pub success: bool,
}

// ─── Legacy PyFunction Export ───────────────────────────────────────────────

/// Execute a shell command and return `(exit_code, stdout, stderr)`.
///
/// Kept for backward compatibility with existing Python code.
#[pyfunction]
pub fn execute_and_intercept(cmd: &str) -> PyResult<(i32, String, String)> {
    let hook = TerminalHook::new();
    let result = hook.execute_command(cmd)?;
    Ok((result.exit_code, result.stdout, result.stderr))
}

// ─── TerminalHook PyClass ───────────────────────────────────────────────────

/// Child process interceptor for the AURIX agent's terminal stream.
///
/// # Usage from Python
/// ```python
/// from aurix_core import TerminalHook
///
/// hook = TerminalHook()
/// exit_code, stdout, stderr = hook.run("echo Hello from AURIX")
/// print(f"Exit: {exit_code}, Out: {stdout}")
/// ```
///
/// # Security
/// Commands are run in the context of the current user.  The `file_jail`
/// module should be used to validate any file paths *before* passing them
/// to a terminal command.
#[pyclass]
#[derive(Clone)]
pub struct TerminalHook {
    // Stateless — each command invocation spawns a fresh child process.
    // We could add fields here for configurable working directory,
    // environment variable overrides, or timeout limits in the future.
    _private: (),
}

#[pymethods]
impl TerminalHook {
    /// Create a new TerminalHook instance.
    #[new]
    pub fn new() -> Self {
        TerminalHook { _private: () }
    }

    /// Execute a shell command and return `(exit_code, stdout, stderr)`.
    ///
    /// The command is dispatched via `cmd.exe /C` on Windows.  Standard
    /// handles are piped so the parent process captures all output.
    /// The `CREATE_NO_WINDOW` flag suppresses console window creation.
    ///
    /// # Arguments
    /// * `cmd` — The shell command to execute (e.g., `"dir C:\\Users"`).
    ///
    /// # Returns
    /// A tuple of `(exit_code: i32, stdout: str, stderr: str)`.
    ///
    /// # Errors
    /// Returns `PyRuntimeError` if the process cannot be spawned or waited on.
    #[pyo3(name = "run")]
    pub fn run_py(&self, cmd: &str) -> PyResult<(i32, String, String)> {
        let result = self.execute_command(cmd)?;
        Ok((result.exit_code, result.stdout, result.stderr))
    }

    /// Python `__repr__` for debugging.
    fn __repr__(&self) -> String {
        "TerminalHook()".to_string()
    }
}

impl Default for TerminalHook {
    fn default() -> Self {
        Self::new()
    }
}

impl TerminalHook {
    /// Core command execution logic — used by both the PyO3 methods and
    /// the legacy free-function export.
    ///
    /// # Implementation Details
    /// 1. We build a `Command` targeting `cmd.exe /C <user_command>`.
    /// 2. On Windows, `creation_flags(CREATE_NO_WINDOW)` prevents a
    ///    console window from flashing on screen.
    /// 3. All three standard handles (stdin, stdout, stderr) are piped.
    /// 4. We read stdout and stderr fully into memory, then wait for exit.
    /// 5. The exit code is extracted; `-1` is used as a sentinel if the
    ///    process was terminated by a signal rather than exiting normally.
    pub fn execute_command(&self, cmd: &str) -> PyResult<CommandResult> {
        // ── Build the Command ────────────────────────────────────────────
        let mut command = Command::new("cmd");
        command
            .args(&["/C", cmd])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // On Windows, suppress the console window for headless operation.
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(CREATE_NO_WINDOW);
        }

        // ── Spawn the child process ──────────────────────────────────────
        let mut child = command.spawn().map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!(
                "Failed to spawn child process for command '{}': {}",
                cmd, e
            ))
        })?;

        // ── Capture stdout ───────────────────────────────────────────────
        let mut stdout_buf = String::new();
        if let Some(mut out) = child.stdout.take() {
            let _ = out.read_to_string(&mut stdout_buf);
        }

        // ── Capture stderr ───────────────────────────────────────────────
        let mut stderr_buf = String::new();
        if let Some(mut err) = child.stderr.take() {
            let _ = err.read_to_string(&mut stderr_buf);
        }

        // ── Wait for exit ────────────────────────────────────────────────
        let status = child.wait().map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!(
                "Failed to wait for child process: {}",
                e
            ))
        })?;

        let exit_code = status.code().unwrap_or(-1);

        Ok(CommandResult {
            command: cmd.to_string(),
            exit_code,
            stdout: stdout_buf,
            stderr: stderr_buf,
            success: exit_code == 0,
        })
    }
}
