# AURIX — Autonomous Universal Reasoning & Interaction Executive

AURIX is an **experimental Windows desktop AI assistant**. The application UI is built with React 18, Vite and Tauri 2; the current AI worker and automation tools are written in Python, with Windows-focused Rust native modules. The conversational AI agent is named **LUNA**.

> **Release status: development preview, not a production-safe autonomous agent.** The security hardening in this repository is partial. Do not run the app with administrator privileges or allow untrusted users to access its environment.

## Implemented in the current repository

- Local desktop chat routed to a Python agent when a supported model and runtime are available.
- Rust telemetry for CPU/RAM and, when supported, GPU utilization, temperature and VRAM. Raw data persists in an app-local SQLite database for 24 hours, one-minute aggregates for 30 days and hourly aggregates without automatic expiry. A telemetry history chart shows 1h/24h/7d and can export CSV to app data. No per-process GPU ownership is claimed.
- Desktop application and file tool implementations with action-level permission requests.
- Single-use, fingerprint-bound pending action tokens, with a Windows native confirmation dialog for requests made through the Tauri UI.
- Session-secret-authenticated **localhost-only HTTP** between Tauri and the Python worker. Browser-origin requests and arbitrary hosts are rejected; JavaScript does not receive the token.
- Encryption/checkpoint code, secret scrubbing, SQLite-based telemetry tools, and automated Python/Rust tests.
- Opt-in AES-GCM encrypted SQLite memory and Windows DPAPI key storage, with a basic Memory Explorer panel.
- The guarded StudentTrainingController now starts an actual QLoRA subprocess only when the workstation is idle and plugged in, CUDA and training dependencies are available, and a local dataset exists. It reports real process status, not simulated progress. Its training results have not been independently evaluated.

## Not yet implemented or validated

- A verified and signed one-click installer with auto-updater and full onboarding. An experimental unsigned PyInstaller/Tauri build script now exists.
- Authenticated Windows named-pipe IPC; the loopback HTTP transport is temporary.
- Always-on wake-word detection and interruptible voice playback. Push-to-talk now uses an optional local Whisper model when installed, otherwise reports unavailability.
- A Windows restricted-token/Job-Object command sandbox; model-generated `shell_exec` is **disabled** until this exists.
- The active agent router uses lazy, local GGUF inference through optional `llama-cpp-python`. Model weights and the native library are not bundled. Legacy Transformers/Ollama code remains in the repository but is not used by the default router.
- A verified 6 GB **per-application** VRAM / 12 GB RAM hard cap, idle <150 MB resource guarantee, and complete evaluated training.
- Complete role-based tool SDK, rollback/undo, persistent native approval audit, memory explorer, signed installer, and independent security assessment.
- Online communications and software-installation workflows require explicit review; no guarantee is made that every action is fully offline.

See [implementation status](docs/IMPLEMENTATION_STATUS.md) and [security model](docs/SECURITY.md) before using OS automation.

## Requirements

Windows 10/11, Python 3.10+, Node.js 22+, a compatible Rust toolchain and the Tauri Windows prerequisites. Model inference, speech and GPU training have their own optional native/dependency requirements. CPU-only inference requires a compatible local GGUF model and `llama-cpp-python`. Missing weights or dependencies produce a clear error, not a fake LLM response.

## Development setup

```powershell
git clone https://github.com/KiritoTempest175/AURIX.git
cd AURIX
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
# Install llama-cpp-python with a compatible CPU/CUDA wheel from a trusted distributor.
# Place a verified local GGUF model at config.toml [llm].model_path.
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

`config.toml` is the active file for the tool executor and lazy GGUF model runtime; it does not auto-download weights. Configure `security.allowed_project_paths` for workspace access. Empty trusted roots mean writes require explicit authorization and other Python file reads remain restricted to standard user folders. Legacy modules still contain other configuration defaults; consolidation is not finished.

The current `[general].offline_mode` key is informational until every network-capable tool has been migrated to a central network policy. Do not treat this flag as a verified network isolation switch.

`config/LUNA.md` is the non-personal LUNA persona file. User-specific vault content is intentionally not shipped. The historical Git repository may still contain old vault commits; follow [privacy history guidance](docs/PRIVACY_HISTORY.md).

## Resource proof (measure, don't assume)

AURIX has **targets**, not verified resource guarantees. To measure a running AURIX process:

```powershell
pip install psutil
python scripts/resource_proof.py --pid <AURIX_PROCESS_PID> --seconds 60 --csv resource-proof.csv
```

The report measures the chosen process tree's RSS and CPU, plus system-wide GPU usage/VRAM when NVML is available. It does not claim per-process VRAM ownership or enforce limits.

## Testing and CI

`pytest` and `cargo test --workspace` are run in Windows GitHub Actions; a frontend compilation job is also included. The security regression tests cover unauthorized loopback clients, bad hosts, browser Origins and vault path containment. Passing CI is not equivalent to full security testing.

## License

MIT — see [LICENSE](LICENSE).

## Known limitations and participation

This repo is an in-progress project. Contributions should not introduce fake model progress, hardcoded user paths, secrets, tracked personal memory or unsupported claims of offline operation. New external or destructive tool capabilities must have an auditable trusted-user authorization mechanism.

## Windows installer preview (unsigned, unverified)

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
