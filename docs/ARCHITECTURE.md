# LUNA — System Architecture Specification

## 1. Overview & Vision
**LUNA (Autonomous Universal Reasoning & Interaction Executive v2.0)** is an edge-governed, air-gapped, voice-and-text-activated desktop AI executive. Operating as a personal JARVIS on the user's PC, LUNA features:
- **Dual-Model Paradigm:**
  1. **Gemma 3n E4B:** Primary reasoning and tool-use foundation model loaded in 4-bit NF4 with elastic E2B/E4B execution.
  2. **Luna-Student-5B:** Continuous personal student model trained via QLoRA on live user interaction traces.
- **Adaptive Power/Resource Governor v2:** Idle-aware state engine monitoring user input, session locks, host RAM, GPU VRAM, and thermals.
- **Secure Checkpointing & Hibernation:** Atomic, encrypted checkpoint persistence (AES-256-GCM) with 3-version rollback.
- **Offline Wake-Word Engine:** Spoken keyword activation ("Luna") with confirmation echo protection.
- **Bare-Metal Safety Sandbox:** File jail path canonicalization, PTY execution, and interactive Trust Token authorization.

---

## 2. Tri-Tier Topology

```
+-------------------------------------------------------------------------+
|                         NATIVE UI & AUDIO TIER                          |
|  Slint 1.8 Command Center  |  Whisper STT (16kHz)  |  Piper Neural TTS  |
|  Offline Wake-Word Detector ("Luna") | Start/Stop Training Toggle       |
+------------------------------------+------------------------------------+
                                     | (In-Process PyO3 / C-ABI)
+------------------------------------v------------------------------------+
|                         CORE ENGINE (RUST 2021)                         |
|  Adaptive Power Governor (Active / Idle / Locked / Suspending)          |
|  File Jail Path Canonicalization  |  UIA Tree COM  |  Headless PTY      |
+------------------------------------+------------------------------------+
                                     | (Zero-Cost Atomic Memory)
+------------------------------------v------------------------------------+
|                      AI ENGINE & DATA PIPELINE                          |
|  Gemma 3n E4B Inference Engine  |  Luna-Student-5B QLoRA Training Loop  |
|  CheckpointManager (AES-256-GCM)|  Secret Scrubber Redaction Engine     |
|  SQLite WAL Telemetry Log       |  DuckDB Analytical Query Engine       |
+-------------------------------------------------------------------------+
```

---

## 3. Adaptive Power Governor v2

| State | Trigger Criteria | Governor Policy |
|---|---|---|
| **ACTIVE** | Foreground window input / mouse movement | Training throttled (Micro-batch 1, LoRA Rank 16, RAM $\le$ 12 GB, VRAM $\le$ 6 GB). Inference prioritized. |
| **IDLE** | No keyboard/mouse input for $\ge 300\text{s}$ | Ceilings raised (LoRA Rank 32, RAM $\le$ 13.5 GB, VRAM $\le$ 7.0 GB). Background SFT boosted. |
| **LOCKED** | Windows workstation locked (`Win+L`) | Full-throttle continuous training up to absolute hardware ceilings (RAM $\le$ 14 GB, VRAM $\le$ 7.2 GB). |
| **SUSPENDING** | OS shutdown / sleep / hibernate signal | Emergency checkpoint persisted, WAL flushed, VRAM released within grace period. |

---

## 4. Checkpoint Persistence & Rollback Architecture

Checkpoints are persisted in versioned directories:
```
checkpoints/luna-student/
├── latest_checkpoint.json          # Atomic pointer file (tempfile + fsync + rename)
├── ckpt_20260901_221500_a1b2c3d4/  # Versioned snapshot directory
│   ├── adapter_model.bin           # AES-256-GCM encrypted adapter weights
│   ├── training_state.json         # Optimizer / RNG / step state
│   └── manifest.json               # SHA-256 hash, ISO timestamp, step count, metrics
└── ...
```

---

## 5. Security & Containment Model
- **File Jail:** Path canonicalization ensures all file reads/writes reside within configured `allowed_project_paths`.
- **Trust Tokens:** Cryptographic approval tokens required for file deletion, system settings, and checkpoint restorations.
- **Secret Scrubbing:** Regex + Shannon entropy detection scrubs credentials from telemetry and training sets.
