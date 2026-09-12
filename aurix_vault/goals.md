---
title: System Goals & Strategic Roadmap
created: 2026-09-12
updated: 2026-09-12
tags: [goals, roadmap, milestones, development, aurix, luna]
---

# System Goals & Strategic Roadmap

This document outlines the core objectives, active engineering milestones, and long-term vision for the **AURIX** ecosystem and **Luna**'s cognitive evolution.

---

## 1. Primary Mission

> **To build the world's most capable, 100% air-gapped, zero-cloud desktop AI executive—fusing bare-metal Rust performance, local neural voice interaction, continuous student learning, and frictionless OS automation.**

---

## 2. Active Engineering Milestones (Near-Term)

* [x] **Rust Core FFI Stabilization:** PyO3 bindings for `core_engine.pyd` and `luna_core.pyd` providing microsecond hardware monitoring.
* [x] **Adaptive Power Governor v2:** 4-tier state machine (`ACTIVE`, `IDLE`, `LOCKED`, `SUSPENDING`) managing hardware quotas and LoRA scaling.
* [x] **Dual-Model Inference Cascade:** Dynamic model resolution across Ollama Qwen 2.5 3B, Gemma 4 E4B (4-bit NF4), and Qwen Coder.
* [x] **Knowledge Vault Reorganization:** Standardized Obsidian memory architecture with explicit model, command, tool, and memory hierarchy.
* [ ] **Sub-100ms Voice Turnaround:**
  * Optimize Whisper GGML threading and Piper ONNX streaming synthesis to achieve instantaneous conversational responsiveness.
  * Implement streaming audio playback buffer so TTS begins playing before LLM generation finishes.
* [ ] **Obsidian Bidirectional Graph Indexing:**
  * Build local embedding index in `aurix_vault/.index/` for semantic search across memory notes.
  * Enable Luna to proactively cross-reference previous episodic notes during daily planning.

---

## 3. Medium-Term Roadmap (Autonomous Learning)

* [ ] **Student-5B Continuous QLoRA Convergence:**
  * Run in-memory synthetic task training during workstation lock states (`LOCKED` power state).
  * Validate 70/30 replay buffer (synthetic coding vs sanitized telemetry) to prevent catastrophic forgetting.
  * Automated 3-version rollback and evaluation benchmark against standard desktop automation tasks.
* [ ] **Multimodal Visual Grounding:**
  * Integrate lightweight local vision model or Windows UI Automation tree crawler for visual screen element detection.
  * Direct coordinate-free interaction with complex third-party GUI software.
* [ ] **Unified Multi-Contact Routing:**
  * Expand WhatsApp and email dispatchers with smart contact resolution and meeting coordination from Obsidian people dossiers (`aurix_vault/people/`).

---

## 4. Long-Term Vision

* **Complete Air-Gapped Autonomy:** A fully autonomous workstation companion that acts as a proactive co-pilot without sending a single byte to external servers.
* **Zero-Friction Co-Development:** Pair programming where Luna indexes entire project repositories, runs tests, fixes bugs, and commits clean diffs while Huzaifa focuses on architecture.
