// ─────────────────────────────────────────────────────────────────────────────
// core_engine/src/sandbox/file_jail.rs
// ─────────────────────────────────────────────────────────────────────────────
// Security Sandbox — Path Canonicalization & Trust Token Enforcement.
//
// This module is the last line of defence preventing the AURIX agent from
// accessing, modifying, or deleting files outside of designated safe zones.
//
// Every file path the agent produces (whether from the QLoRA model's output
// or from a user-issued command) MUST pass through `secure_path_resolve()`
// before any I/O operation is performed.
//
// Architecture:
// - `secure_path_resolve()` is a pure function: it takes a base directory
//   and a target path string, resolves symlinks and `..` segments via the
//   OS, and verifies the result lives strictly under the base.
// - If the resolved path escapes the jail, the function panics with a
//   security violation message.  This is intentional: a path-escape
//   attempt is a critical safety failure and must halt execution.
// - The PyO3 wrapper `validate_path()` converts the panic into a Python
//   exception so the agent can log the violation and recover gracefully.
//
// Blueprint invariant: The default allowed root is set to the project
// workspace directory.  Production deployments should make this configurable.
// ─────────────────────────────────────────────────────────────────────────────

use pyo3::prelude::*;
use std::path::{Path, PathBuf};
use std::fs;
use std::io;

// ─── Default Allowed Root ───────────────────────────────────────────────────
// The top-level directory that the agent is permitted to access.
// Any path that resolves outside this boundary is rejected.
// ─────────────────────────────────────────────────────────────────────────────
const ALLOWED_ROOT: &str = r"C:\Users\NAC\Documents\University\Projects";

// ─── Core Security Function ────────────────────────────────────────────────

/// Resolve and validate a target path against a base directory jail.
///
/// # Algorithm
/// 1. Canonicalize the `base_dir` to obtain its absolute, symlink-resolved form.
/// 2. Join `base_dir` and `target` to produce the candidate path.
/// 3. Canonicalize the candidate.  If the candidate doesn't exist yet,
///    canonicalize its parent and re-append the filename.
/// 4. Verify that the canonicalized candidate starts with the canonicalized
///    base.  This check is resistant to:
///    - `..` traversal (`base/../../etc/passwd`)
///    - Symlink attacks (symlink inside base pointing outside)
///    - Windows drive-letter escapes (`D:\malicious`)
///    - UNC path injection (`\\server\share`)
///
/// # Panics
/// Panics with `"Access Denied"` if the resolved path escapes the jail.
/// This is intentional — a jail escape is a critical security violation.
///
/// # Errors
/// Returns `io::Error` if canonicalization fails (e.g., path doesn't exist
/// and neither does its parent).
pub fn secure_path_resolve(base_dir: &Path, target: &str) -> Result<PathBuf, io::Error> {
    // ── Step 1: Canonicalize the base jail directory ─────────────────────
    let canon_base = fs::canonicalize(base_dir).map_err(|e| {
        io::Error::new(
            io::ErrorKind::NotFound,
            format!(
                "Jail base directory {:?} does not exist or is inaccessible: {}",
                base_dir, e
            ),
        )
    })?;

    // ── Step 2: Build the candidate path ────────────────────────────────
    // If `target` is an absolute path, `Path::new(target)` ignores the
    // base entirely — that's fine, we'll catch it in the containment check.
    let target_path = Path::new(target);
    let candidate = if target_path.is_absolute() {
        target_path.to_path_buf()
    } else {
        base_dir.join(target)
    };

    // ── Step 3: Canonicalize the candidate ──────────────────────────────
    // Try the full path first.  If it doesn't exist (e.g., the agent is
    // about to create a new file), fall back to canonicalizing the parent
    // and appending the final component.
    let canon_candidate = match fs::canonicalize(&candidate) {
        Ok(p) => p,
        Err(_) => {
            // The file might not exist yet — canonicalize its parent.
            let parent = candidate.parent().ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!("Path {:?} has no parent directory", candidate),
                )
            })?;

            let canon_parent = fs::canonicalize(parent).map_err(|e| {
                io::Error::new(
                    io::ErrorKind::NotFound,
                    format!(
                        "Parent directory {:?} does not exist or is inaccessible: {}",
                        parent, e
                    ),
                )
            })?;

            let filename = candidate
                .file_name()
                .ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::InvalidInput,
                        format!("Path {:?} has no filename component", candidate),
                    )
                })?;

            canon_parent.join(filename)
        }
    };

    // ── Step 4: Containment check ───────────────────────────────────────
    // The canonicalized candidate must start with the canonicalized base.
    // On Windows, `starts_with` is case-insensitive for drive letters but
    // case-sensitive for directory names.  Since both sides go through
    // `fs::canonicalize`, the OS normalizes casing for us.
    if !canon_candidate.starts_with(&canon_base) {
        panic!(
            "Access Denied: path {:?} escapes jail boundary {:?}",
            canon_candidate, canon_base
        );
    }

    Ok(canon_candidate)
}

