# AURIX — Autonomous Universal Reasoning & Interaction Executive

AURIX is an **experimental Windows desktop AI assistant**. The application UI is built with React 18, Vite and Tauri 2; the current AI worker and automation tools are written in Python, with Windows-focused Rust native modules. The conversational AI agent is named **LUNA**.

> **Release status: development preview, not a production-safe autonomous agent.** The security hardening in this repository is partial. Do not run the app with administrator privileges or allow untrusted users to access its environment.

## Implemented in the current repository

- Inference-only local desktop chat routed to user-selected Ollama or direct GGUF models. Ollama manages local model storage and supported GPU/CPU acceleration.
- Rust telemetry for CPU/RAM and, when supported, GPU utilization, temperature and VRAM. Raw data persists in an app-local SQLite database for 24 hours, one-minute aggregates for 30 days and hourly aggregates without automatic expiry. A telemetry history chart shows 1h/24h/7d and can export CSV to app data. No per-process GPU ownership is claimed.
- Desktop application and file tool implementations with action-level permission requests.
- Single-use, fingerprint-bound pending action tokens, with a Windows native confirmation dialog for requests made through the Tauri UI.
- Session-secret-authenticated **localhost-only HTTP** between Tauri and the Python worker. Browser-origin requests and arbitrary hosts are rejected; JavaScript does not receive the token.
- Encryption/checkpoint code, secret scrubbing, SQLite-based telemetry tools, and automated Python/Rust tests.
- Opt-in AES-GCM encrypted SQLite memory and Windows DPAPI key storage, with a basic Memory Explorer panel.
- **No training is performed or required in the active assistant.** Older QLoRA research modules remain in the source tree for compatibility; they are not invoked by normal AURIX model selection or chat, and training dependencies are optional.

## Not yet implemented or validated

- A verified and signed one-click installer with auto-updater and full onboarding. An experimental unsigned PyInstaller/Tauri build script now exists.
- Authenticated Windows named-pipe IPC; the loopback HTTP transport is temporary.
- Always-on wake-word detection and interruptible voice playback. Push-to-talk now uses an optional local Whisper model when installed, otherwise reports unavailability.
- A Windows restricted-token/Job-Object command sandbox; model-generated `shell_exec` is **disabled** until this exists.
- The selected model must first be installed. Ollama is optional, and model downloads need explicit user approval. The direct GGUF backend remains an advanced alternative.
- The system no longer imposes fixed RAM/VRAM allocation ceilings or GPU-model requirements. The governor reacts to low free-memory percentages and thermal warnings; GGUF uses available acceleration with a CPU fallback. Real-world idle, training and performance benchmarks remain unverified.
- Complete role-based tool SDK, rollback/undo, persistent native approval audit, memory explorer, signed installer, and independent security assessment.
- Online communications and software-installation workflows require explicit review; no guarantee is made that every action is fully offline.

See [implementation status](docs/IMPLEMENTATION_STATUS.md) and [security model](docs/SECURITY.md) before using OS automation.

## Requirements

Windows 10/11, Python 3.10+, Node.js 24+, compatible Rust/Tauri Windows prerequisites. Ollama is a free optional local model server. Use the in-app Models panel to install Ollama through the verified winget package and download/select a supported model. The alternative direct GGUF backend requires `llama-cpp-python` and a model file. Training is not required; CPU-only local inference is supported by compatible runtime/model combinations.

## Development setup

```powershell
git clone https://github.com/KiritoTempest175/AURIX.git
cd AURIX
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
# Model setup is completed inside AURIX: Models → Install Ollama → Download model.
# Advanced users may install llama-cpp-python and import local GGUF models.
cd frontend
npm install
npm run tauri dev
```

Tauri now prefers an installer-bundled `aurix-worker.exe` beside its executable; source-mode development falls back to `frontend/bridge_server.py` using `python` or `python3` on PATH. Launching `npm run dev` **only runs the Vite browser preview**, where actions are unavailable. The packaged desktop binary is **not yet self-contained**. If the worker is missing, the UI will show it as unavailable.

Optional native engine build from the repo root:

```powershell
.\scripts\build_engine.ps1
cargo test --workspace
pytest
```

Do **not** enable public binding for the Python bridge. Its token is generated and supplied by Tauri at launch. Running `python frontend/bridge_server.py` directly refuses startup without this token.

## Configuration

`config.toml` is the active default for the tool executor and model runtime. `llm.backend="ollama"` selects local Ollama inference; a user-owned `model_selection.json` stores backend and model switching without changing tracked files. No model downloads occur automatically. Configure `security.allowed_project_paths` for workspace access. Empty trusted roots mean writes require explicit authorization and other Python file reads remain restricted to standard user folders. Legacy modules still contain other configuration defaults; consolidation is not finished.

The current `[general].offline_mode` key is informational until every network-capable tool has been migrated to a central network policy. Do not treat this flag as a verified network isolation switch.

`config/LUNA.md` is the non-personal LUNA persona file. User-specific vault content is intentionally not shipped. The historical Git repository may still contain old vault commits; follow [privacy history guidance](docs/PRIVACY_HISTORY.md).

## Resource proof (measure, don't assume)

AURIX has **targets**, not verified resource guarantees. To measure a running AURIX process:

```powershell
pip install psutil
python scripts/resource_proof.py --pid <AURIX_PROCESS_PID> --seconds 60 --csv resource-proof.csv
```

