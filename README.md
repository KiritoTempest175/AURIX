# LUNA — Autonomous Desktop Executive

> **LUNA (Autonomous Universal Reasoning & Interaction Executive v0.2.0)**  
> A Gemma-Powered, Self-Training, JARVIS-Style Desktop AI Agent for Windows & Edge Environments.

---

## 🌟 Key Capabilities

- **Offline Wake-Word Activation:** Wakes on the spoken keyword **"Luna"** with confirmation echo protection ("Yes? Go ahead.") before acting on utterances.
- **Dual-Model Cognitive Architecture:**
  - **Gemma 3n E4B:** Primary reasoning brain for intent parsing, tool selection, and code generation loaded in 4-bit NF4 (with elastic `E2B`/`E4B` execution switch).
  - **Luna-Student-5B:** Continuous personal student model trained via QLoRA on the user's real interaction telemetry.
- **Adaptive Idle-Aware Power Governor v2:**
  - Automatically transitions between `ACTIVE` (conservative limits), `IDLE` (boosted training ceilings), `LOCKED` (full-throttle background training), and `SUSPENDING` (safe state hibernation).
- **Secure Encrypted Checkpointing:**
  - Versioned snapshots with AES-256-GCM encryption at rest, atomic pointer file writes, integrity manifests, and 3-version automatic rollback.
  - Training is explicitly toggled by the user in the UI — never auto-started silently.
- **Hardened Security Sandbox:**
  - Path canonicalization file jail, scoped action categories, secret scrubbing (regex + Shannon entropy), and append-only audit trail enforcement.

---

## 🛠 Target Hardware Profile

All resource limits are tuned for smooth operation on standard developer hardware:
- **Host RAM:** 16.0 GB Total (12.0 GB Active Ceiling / 13.5 GB Idle Ceiling)
- **Discrete GPU:** NVIDIA RTX 4060 8.0 GB VRAM (6.0 GB Active Ceiling / 7.0 GB Idle Ceiling)
- **All thresholds are fully configurable in `config/luna.toml`.**

---

## 🚀 Quick Start

### 1. Build Core Rust Engine
```powershell
.\scripts\build_engine.ps1
# Or:
cargo build --manifest-path core_engine/Cargo.toml --release
Copy-Item target/release/core_engine.dll core_engine.pyd
```

### 2. Launch LUNA Command Center GUI
```powershell
.\scripts\run_luna.ps1
# Or:
python native_ui/run_ui.py
```

### 3. Run Test Suites
```powershell
.\scripts\run_tests.ps1
# Or individually:
python tests/run_all_tests.py
cargo test --workspace
```

---

## 📁 Repository Structure

```
luna/
├── config/
│   ├── luna.toml                  # Central system configuration
│   └── luna.schema.json           # JSON Schema validator
├── core_engine/                   # Rust 2021 Systems Core
│   ├── src/
│   │   ├── governor/              # Adaptive Power Governor v2 & Idle Monitor
│   │   ├── sandbox/               # File Jail path canonicalization
│   │   ├── observers/             # Windows UIA Tree & PTY Interceptor
│   │   └── ffi/                   # PyO3 Native Bindings
│   └── Cargo.toml
├── ai_engine/                     # PyTorch & Unsloth AI Subsystems
│   ├── inference/
│   │   └── gemma_e4b.py           # Gemma 3n E4B Foundation Model Runner
│   ├── training/
│   │   ├── student_qlora_loop.py  # Student-5B Continuous QLoRA Loop
│   │   ├── memory_manager.py      # Graceful VRAM Eviction Manager
│   │   └── checkpoint_manager.py  # Encrypted Atomic Checkpoint Manager
│   └── models/
├── data_pipeline/                 # Dual Storage & Self-Healing
│   ├── storage/                   # SQLite & DuckDB Schemas & Daemons
│   ├── vector_store/              # ChromaDB & FAISS Vector Index
│   └── self_healing/              # Traceback Analyzer & Self-Healing Loop
├── native_ui/                     # Slint 1.8 Desktop Interface & Audio
│   ├── ui/                        # Declarative .slint GUI files
│   ├── audio/                     # Whisper STT, Piper TTS & Wake-Word Detector
│   └── run_ui.py                  # Python GUI Controller
├── security/                      # Cryptography, Secret Scrubber, Permissions
├── tests/                         # Python & Rust Test Suites
│   ├── python/
│   └── rust/
├── docs/                          # Comprehensive Technical Documentation
│   ├── ARCHITECTURE.md
│   └── SECURITY.md
├── scripts/                       # PowerShell build and run scripts
├── CHANGELOG.md
├── LICENSE
└── README.md
```

---

## 📄 License
Licensed under the [MIT License](LICENSE).
