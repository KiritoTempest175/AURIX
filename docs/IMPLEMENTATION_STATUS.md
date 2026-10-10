# AURIX finding-by-finding implementation tracker

Updated: 2026-10-10. Status is based on code changes, not an executed Windows penetration test. **Fixed in source** is not equivalent to fully validated or production-ready.

| ID | Status | Evidence / next action |
|---|---|---|
| C-01 | Partially mitigated | `frontend/bridge_server.py`, `frontend/src-tauri/src/main.rs`: session bearer, loopback, Host and Origin validation, no CORS; replace HTTP with protected native IPC |
| C-02 | Partially mitigated | Native `MessageBoxW` approval and `ToolExecutor.preview_pending`; independent tamper-proof approval event signing still needed |
| H-01 | Mitigated by disabling tool | `ai_brain/tool_executor.py`: shell_exec denied; add restricted-token/Job-Object runner before re-enabling |
| H-02 | Partially fixed | `ai_brain/file_control.py`: canonical allowlisted roots; address race windows and full Rust/Python unification |
| H-03 | Fixed in source | `ai_brain/second_brain.py`: path-component-safe `relative_to` |
| H-04 | Partially fixed | Remove current vault files, update `.gitignore`, `docs/PRIVACY_HISTORY.md`; rewrite Git history independently |
| H-05 | Open | `frontend/src-tauri/src/main.rs`: removed hardcoded E:/ path, but packaged sidecar is not bundled |
| H-06 | Mitigated | `frontend/src-tauri/tauri.conf.json`: references only committed icon.ico; produce full image asset set later |
| H-07 | Partially mitigated | `ai_engine/training/student_qlora_loop.py` now launches a real gated QLoRA subprocess and reports exit status; model evaluation and metrics remain unverified |
| H-08 | Partially fixed | `core_engine/src/governor/monitor.rs`: corrected 102 typo and 12/6 GiB constants; load limits from validated config and measure app allocation |
| H-09 | Partially fixed | `frontend/src/App.jsx`: approval preview + Rust native confirmation; persistent audit and expiry visualization remain |
| H-10 | Fixed in source | Tauri CSP enabled in `frontend/src-tauri/tauri.conf.json`; review final policies with packaged app |
| M-01 | Partially fixed | Thread/request bounds in bridge; inference still serialized and can block queued requests |
| M-02 | Fixed at bridge | Safe structured error codes in `frontend/bridge_server.py`; other legacy tools still leak errors |
| M-03 | Partially fixed | Reused reqwest client with 120-second timeout; need individual deadlines/cancel support |
| M-04 | Fixed in source | React `isTauri()`; browser no longer calls private localhost API |
| M-05 | Mitigated by honest UI | Voice button reports unavailable instead of invented transcript |
| M-06 | Partially fixed | UI worker health is probed, native Rust telemetry now reads GPU utilization/temperature/VRAM via NVML when supported; full historical health and charts remain |
| M-07 | Open | `config.toml` remains authoritative for tool permissions, but legacy `config/luna.toml` is still referenced |
| M-08 | Open | Lock files, pip/npm audits and pinned dependency updates still required |
| M-09 | Partially fixed | New `tests/test_bridge_security.py`; full installer/IPC abuse-case suite missing |
| M-10 | Open | Existing DB schema contains audit table, but native dialog events not durably recorded |
| M-11 | Fixed for root docs | Replaced README/security docs with explicit current limitations |
| M-12 | Mitigated by disabling generic shell | Windows shell executor remains incomplete; bound output, process termination and child job control not implemented |
| L-01 | Fixed in source | Removed duplicate `AppCloser` declaration from `ai_brain/app_control.py` |
| L-02 | Open | No WCAG contrast/accessibility verification yet |
| L-03 | Mitigated | Nonfunctional nav buttons disabled; actual panels remain to implement |
| L-04 | Fixed in root docs | Correct repo URL, accurate developer setup and screenshot limitations |
| L-05 | Partially fixed | AURIX product and LUNA persona documented; legacy names/configs remain |

## Platform commitments still outstanding

- A bundled, validated GGUF/llama.cpp runtime; optional local-only `ai_engine/inference/local_gguf.py` now runs the default model path without cloud/Ollama.
- Lazy wake-word/STT/TTS pipeline and interruptible speech.
- Measured near-zero idle resources and hard per-process VRAM limits.
- Rust telemetry history and CSV exports.
- Full git/software installation/IDE/email/WhatsApp action set with risk tiers.
- Encrypted searchable second brain and memory-management UI.
- Evaluated QLoRA adapters with genuine loss/progress reporting and rollback, beyond the gated training subprocess.
- Signed single installer, updater, system tray, global kill switch and accessibility audit.

No remaining item above should be advertised as production-ready.
