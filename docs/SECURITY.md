# AURIX security model — current implementation (October 2026)

## Scope

This file describes behavior in the committed code, not planned safeguards.

### Transport and trust
- The current worker uses HTTP bound to `127.0.0.1:9721`, **not named pipes**.
- The native Tauri process generates an unpredictable 256-bit session token for each startup and injects it into the Python child environment.
- Every Python HTTP endpoint requires `Authorization: Bearer <session token>` and validates the `Host` header.
- Browser `Origin` headers are rejected; the worker emits no permissive CORS headers. The React UI calls only native Tauri commands.
- Request bodies have a 64 KiB limit. The server limits simultaneous request threads, bounds socket reads and mutation rate, and rejects overlapping dispatches. Emergency controls bypass mutation rate limiting.
- Approval previews include complete JSON arguments and reject control characters/oversized previews. Stop invalidates outstanding approvals even after resume.
- Trust previews are obtained from the worker by native Rust. The operating system displays the exact description in a Windows `MessageBoxW` confirmation before Tauri requests execution.
- Pending action tokens in Python are fingerprint-bound and single-use; the entire approval design still requires penetration testing and native IPC replacement.

### Action restrictions
- Model-generated generic shell commands are **disabled** until a constrained Windows sandbox is available. Disabling this tool reduces functional coverage.
- Python FileSandbox limits access to the six normal Windows user folders and explicit configured workspace roots; recursive search remains unoptimized.
- The vault path check uses `Path.relative_to` instead of unsafe string prefix matching.
- Delete operations refuse permanent deletion when a recoverable Recycle Bin integration is absent.
- The Tauri CSP is non-null and does not grant general internet sources.

### Remaining threats
- The Python HTTP bridge, although authenticated, is not yet named-pipe IPC and the worker retains the secret in memory. It removes the environment entry at startup so launched apps do not inherit it.
- The Python process and external UI-automation tools still execute with the user's operating-system privileges. No restricted token or Job Object is implemented.
- The file tool's initial search strategy and all symlink/race conditions require hardening.
- A full, persisted, cryptographically verifiable approval audit trail is not wired to the Tauri dialog.
- Other modules retain legacy network/SMTP/Ollama paths. `offline_mode` is not an enforced network-control boundary.
- Model weights, memory, and telemetry require an independent privacy audit. Git history may retain past tracked vault files.
- CSP settings, Windows installer execution and network-level attacks have not been penetration-tested.

**Recommendation:** Run only as a normal non-admin Windows user in a trusted environment, and review all native confirmations. Do not assume protection against malicious software running as the same OS user.
