# AURIX — Autonomous Universal Reasoning & Interaction eXecutive

<p align="center">
  <img src="https://img.shields.io/badge/AURIX-v0.2.0-00f0ff?style=for-the-badge&logo=electron&logoColor=white" alt="AURIX Version" />
  <img src="https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078d4?style=for-the-badge&logo=windows&logoColor=white" alt="Platform" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776ab?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Rust-2021%20Edition-dea584?style=for-the-badge&logo=rust&logoColor=white" alt="Rust" />
  <img src="https://img.shields.io/badge/PyTorch-2.2%2B-ee4c2c?style=for-the-badge&logo=pytorch&logoColor=white" alt="PyTorch" />
  <img src="https://img.shields.io/badge/Security-Air--Gapped%20%7C%20Zero--Cloud-brightgreen?style=for-the-badge&logo=shield" alt="Air-Gapped" />
  <img src="https://img.shields.io/badge/License-MIT-blue?style=for-the-badge" alt="License" />
</p>

---

## 📑 Table of Contents

- [Overview & Philosophy](#-overview--philosophy)
- [Key Capabilities](#-key-capabilities)
- [System Architecture](#-system-architecture)
- [AI Brain & Desktop Automation](#-ai-brain--desktop-automation)
- [Adaptive Power Governor v2](#-adaptive-power-governor-v2)
- [Continuous Learning & Checkpoints](#-continuous-learning--checkpoints)
- [Hardware Profiles & Requirements](#-hardware-profiles--requirements)
- [Installation & Setup](#-installation--setup)
- [Quick Start](#-quick-start)
- [Configuration Reference](#-configuration-reference)
- [Repository Structure](#-repository-structure)
- [Security & Sandbox Model](#-security--sandbox-model)
- [Troubleshooting & FAQs](#-troubleshooting--faqs)
- [License & Credits](#-license--credits)

---

## 🌌 Overview & Philosophy

**AURIX (Autonomous Universal Reasoning & Interaction eXecutive)** is a state-of-the-art, air-gapped, voice-and-text-activated desktop AI executive designed natively for Windows. Operating as a private, on-device JARVIS, AURIX seamlessly bridges high-level cognitive reasoning, bare-metal hardware governance, local desktop automation, and autonomous continuous learning—**without transmitting private telemetry, code, or personal data to third-party cloud servers**.

### Why AURIX?
- **100% On-Device & Air-Gapped:** Your files, logs, voice recordings, and weights stay strictly on your local NVMe/SSD.
- **Dual-Model Cognitive Architecture:** Uses an agile local foundation brain for high-speed inference while simultaneously training a continuous personal student model via QLoRA.
- **Native Bare-Metal Systems Core:** Powered by high-performance Rust 2021 systems code compiled to native `.pyd` FFI for microsecond-level hardware control, process management, and sandbox containment.
- **True Desktop Automation:** Controls real Windows applications, chats and calls on WhatsApp Desktop, manages media and emails, indexes local folders, and operates your Obsidian-compatible knowledge vault.
- **Adaptive Power Awareness:** Respects your machine's hardware limits. Automatically dials back during intensive gaming/development and boosts background learning when your workstation is idle or locked.

---

## 🌟 Key Capabilities

### 1. Foundation Model Intelligence & Auto-Resolver
- **Smart Model Resolver:** Dynamically discovers available LLMs on your workstation across local Hugging Face caches and local model directories.
- **Primary Foundation Model:**
  - `google/gemma-4-E4B-it` *(Google Gemma 4 E4B — Elastic 4-bit NF4 foundation model)*
- **Self-Healing Download:** Automatically downloads Gemma 4 E4B model checkpoints if no local weights are detected.

### 2. Hands-Free Voice & Audio Pipeline
- **Offline Wake-Word Detection:** Listens continuously for the spoken wake keyword (**"Luna"** or **"Aurix"**) with confirmation echo protection (*"Yes? Go ahead."*) to prevent accidental triggers.
- **Whisper Speech-to-Text (STT):** Local 16kHz GGML multi-threaded voice transcription with adaptive silence detection and energy thresholding.
- **Piper Neural Text-to-Speech (TTS):** Ultra-fast, natural-sounding voice synthesis with customizable speech rates and female/male voice models.
- **Startup Welcome Greeting:** Personalized startup vocalization and status report (`welcome_config.json`).

### 3. AI Brain & Desktop Controllers
- **WhatsApp Desktop Controller:** Automates contact searching, dynamic message composition, chat opening, and voice/video calling using 64-bit safe clipboard injection and Windows UI Automation (UIA).
- **Application & Window Manager:** Launches, switches, minimizes, and terminates desktop applications with intelligent fuzzy process matching.
- **File System Operator:** Path-jailed file reading, writing, editing, renaming, moving, and searching.
- **Media & Volume Control:** Native Windows master volume adjustment, playback play/pause/skip, and Spotify desktop integration.
- **Email Dispatcher:** Automated email drafting, formatting, and client routing.
- **Obsidian Aurix Vault:** Interacts directly with local markdown knowledge bases for long-term episodic memory.

### 4. Rust Systems Core & Power Governor v2
- **4-Tier State Machine:** Automatically transitions between `ACTIVE`, `IDLE`, `LOCKED`, and `SUSPENDING` based on real-time Windows user input (`GetLastInputInfo`) and session lock polling (`Win+L`).
- **Dynamic Resource Ceilings:** Automatically scales LoRA rank (16 $\to$ 32), micro-batch sizes, and RAM/VRAM allocations.
- **Hardware Protection:** Enforces GPU thermal ceilings ($82^\circ\text{C}$) and initiates emergency checkpoints upon OS suspend/hibernation signals.

### 5. Continuous Local Learning & Checkpointing
- **Student-5B Continuous QLoRA:** Progressively trains a personal student model on a balanced 70/30 experience replay buffer:
  - **70% Synthetic Curriculum:** High-quality in-memory engineering problems generated without touching private user files.
  - **30% User Telemetry:** Scrubbed, sanitized real interaction traces.
- **Encrypted Atomic Checkpoints:** Checkpoints are encrypted at rest with **AES-256-GCM**, written atomically via pointer files, and guarded by an automated 3-version rollback safety net.

### 6. React + Tauri v2 Desktop Shell
- Modern desktop command center (`frontend/`) built with React, Vite, and Tauri v2 featuring:
  - Animated orb centerpiece with orbital ring animations.
  - Live system telemetry: CPU, RAM, GPU usage, and thermal monitoring.
  - Live audio waveform and voice status indicators (Standby / Listening / Processing).
  - Integrated chat panel wired to the AURIX AI brain via a Python bridge server.
  - Glassmorphism panels with dark navy + gold accent design system.

---

## 🏗 System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           NATIVE UI & AUDIO TIER                            │
│  React + Tauri Desktop Shell          │  Whisper STT (16 kHz Local GGML)     │
│  Piper Neural TTS Engine              │  Offline Wake-Word Detector         │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ (Direct In-Process / PyO3 FFI)
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                           CORE ENGINE (RUST 2021)                           │
│  Adaptive Power Governor v2 (Active / Idle / Locked / Suspending)           │
│  Hardware Monitor (psutil / NVML)     │  Windows UIA Observers & PTY        │
│  Bare-Metal File Jail Sandbox         │  Zero-Cost Atomic Memory            │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                         AI ENGINE & DATA PIPELINE                           │
│  ┌────────────────────────┐  ┌───────────────────────────────────────────┐  │
│  │ Model Resolver         │  │ Student-5B Continuous QLoRA Loop          │  │
│  │ • Gemma 4 E4B (4-bit)  │  │ • 70/30 Experience Replay Buffer          │  │
│  │ • NF4 Quantization     │  │ • In-Memory Synthetic Data Generator      │  │
│  │ • Hugging Face Cache   │  │ • AES-256-GCM Checkpoint Manager          │  │
│  └────────────────────────┘  └───────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ AI Brain Dispatcher: App Control • WhatsApp • File • Media • Email    │  │
│  │ Aurix Vault (Obsidian) • Secret Scrubber • SQLite WAL • DuckDB Logs   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🧠 AI Brain & Desktop Automation

The `ai_brain/` subsystem exposes unified tool dispatching for natural language intent execution:

| Controller | Purpose & Mechanics | Example Commands |
|---|---|---|
| **App Control** (`app_control.py`) | Launches, focuses, minimizes, and controls Windows desktop apps via process tree and UIA inspection. | *"Open VS Code"*, *"Minimize Discord"*, *"Focus Chrome"* |
| **Message Control** (`message_control.py`) | Controls WhatsApp Desktop: navigates chats, injects text safely via 64-bit clipboard, sends messages, and triggers voice/video calls. | *"Send a WhatsApp message to Alex saying I'll be there in 10 minutes"*, *"Call Mom on WhatsApp"* |
| **File Control** (`file_control.py`) | Sandboxed file system operations (read, write, delete, search, move, list) within canonicalized project boundaries. | *"Find all python scripts modified today"*, *"Read config.toml"* |
| **Media Player** (`media_player.py`) | Windows multimedia control, master volume adjustments, Spotify track playback and pausing. | *"Play music"*, *"Pause playback"*, *"Set volume to 50%"* |
| **Email Control** (`email_control.py`) | Composes and launches email drafts with recipient, subject, and body pre-populated. | *"Draft an email to supervisor about project milestones"* |
| **Web Search** (`web_search.py`) | Air-gapped / local-friendly search query synthesis and DuckDuckGo scraping. | *"Search the web for the latest PyTorch 2.5 release notes"* |
| **Aurix Vault** (`aurix_vault/`) | Direct bi-directional integration with an Obsidian markdown vault for persistent notes and memory. | *"Save this snippet to my vault"*, *"Check notes on architecture"* |

---

## ⚡ Adaptive Power Governor v2

The Power Governor monitors system load and user engagement to dynamically allocate hardware resources:

| Power State | Trigger Condition | Governor Policy & Hardware Quotas |
|---|---|---|
| **`ACTIVE`** | Foreground user keyboard/mouse activity detected | **Inference prioritized.** Background training throttled (Micro-batch 1, LoRA Rank 16). Host RAM $\le$ 12.0 GB, VRAM $\le$ 6.0 GB. |
| **`IDLE`** | No keyboard or mouse activity for $\ge 300\text{ s}$ | **Training ceilings boosted.** LoRA Rank 32, increased batch size. Host RAM $\le$ 13.5 GB, VRAM $\le$ 7.0 GB. |
| **`LOCKED`** | Windows workstation locked (`Win + L`) | **Full-throttle autonomous learning.** Maximum hardware capacity utilized (Host RAM $\le$ 14.0 GB, VRAM $\le$ 7.2 GB). |
| **`SUSPENDING`** | OS shutdown, sleep, or hibernate signal | **Emergency save.** Checkpoint committed to disk, SQLite WAL flushed, VRAM gracefully released. |

> [!NOTE]
> GPU thermals are continuously monitored. If the GPU junction temperature exceeds **$82^\circ\text{C}$**, training steps are paused until the GPU cools down below $75^\circ\text{C}$.

---

## 🔄 Continuous Learning & Checkpoints

```
checkpoints/luna-student/
├── latest_checkpoint.json            # Atomic pointer file (tempfile + fsync + rename)
├── ckpt_20260901_221500_a1b2c3d4/    # Snapshot directory
│   ├── adapter_model.bin             # AES-256-GCM encrypted QLoRA weights
│   ├── training_state.json           # Optimizer, scheduler, step count, RNG seeds
│   └── manifest.json                 # SHA-256 integrity hash & performance telemetry
└── ...
```

- **Replay Balancing:** Telemetry is compiled with **70% in-memory synthetic engineering exercises** and **30% real user interaction data**.
- **Privacy Guarantee:** The synthetic data generator never reads the user's private files, source trees, or personal notes.
- **Rollback Guarantee:** If evaluation loss diverges or an encrypted checkpoint fails SHA-256 validation, AURIX automatically rolls back up to 3 prior verified snapshots.

---

## 💻 Hardware Profiles & Requirements

| Component | Minimum Specification | Recommended Specification |
|---|---|---|
| **Operating System** | Windows 10 (64-bit, 21H2+) | Windows 11 (64-bit, 23H2+) |
| **Processor (CPU)** | 4 Cores / 8 Threads (Intel Core i5 / AMD Ryzen 5) | 8 Cores / 16 Threads (Intel Core i7 / AMD Ryzen 7) |
| **System Memory (RAM)** | 16 GB DDR4 | 32 GB DDR4 / DDR5 |
| **Graphics (GPU)** | NVIDIA GTX 1660 / RTX 3050 (6 GB VRAM) | NVIDIA RTX 4060 / 4070+ (8 GB+ VRAM) |
| **Storage** | 20 GB free space (SSD required) | 50 GB free NVMe M.2 SSD |
| **Microphone / Audio** | Standard input device | Dedicated directional USB microphone |

*Note: AURIX can also operate in pure CPU mode using Ollama for lightweight environments.*

---

## 📦 Installation & Setup

### 1. Prerequisites
Ensure the following tools are installed on your Windows workstation:
1. **Python 3.10 or 3.11** (standard CPython installer with `tcl/tk` enabled).
2. **Rust Toolchain (Cargo 1.75+)**: Install via [rustup.rs](https://rustup.rs/).
3. **C++ Build Tools for Windows**: Visual Studio C++ Build Tools (MSVC).
4. *(Recommended)* **Ollama**: Download from [ollama.ai](https://ollama.ai/) for high-speed local model execution.

### 2. Clone the Repository
```powershell
git clone https://github.com/YourUsername/AURIX.git
cd AURIX
```

### 3. Create and Activate Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 4. Install Python Dependencies
```powershell
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e .
```

### 5. Build Core Rust Engine
Compile the native systems core and produce the `core_engine.pyd` native library:
```powershell
.\scripts\build_engine.ps1
```
*Or manually:*
```powershell
cargo build --manifest-path core_engine/Cargo.toml --release
Copy-Item core_engine/target/release/core_engine.dll core_engine.pyd
```

### 6. Verify or Download Foundation Model (Gemma 4 E4B)
```powershell
python scripts/download_gemma.py
```
*(Alternatively, AURIX will automatically download Gemma 4 E4B weights on first boot).*

---

## 🚀 Quick Start

### Launch the AURIX Desktop Shell
```powershell
cd frontend
npm install
npm run dev
```
*This starts the Vite dev server at http://localhost:1420 and auto-spawns the Python bridge server.*

*To run as a native desktop app (requires Rust toolchain + Tauri prerequisites):*
```powershell
cd frontend
npm run tauri dev
```

### Run Comprehensive Test Suite
```powershell
.\scripts\run_tests.ps1
```
*Or run individual Python and Rust test harnesses:*
```powershell
# Python unit and integration tests
pytest tests/ -v

# Rust core engine tests
cargo test --manifest-path core_engine/Cargo.toml
```

### Dedicated Voice & Speech Scripts
```powershell
# Listen for the offline wake-word ("Luna" / "Aurix")
.\scripts\wakeword_listener.ps1

# Test speech recognition
.\scripts\speech_listen.ps1

# Test neural text-to-speech output
.\scripts\speech_speak.ps1
```

---

## ⚙️ Configuration Reference

### `config.toml`
Central system configuration defining permissions, audio devices, resource bounds, and LLM backends:

```toml
[security]
allowed_project_paths = [
    "G:/Python Project/AURIX",
    "C:/Users/YourName/Projects"
]
file_jail_enabled = true
read_only_mode = false
trust_token_required = true

[audio]
microphone = "Default"
whisper_model_path = "models/whisper/ggml-base.en.bin"
whisper_language = "en"
silence_limit = 2.2
min_speech_duration = 0.8
auto_tts_reply = true
piper_model_path = "models/piper/en_US-lessac-medium.onnx"
piper_speed = 1.00

[resources]
max_ram_gb = 16.0
max_vram_gb = 6.0
cpu_throttle_percent = 85.0
poll_interval_ms = 1000
suspend_on_overload = true

[llm]
model_name = "google/gemma-4-E4B-it"
model_alias = "Gemma 4 E4B (4-bit NF4, GPU)"
effective_params = "E4B"
max_seq_length = 2048
load_in_4bit = true
quantization = "nf4"
device = "cuda"
temperature = 0.7
top_p = 0.9
```

### `welcome_config.json`
Customizes the speech greeting vocalized by AURIX upon startup:

```json
{
  "greeting": "Welcome back,",
  "name": "Sir",
  "message": "all systems are online and ready for your command."
}
```

---

## 📁 Repository Structure

```
AURIX/
├── ai_brain/                      # Central Brain & Desktop Tool Controllers
│   ├── app_control.py             # Windows Application & Process Manager
│   ├── dispatcher.py              # Central Intent Router & Execution Engine
│   ├── email_control.py           # Email Drafting & Dispatch Controller
│   ├── file_control.py            # Path-Jailed File Operations & Search
│   ├── media_player.py            # Master Volume & Media Controls (Spotify)
│   ├── message_control.py         # WhatsApp Desktop Automation (UIA)
│   ├── tool_schema.py             # LLM Function Calling JSON Schemas
│   └── web_search.py              # Local/DuckDuckGo Query Scraper
├── ai_engine/                     # Local Inference & Continuous Learning
│   ├── inference/
│   │   ├── gemma_e4b.py           # Gemma 4 / Foundation Model Inference Runner
│   │   └── model_resolver.py      # Automatic Model Discovery & Download Cascade
│   └── training/
│       ├── checkpoint_manager.py  # AES-256-GCM Encrypted Checkpoint Manager
│       ├── memory_manager.py      # Adaptive VRAM Allocator & Eviction Manager
│       ├── qlora_loop.py          # Continuous QLoRA Fine-Tuning Loop
│       ├── student_qlora_loop.py  # Student-5B Autonomous Training Controller
│       └── synthetic_generator.py # In-Memory Privacy-Preserving Synthetic Generator
├── aurix_vault/                   # Obsidian-Compatible Local Knowledge Base
├── core_engine/                   # Native Rust 2021 Systems Core
│   ├── src/
│   │   ├── governor/              # 4-State Adaptive Power Governor v2
│   │   ├── observers/             # Windows UIA Event Trees & PTY Interceptors
│   │   ├── sandbox/               # Path Canonicalization File Jail
│   │   └── ffi/                   # PyO3 Python Native Bindings
│   └── Cargo.toml                 # Rust Package Manifest
├── data_pipeline/                 # Dual-Storage & Telemetry Pipeline
│   ├── compiler/                  # 70/30 Experience Replay Buffer Compiler
│   ├── self_healing/              # Error Diagnostics & Self-Healing Loop
│   ├── storage/                   # SQLite (WAL) & DuckDB Analytical Storage
│   └── vector_store/              # ChromaDB & FAISS Semantic Index
├── native_ui/                     # Audio Subsystem & Neural Voice Pipeline
│   └── audio/                     # Whisper STT, Piper TTS & Wake-Word Detector
├── security/                      # Cryptography, Permissions & Sandboxing
│   ├── encryption.py              # AES-256-GCM & PBKDF2 Master Key Derivation
│   ├── permissions.py             # Scoped Action Categories & Trust Tokens
│   └── secret_scrubber.py         # Shannon Entropy & Regex Credential Redactor
├── docs/                          # Architecture & Security Documentation
│   ├── ARCHITECTURE.md            # In-Depth Systems Design Specification
│   └── SECURITY.md                # Sandboxing & Cryptographic Model
├── scripts/                       # PowerShell Automation Scripts
│   ├── build_engine.ps1           # Rust Core Build Script
│   ├── run_luna.ps1               # Main Application Launcher
│   └── run_tests.ps1              # Full Test Suite Executor
├── tests/                         # Python & Rust Test Suites
│   ├── python/                    # Subsystem Unit & Integration Tests
│   └── rust/                      # Native Core Engine Unit Tests
├── config.toml                    # Master Configuration File
├── frontend/                      # React + Vite + Tauri v2 Desktop Shell
│   ├── src/App.jsx                # Main UI (orb, nav, telemetry, chat)
│   ├── src/App.css                # Design system (dark navy, gold accent)
│   ├── src-tauri/                 # Tauri v2 Rust backend
│   └── bridge_server.py           # Python HTTP bridge to AI brain
├── pyproject.toml                 # Python Package Metadata & Build Configuration
├── requirements.txt               # Locked Dependencies
└── welcome_config.json            # Vocal Startup Greeting Configuration
```

---

## 🛡 Security & Sandbox Model

AURIX is engineered from the ground up to guarantee user safety:

1. **Path-Canonicalized File Jail:** The agent cannot inspect, read, or write to any directory outside of `allowed_project_paths` configured in `config.toml`. All symlinks, relative traversal sequences (`../`), and junction points are canonicalized.
2. **Trust Token Authorization:** Irreversible or high-risk operations—including file deletions, system shutdowns, shell script execution, and checkpoint rollbacks—require cryptographic Trust Token confirmation in the UI.
3. **Secret Scrubber & Shannon Entropy Redaction:** Every trace emitted into telemetry databases or used in fine-tuning is passed through an automated redaction engine:
   - Scans and redacts API keys (`sk-...`, `ghp_...`, `AKIA...`), bearer tokens, private keys, and passwords.
   - Detects and masks anomalous high-entropy strings ($H \ge 4.3$).
4. **Append-Only Immutable Audit Trails:** All tool executions, shell calls, and security authorizations are logged to SQLite with database triggers preventing retroactive record tampering or deletion.

---

## ❓ Troubleshooting & FAQs

### 1. `Cannot find module 'tomli'. Did you mean 'tomllib'?`
If you are running Python 3.11 or newer, `tomllib` is built into the standard library. AURIX automatically uses standard `tomllib` on Python 3.11+ and falls back to `tomli` on older versions. If you encounter this warning in your IDE/type-checker, ensure your IDE's Python interpreter is pointing to `.venv\Scripts\python.exe`.

### 2. `core_engine imported as namespace package — compiled .pyd not found`
The native Rust library has not yet been built for your Python environment. Run:
```powershell
.\scripts\build_engine.ps1
```
This compiles the Rust crate and copies `core_engine.pyd` to the project root.

### 3. Whisper / Piper Voice Models Missing
Voice models are downloaded automatically on first run, or you can invoke the download helper:
```powershell
python scripts/download_female_voice.py
```
Ensure your microphone is recognized as the default Windows recording device.

### 4. GPU Out-of-Memory (OOM) Errors
If running a larger model on a GPU with 6 GB or 8 GB VRAM, ensure:
- Alternatively, enable 4-bit NF4 quantization or toggle `effective_params = "E2B"` to minimize VRAM.

---

## 📄 License & Credits

Distributed under the **MIT License**. See [LICENSE](LICENSE) for full details.

Developed with ❤️ by the **AURIX Core Engineering Team**:
- **Huzaifa** — System Architecture & AI Brain
- **Saad** — Rust Systems Core & Hardware Governor
- **Zain** — Data Pipeline, Security & Audio Subsystem
