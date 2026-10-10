# AURIX — Autonomous Universal Reasoning & Interaction Executive

AURIX is an **experimental Windows desktop AI assistant**. The application UI is built with React 18, Vite and Tauri 2; the current AI worker and automation tools are written in Python, with Windows-focused Rust native modules. The conversational AI agent is named **LUNA**.

> **Release status: development preview, not a production-safe autonomous agent.** The security hardening in this repository is partial. Do not run the app with administrator privileges or allow untrusted users to access its environment.

## Implemented in the current repository

- Local desktop chat routed to a Python agent when a supported model and runtime are available.
- Rust and Python telemetry for CPU/RAM. GPU figures are explicitly reported as unavailable in the frontend until a verified NVML integration is connected.
- Desktop application and file tool implementations with action-level permission requests.
- Single-use, fingerprint-bound pending action tokens, with a Windows native confirmation dialog for requests made through the Tauri UI.
- Session-secret-authenticated **localhost-only HTTP** between Tauri and the Python worker. Browser-origin requests and arbitrary hosts are rejected; JavaScript does not receive the token.
- Encryption/checkpoint code, secret scrubbing, SQLite-based telemetry tools, Markdown memory management and automated Python/Rust tests.
- QLoRA training code exists, **but the currently exposed StudentTrainingController still simulates training**; it does not constitute proof of active learning.

## Not yet implemented or validated

- A bundled Python sidecar, one-click standalone installer, auto-updater, full first-run onboarding.
- Authenticated Windows named-pipe IPC; the loopback HTTP transport is temporary.
- A real microphone-connected voice control button in the React UI. It explicitly reports unavailability rather than simulated captured speech.
- A Windows restricted-token/Job-Object command sandbox; model-generated `shell_exec` is **disabled** until this exists.
- Embedded GGUF/llama.cpp-only model runtime; current code still uses Transformers and has legacy Ollama adapter code.
- A verified 6 GB **per-application** VRAM / 12 GB RAM hard cap, GPU telemetry integration, idle <150 MB resource guarantee, and live training.
- Complete role-based tool SDK, rollback/undo, persistent native approval audit, memory explorer, signed installer, and independent security assessment.
- Online communications and software-installation workflows require explicit review; no guarantee is made that every action is fully offline.

See [implementation status](docs/IMPLEMENTATION_STATUS.md) and [security model](docs/SECURITY.md) before using OS automation.

## Requirements

Windows 10/11, Python 3.10+, Node.js 22+, a compatible Rust toolchain and the Tauri Windows prerequisites. Model inference, speech and GPU training have their own optional native/dependency requirements. CPU-only fallback is limited and may use deterministic responses; it is **not** a substitute for a real local LLM.

## Development setup

```powershell
git clone https://github.com/KiritoTempest175/AURIX.git
cd AURIX
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cd frontend
npm install
npm run tauri dev
```

The Tauri development launcher attempts to start `frontend/bridge_server.py` using `python` or `python3` on PATH. Launching `npm run dev` **only runs the Vite browser preview**, where actions are unavailable. The packaged desktop binary is **not yet self-contained**. If the worker is missing, the UI will show it as unavailable.

Optional native engine build from the repo root:

```powershell
.\scripts\build_engine.ps1
cargo test --workspace
pytest
```

Do **not** enable public binding for the Python bridge. Its token is generated and supplied by Tauri at launch. Running `python frontend/bridge_server.py` directly refuses startup without this token.

## Configuration

`config.toml` is the active file for the central tool executor. Configure `security.allowed_project_paths` for workspace access. Empty trusted roots mean writes require explicit authorization and other Python file reads remain restricted to standard user folders. Legacy modules still contain other configuration defaults; consolidation is not finished.

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
