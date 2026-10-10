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
| H-05 | Partial | Native startup prefers a packaged worker and an unsigned Windows sidecar/Tauri workflow exists; clean-VM installation remains unverified |
| H-06 | Mitigated | `frontend/src-tauri/tauri.conf.json`: references only committed icon.ico; produce full image asset set later |
| H-07 | Not applicable to active inference | Normal AURIX uses selected Ollama/GGUF model inference only. Legacy QLoRA research modules are not part of model selection or conversation; dependencies moved to optional training extras. |
| H-08 | Adapted to new requirement | Removed absolute RAM/VRAM ceilings from Rust and Python. The governor now yields background work on relative low-memory/thermal signals, and GGUF permits any supported GPU backend with CPU fallback. Native hardware benchmarks remain pending. |
| H-09 | Partially fixed | Native confirmation and 600-char complete outbound message preview; persistent audit, large scrollable previews and expiry display remain |
| H-10 | Fixed in source | Tauri CSP enabled in `frontend/src-tauri/tauri.conf.json`; review final policies with packaged app |
| M-01 | Partially fixed | Thread/request bounds in bridge; inference still serialized and can block queued requests |
| M-02 | Fixed at bridge | Safe structured error codes in `frontend/bridge_server.py`; other legacy tools still leak errors |
| M-03 | Partially fixed | Reused reqwest client with 120-second timeout; need individual deadlines/cancel support |
| M-04 | Fixed in source | React `isTauri()`; browser no longer calls private localhost API |
| M-05 | Mitigated by honest UI | Voice button reports unavailable instead of invented transcript |
| M-06 | Partially fixed | Rust GPU metrics, SQLite raw/minute/hour history, CSV export and live event updates are implemented. GPU-less systems report N/A; full runtime validation and subsystem health checks are pending |
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

- Real end-to-end validation of the in-app Ollama installation/model downloads and GGUF fallback on clean Windows; model weights remain user-installed.
- Lazy wake-word/STT/TTS pipeline and interruptible speech.
- Measured low idle resource use and adaptive optimization on varied hardware; fixed RAM/VRAM caps were intentionally removed.
- Rust telemetry history and CSV exports.
- Full git/software installation/IDE/email/WhatsApp action set with risk tiers.
- Complete second brain: opt-in encrypted SQLite memory and an initial Memory Explorer are available; vector retrieval, conflict resolution, durable backups and tested key rotation remain outstanding.
- No QLoRA training is needed or scheduled in the active assistant. Optional legacy research code remains in the repository, outside the production inference workflow.
- Verified signed Windows installer, updater, system tray, OS-level kill switch and accessibility audit. A manual unsigned preview script exists.

No remaining item above should be advertised as production-ready.

### New scoped developer functions

`ai_brain/developer_tools.py` implements typed `git_status`, `git_commit`, and `git_push` without shell interpolation. Workspaces are verified against configured roots; commit and publish are native-approval gated. Arbitrary code execution, package installation, and IDE-agent injection still need safe implementation and validation.

### CI improvements

The main pipeline now includes frontend Vitest telemetry tests and Python syntax compilation. A scheduled/manual security workflow includes Gitleaks, pip-audit, npm audit and cargo-audit; Dependabot configurations exist. CI is still being actively stabilized and the release workflow has not passed a clean Windows installer smoke test.

### Local text-to-speech (partial)

The Windows-only Piper adapter in native_ui/audio/offline_tts.py synthesizes bounded, user-requested text from a locally installed voice model and Piper binary. A separate stop command cancels playback. This is not continuous wake-word processing, streaming responses, or automatic spoken greetings. Actual Windows/audio hardware validation is still necessary.

### Memory privacy UI
Memory capture may now be toggled in System and Memory views with an explicit consent prompt. The selected preference is saved privately to privacy-settings.json, with DPAPI preflight before enabling. This does not implement full memory backup, key rotation, vector search or guaranteed secure erasure.


### Local-model configuration (inference only)

The model setup is controlled by the desktop Models panel, which calls trusted native Rust commands for `winget` installation, local Ollama model downloads (with progress events), deletion and activation. The Python worker uses the fixed loopback Ollama chat API or the configured GGUF backend. Users choose Qwen3, Gemma3 or any syntactically valid installed Ollama model tag; model weights are never downloaded automatically. Runtime verification on real Windows hardware remains required.

### v0.2.0 desktop usability revision

Implemented in source: independent scrolling, updated desktop style, first-run text and TTS greeting, low-risk no-prompt app allowlist, deterministic known-app routing before model setup, secure DPAPI-backed SMTP credential entry in the Email panel, opt-in persistent wake listener, Windows speech-to-text/speech-output fallbacks, and packaged optional desktop automation Python dependencies.

Remaining for release sign-off: actual microphone and wake test on supported Windows speech environments, Windows installer clean-VM smoke, local GPU/model performance, end-to-end Ollama and WhatsApp UI automation, real SMTP recipient test, automatic update/code signing, stronger native IPC and process sandbox, and independent security/accessibility audit. This status is not a claim of 10/10 production readiness.
