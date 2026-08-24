use pyo3::prelude::*;
use std::path::{Path, PathBuf};
use std::fs;

/// A simple global whitelist for the file jail. 
/// In a real implementation, this would be dynamically loaded from a config file
/// or set upon agent initialization.
const ALLOWED_ROOT: &str = "C:\\Users\\NAC\\Documents\\University\\Projects";

/// Validates a file path to ensure it is within the allowed root directory.
/// 
/// Performs path canonicalization to resolve any symlinks, `..`, or `.` segments
/// that could be used for directory traversal attacks. If the final path
/// attempts to escape the allowed root, this function will trigger a Rust panic,
/// acting as a hard security boundary.
#[pyfunction]
pub fn validate_path(requested_path_str: &str) -> PyResult<String> {
    let requested_path = Path::new(requested_path_str);
    let root_path = Path::new(ALLOWED_ROOT);

    // Canonicalize both the requested path and the allowed root
    let canon_req = match fs::canonicalize(requested_path) {
        Ok(p) => p,
        Err(e) => {
            // If the file doesn't exist yet, we can't fully canonicalize it via OS,
            // so we canonicalize its parent directory instead.
            if let Some(parent) = requested_path.parent() {
                if let Ok(canon_parent) = fs::canonicalize(parent) {
                    let mut p = PathBuf::from(canon_parent);
                    p.push(requested_path.file_name().unwrap_or_default());
                    p
                } else {
                    return Err(pyo3::exceptions::PyIOError::new_err(format!("Parent directory does not exist or access denied: {}", e)));
                }
            } else {
                return Err(pyo3::exceptions::PyIOError::new_err(format!("Path canonicalization failed: {}", e)));
            }
        }
    };
    
    // Attempt to canonicalize the root path as well (this should always exist in a healthy state)
    let canon_root = fs::canonicalize(root_path)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to canonicalize root jail path: {}", e)))?;

    // Check if the canonicalized requested path starts with the canonicalized allowed root.
    if !canon_req.starts_with(&canon_root) {
        // Enforce the strict blueprint invariant: throw an immediate Rust IO panic.
        panic!(
            "SECURITY VIOLATION: Attempted to access path {:?} outside of the designated File Jail {:?}!",
            canon_req, canon_root
        );
    }

    Ok(canon_req.to_string_lossy().into_owned())
}
