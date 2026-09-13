---
title: System & Environmental Facts
created: 2026-09-12
updated: 2026-09-12
tags: [memory, facts, environment, hardware, system]
---

# System & Environmental Facts

This file contains persistent, verified technical facts regarding the host workstation, environment configuration, software installations, and security boundaries.

---

## 1. Workstation & OS Telemetry

* **Operating System:** Microsoft Windows 11 (64-bit)
* **Shell Environment:** PowerShell / Windows Terminal
* **Primary Display:** High-DPI Desktop Monitor
* **Audio Input:** Default System Microphone (Sample rate: 16,000 Hz for Whisper STT)
* **Audio Output:** Default System Audio Output (Piper Neural TTS, voice: `en_US-lessac-medium.onnx`)

---

## 2. Hardware Resource Constraints & Quotas

Configured in `config.toml`:

| Metric | Configured Ceiling | Safe Operating Baseline |
|---|---|---|
| **Max RAM** | 16.0 GB | Host usage monitored via `psutil` |
| **Max VRAM** | 6.0 GB | GPU VRAM monitored via NVML / PyTorch |
| **CPU Throttle** | 85.0% | Power governor throttles background jobs |
| **GPU Thermal Ceiling** | 82.0°C | Triggers thermal cooldown & suspend |
| **Suspend on Overload** | `true` | Emergency state preservation |

---

## 3. Security & Sandboxing Constraints

* **File Jail:** Enabled (`file_jail_enabled = true`)
* **Trust Token:** Required for external communications and direct terminal shell execution (`trust_token_required = true`)
* **Canonical Allowed Paths:**
  1. `E:/AURIX` (Main project repository)
  2. `G:/Websites By Ai/AURIX`
  3. `C:/Users/Zain/Projects`
* **Restricted / Forbidden Boundaries:**
  * `C:\Windows` and all subdirectories
  * Windows Registry hives (`HKLM`, `HKCU`)
  * System32 and EFI boot partitions

---

## 4. Installed AI Models & Checkpoints

* **Primary Foundation LLM:** `google/gemma-4-E4B-it` (4-bit NF4 quantized, GPU accelerated via Unsloth/PyTorch)
* **STT Model:** `models/whisper/ggml-base.en.bin` (GGML 16kHz)
* **TTS Model:** `models/piper/en_US-lessac-medium.onnx`
