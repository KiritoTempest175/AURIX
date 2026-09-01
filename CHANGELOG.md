# LUNA Project Changelog

All notable changes to the LUNA desktop AI executive are documented in this file.

## [0.2.0] - 2026-09-01 — Evolution from AURIX to LUNA

### Added
- **Dual-Model Reasoning & Training Paradigm:**
  - Integrated **Gemma 3n E4B** as primary reasoning brain with elastic `E2B`/`E4B` execution.
  - Added **Luna-Student-5B** continuous QLoRA personal training loop with rank auto-scaling (16 in Active $\to$ 32 in Idle).
- **Adaptive Power/Resource Governor v2:**
  - Idle detection via Windows `GetLastInputInfo` and session lock polling.
  - Four distinct power states: `ACTIVE`, `IDLE`, `LOCKED`, `SUSPENDING`.
  - Dynamic RAM/VRAM ceilings and GPU thermal throttling ($82^\circ\text{C}$).
- **Encrypted Atomic Checkpoint Manager:**
  - Versioned checkpoint directory structure (`checkpoints/luna-student/ckpt_<timestamp>_<hash>/`).
  - AES-256-GCM authenticated encryption at rest.
  - Manifest generation with dataset hashes, step counts, and metrics.
  - Atomic `latest_checkpoint.json` pointer file updates and automatic 3-version rollback.
- **Offline Wake-Word Detection:**
  - Local keyword spotting for **"Luna"** with confirmation echo ("Yes? Go ahead.") to mitigate false activations.
- **Security Hardening (`security/`):**
  - Scoped action category permissions and Trust Token enforcement.
  - Regular expression + Shannon entropy secret scrubber redacting credentials from telemetry and datasets.
  - Append-only database triggers on `security_audit_trails`.
- **Slint 1.8 Dashboard Enhancements:**
  - Front-panel **Start / Stop Training** toggle switch with live telemetry (Step, PowerState, LoRA Rank, RAM/VRAM).
  - Checkpoint Browser modal for inspecting and restoring snapshots.
  - Wake-word status indicator dot.

### Changed
- Centralized configuration into `config/luna.toml` validated by `config/luna.schema.json`.
- Restructured core engine FFI bindings into `core_engine/src/ffi/`.
- Reorganized test suites into `tests/python/` and `tests/rust/`.
