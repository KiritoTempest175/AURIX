---
title: Project Dossier — AURIX Desktop AI Executive
created: 2026-09-12
updated: 2026-09-12
tags: [project, aurix, architecture, rust, python, ai]
---

# Project Dossier — AURIX Desktop AI Executive

## 1. Overview
* **Name:** AURIX (Autonomous Universal Reasoning & Interaction eXecutive)
* **Status:** Active Development (v0.2.0)
* **Lead Architect:** [[people/huzaifa|Huzaifa]]
* **Repository Path:** `E:\AURIX`
* **Core Technologies:** Python 3.10+, Rust 2021, PyTorch 2.2+, PyO3, Whisper GGML, Piper TTS, Unsloth/Transformers

---

## 2. Key Architecture Subsystems

1. **Native UI & Audio (`native_ui/`, `frontend.py`):**
   * Cyberpunk Tkinter desktop HUD with rotating holographic radar, live meters, waveform visualizer.
   * Offline wake-word detection ("Luna" / "Aurix") + Piper TTS + Whisper STT.
2. **Bare-Metal Core Engine (`core_engine/`):**
   * High-performance Rust 2021 systems library.
   * Adaptive Power Governor v2 managing thermal ceilings and 4-tier activity states.
   * Safe file-jail containment and zero-cost atomic memory.
3. **AI Engine & Inference (`ai_engine/`):**
   * Priority multi-model auto-resolver (Ollama Qwen 2.5 3B, Gemma 4 E4B NF4, Qwen Coder).
   * Student-5B Continuous QLoRA background training loop.
4. **AI Brain & Automation (`ai_brain/`):**
   * App control, WhatsApp Desktop automation, media player, email dispatcher, file operator.
5. **Knowledge Vault (`aurix_vault/`):**
   * Local Obsidian markdown vault for persistent long-term memory, episodic logs, and model guidelines.

---

## 3. Related Links
* [[model|Luna Model Specification]]
* [[commands|Commands Manual]]
* [[tools|Tools Registry]]
* [[goals|Strategic Goals]]