The report measures the chosen process tree's RSS and CPU, plus system-wide GPU usage/VRAM when NVML is available. It does not claim per-process VRAM ownership. There are no fixed RAM or VRAM usage quotas.

## Testing and CI

`pytest` and `cargo test --workspace` are run in Windows GitHub Actions; a frontend compilation job is also included. The security regression tests cover unauthorized loopback clients, bad hosts, browser Origins and vault path containment. Passing CI is not equivalent to full security testing.

## License

MIT — see [LICENSE](LICENSE).

## Known limitations and participation

This repo is an in-progress project. Contributions should not introduce fake model progress, hardcoded user paths, secrets, tracked personal memory or unsupported claims of offline operation. New external or destructive tool capabilities must have an auditable trusted-user authorization mechanism.

## Windows installer preview (unsigned, unverified)

Testing builds are available from [AURIX GitHub Releases](https://github.com/KiritoTempest175/AURIX/releases) **after the installer smoke test succeeds**. Choose the Windows .exe or .msi asset from the newest preview release; do not install both. A SHA256SUMS.txt checksum file is included. Preview releases are unsigned and are not production-safe.


Run on a Windows workstation after installing the project prerequisites:

```powershell
pwsh ./installer/build_windows.ps1
```

The manual `Windows Installer Preview` workflow can also be dispatched in GitHub Actions. The script creates a PyInstaller one-file Python worker and temporarily configures Tauri to bundle it. Installer startup, Microsoft code signing, clean-machine functionality and updates still require verification; **do not distribute as a production release**.

Configuration is read through `security/config_loader.py`, preferring a private per-user TOML override under `%LOCALAPPDATA%/AURIX` over the bundled default. An explicitly supplied `AURIX_CONFIG_PATH` also works.

Model weights are never downloaded automatically. To import an independently verified GGUF file:

```powershell
python scripts/import_model.py C:\\models\\approved.gguf --sha256 YOUR_VERIFIED_64_HEX_DIGEST
```

The importer checks SHA-256 before copying into the per-user models directory. Update `[llm].model_path` to match the imported file.

## Scoped Git operations

LUNA can inspect Git status, commit files that the user has **already staged**, and push the currently checked-out branch to `origin` in an explicitly trusted project. Configure a single `security.allowed_project_paths` root for commands like "push it" without a path; multiple configured projects require clarification. Git commit and push require native approval; force-push and general shell execution remain disabled. Online push is blocked in Offline Mode. No agent command automatically stages the entire repository, because this could include secrets.

## Quality and dependency checks

Windows CI now runs Python byte-compilation, pytest, Rust compilation and tests, frontend compilation, and Vitest telemetry unit tests. A separate scheduled/manual security workflow scans Git history for secrets and checks Python, npm, and Cargo advisories. Dependency scanning may identify legacy vulnerabilities; alerts must be resolved before any release. Dependabot opens update PRs for review. End-to-end Windows installer testing, native security review, coverage thresholds, and full lint normalization remain pending.

## Offline Piper speech (optional)

Install the Piper CLI locally and put a genuine .onnx voice model at the path specified by the audio.piper_model_path setting. The chat panel offers Speak last reply and Stop speech. Text is passed to Piper through standard input with no shell expansion. Local Windows playback is attempted only when synthesis succeeds. Missing dependencies and missing model files produce explicit error messages. Model weights are not downloaded automatically. Streaming TTS, barge-in detection, and a continuously listening wake-word workflow remain unimplemented.

## Memory privacy preference

The desktop System panel can enable or disable opt-in persistent memory without editing the bundled TOML file. The choice is atomically stored in the user's private AURIX application directory. Enabling requires successful DPAPI key access on Windows. Disabling prevents further memory retrieval and conversation persistence but leaves previously saved encrypted records untouched; delete them individually through Memory Explorer. No claim of secure deletion from physical storage backups is made.

## October 2026 desktop usability revision (v0.2.0 preview)

- Redesigned the desktop palette, reduced bulky central elements and fixed independently scrolling workspaces and status/chat columns.
- First-run welcome now displays and attempts to speak an explicit greeting after worker health checks pass. A persistent opt-in wake listener can listen for "Hey Luna" using an installed local Whisper model or the Windows system speech recognizer; on-device microphone compatibility remains to be validated.
- Low-risk allowlisted applications (e.g. calculator, notepad, WhatsApp) can open and close without the former unnecessary double approval; arbitrary binaries, account messages and destructive actions still require a Windows-native confirmation.
- Built-in narrow app command parsing works even before installing an Ollama model. In-app model downloading can be enabled without leaving the Models panel.
- Gmail SMTP app passwords are entered in the Email panel and protected with Windows DPAPI in the current user's private application directory. Secrets are never returned to the UI. Sending remains an explicit review-and-approve operation.
- Windows system speech output is a fallback when no Piper runtime is installed. Microphone transcription can fall back to installed Windows speech recognition if no Whisper model is configured.
- Windows builds include optional desktop automation packages such as PyAutoGUI; no Python/Node/Rust developer tooling is required for end users of the installer.

**Verification boundary:** CI unit tests and installer smoke tests are not equivalent to live device trials. Always-on speech, Windows language availability, third-party WhatsApp automation, SMTP delivery, privileged IPC hardening, secure OS process sandboxing, signed updates, clean machine trials, and accessibility audits remain unverified or incomplete. This is an unsigned testing release, not a certified production build.
