---
title: User Preferences & Customization Guidelines
created: 2026-09-12
updated: 2026-09-12
tags: [memory, preferences, ui, audio, communication]
---

# User Preferences & Customization Guidelines

This document records the user-specific habits, aesthetic preferences, and operational defaults preferred by **Huzaifa**.

---

## 1. Interaction & Communication Style

* **Brevity:** High. Default to 1-sentence confirmations for routine actions (*"VS Code launched"*, *"Volume set to 40%"*).
* **Tone:** Professional, calm, crisp. Zero hollow pleasantries (*"Have a great day!"*, *"I am happy to assist you"*).
* **Confirmations:** Only confirm for Tier 2 irreversible actions (WhatsApp, calls, emails, file deletes, destructive commands). Never ask for confirmation on Tier 1 tasks.
* **Error Handling:** When a tool encounters an issue, state: (1) what failed, (2) why, (3) the immediate next option. Do not dump raw stack traces unless specifically asked to debug.

---

## 2. Desktop & UI Preferences

* **Color Palette / Theme:** Dark mode, cyberpunk cyan/neon blue accent (`#00f0ff`), deep graphite background (`#0d1117`).
* **Editor:** Visual Studio Code.
* **Terminal:** Windows Terminal running PowerShell.
* **Browser:** Google Chrome.
* **Music Player:** Native Windows Spotify Desktop app. Favors electronic, synthwave, lo-fi, and modern pop tracks.

---

## 3. Coding & Engineering Conventions

* **Python:** Clean, typed (PEP 484), documented with Google or NumPy docstrings. Prefers modular structure with clean separation of concerns.
* **Rust:** High safety, idiomatic error handling (`Result`/`anyhow`), zero unnecessary heap allocations, clean PyO3 wrappers.
* **Git:** Clean, atomic commits with conventional commit prefixes (`feat:`, `fix:`, `refactor:`, `perf:`).

---

## 4. Audio & Voice Settings

* **TTS Voice:** Piper `en_US-lessac-medium.onnx` at `1.00x` speed.
* **Wake Word:** `"Luna"` preferred; `"Aurix"` accepted.
* **Silence Threshold:** 2.2 seconds before terminating speech capture.
* **Startup Chime:** Enabled via `welcome_config.json`.