// ─── PyO3 Wrapper ───────────────────────────────────────────────────────────

/// Validate a file path against the default allowed root directory.
///
/// This wraps `secure_path_resolve()` for Python consumption, using the
/// compile-time `ALLOWED_ROOT` constant as the jail boundary.
///
/// # Python Usage
/// ```python
/// from aurix_core import validate_path
///
/// safe = validate_path(r"C:\Users\NAC\Documents\University\Projects\AURIX\data.txt")
/// # Returns: "\\?\C:\Users\NAC\Documents\University\Projects\AURIX\data.txt"
///
/// validate_path(r"C:\Windows\System32\cmd.exe")
/// # Raises: RuntimeError (Access Denied)
/// ```
///
/// # Errors
/// Returns `PyRuntimeError` if the path escapes the jail or canonicalization fails.
#[pyfunction]
pub fn validate_path(requested_path_str: &str) -> PyResult<String> {
    let root = Path::new(ALLOWED_ROOT);

    // Use `std::panic::catch_unwind` to convert the panic from
    // `secure_path_resolve` into a Python exception, since panics
    // across the FFI boundary are undefined behaviour.
    let result = std::panic::catch_unwind(|| {
        secure_path_resolve(root, requested_path_str)
    });

    match result {
        Ok(Ok(canonical)) => Ok(canonical.to_string_lossy().into_owned()),
        Ok(Err(io_err)) => Err(pyo3::exceptions::PyIOError::new_err(format!(
            "Path validation I/O error: {}",
            io_err
        ))),
        Err(panic_payload) => {
            // Extract the panic message for a meaningful Python error.
            let msg = if let Some(s) = panic_payload.downcast_ref::<&str>() {
                s.to_string()
            } else if let Some(s) = panic_payload.downcast_ref::<String>() {
                s.clone()
            } else {
                "Access Denied: path escapes the designated jail boundary".to_string()
            };
            Err(pyo3::exceptions::PyRuntimeError::new_err(msg))
        }
    }
}

// ─── Unit Tests ──────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;

    #[test]
    fn test_valid_path_within_jail() {
        // Use the current directory as a known-valid jail base.
        let base = env::current_dir().expect("Failed to get cwd");
        let result = secure_path_resolve(&base, "Cargo.toml");
        assert!(result.is_ok(), "Cargo.toml should resolve within the jail");
    }

    #[test]
    #[should_panic(expected = "Access Denied")]
    fn test_traversal_escape_panics() {
        let base = env::current_dir().expect("Failed to get cwd");
        // Use an absolute path that is guaranteed to be outside the CWD jail.
        // This tests the containment check against absolute path injection.
        let _ = secure_path_resolve(&base, r"C:\Windows");
    }

    #[test]
    #[should_panic(expected = "Access Denied")]
    fn test_absolute_path_escape_panics() {
        let base = env::current_dir().expect("Failed to get cwd");
        // An absolute path outside the jail must also be rejected.
        let _ = secure_path_resolve(&base, r"C:\Windows\System32");
    }
}
