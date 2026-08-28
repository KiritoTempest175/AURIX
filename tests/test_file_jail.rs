// ─────────────────────────────────────────────────────────────────────────────
// tests/test_file_jail.rs — Security Sandbox Boundary Tests
// ─────────────────────────────────────────────────────────────────────────────
// Verifies that the file jail correctly REJECTS paths that attempt to
// escape the designated safe zone.
//
// These tests use `#[should_panic(expected = "Access Denied")]` to assert
// that `secure_path_resolve()` panics when given an out-of-bounds path.
// Each test runs in its own process (Rust test harness default for panics)
// so a panic in one doesn't affect others.
//
// Blueprint invariant: NO file I/O may occur outside the allowed root.
// A path escape is a critical security violation and MUST halt execution.
// ─────────────────────────────────────────────────────────────────────────────

use core_engine::sandbox::file_jail::secure_path_resolve;
use std::path::Path;

/// Verify that attempting to access `C:\Windows\System32` from a project
/// jail directory triggers a panic with "Access Denied".
///
/// This is the primary security boundary test: the agent MUST NOT be able
/// to read, write, or execute files in system directories.
#[test]
#[should_panic(expected = "Access Denied")]
fn test_absolute_system32_path_rejected() {
    let jail_base = Path::new(r"C:\Users\NAC\Documents\University\Projects");

    // This absolute path is outside the jail — must panic.
    let _ = secure_path_resolve(jail_base, r"C:\Windows\System32");
}

/// Verify that `..` traversal out of the jail is caught and rejected.
///
/// An attacker (or a confused model output) might try to use relative
/// path segments to escape the jail.  The canonicalization step resolves
/// these before the containment check.
#[test]
#[should_panic(expected = "Access Denied")]
fn test_dot_dot_traversal_rejected() {
    let jail_base = Path::new(r"C:\Users\NAC\Documents\University\Projects");

    // Traversing up four levels from Projects lands in C:\Users\NAC which
    // is outside the jail boundary.
    let _ = secure_path_resolve(jail_base, r"..\..\..\..\Windows\System32");
}

/// Verify that a different drive letter is rejected.
///
/// On Windows, absolute paths on a different drive bypass relative
/// path resolution entirely.  The jail must still catch this.
#[test]
#[should_panic(expected = "Access Denied")]
fn test_different_drive_letter_rejected() {
    let jail_base = Path::new(r"C:\Users\NAC\Documents\University\Projects");

    // D: drive (if it exists) is outside the jail regardless.
    // Even if D: doesn't exist, the canonicalization failure or the
    // containment check will catch it.
    let _ = secure_path_resolve(jail_base, r"D:\SomeFolder\malicious.exe");
}

/// Verify that a valid path WITHIN the jail is accepted (positive test).
///
/// This ensures we haven't made the jail so restrictive that it rejects
/// legitimate paths.
#[test]
fn test_valid_path_within_jail_accepted() {
    let jail_base = Path::new(r"C:\Users\NAC\Documents\University\Projects");

    // The jail base itself should be accepted.
    let result = secure_path_resolve(jail_base, r"C:\Users\NAC\Documents\University\Projects");
    assert!(
        result.is_ok(),
        "The jail base directory itself must be accepted"
    );

    let canonical = result.unwrap();
    assert!(
        canonical.starts_with(r"\\?\C:\Users\NAC\Documents\University\Projects")
            || canonical.starts_with(r"C:\Users\NAC\Documents\University\Projects"),
        "Canonical path must be under the jail base, got: {:?}",
        canonical
    );
}
