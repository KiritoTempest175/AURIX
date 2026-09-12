---
title: AURIX Knowledge Vault — Master Index
created: 2026-09-12
updated: 2026-09-12
tags: [vault, index, root, obsidian, aurix, luna]
---

# AURIX Knowledge Vault — Master Index

Welcome to the **AURIX Knowledge Vault**, the centralized local, air-gapped memory graph for **Luna** and the **AURIX** desktop AI executive ecosystem.

This vault is fully Obsidian-compatible, utilizing bidirectional wikilinks (`[[...]]`), structured frontmatter, and categorized sub-vaults to support continuous grounding, semantic retrieval, and long-term memory.

---

## 🧭 Vault Architecture & Navigation

```
aurix_vault/
├── vault_index.md          ← [YOU ARE HERE] Master navigation hub
├── model.md                ← Model identity, 8-trait persona & rule pointers
├── about_me.md             ← User profile & workflow context for Huzaifa
├── commands.md             ← Voice & text command manual & syntax
├── tools.md                ← Tool schema registry & execution guarantees
├── goals.md                ← Strategic roadmap & engineering milestones
├── corrections.md          ← Single-correction learning log & active patches
│
├── memory/                 ← Semantic & persistent long-term memory
│   ├── facts.md            ← Workstation, hardware quotas & jail boundaries
│   ├── preferences.md      ← Huzaifa's UI, brevity & coding preferences
│   ├── procedures.md       ← Standard Operating Procedures (SOPs)
│   ├── episodic/           ← Chronological session logs & recaps
│   └── working/            ← Active scratchpad & temporary context
│
├── history/                ← Event chronicles & raw telemetry
│   ├── log/                ← Scrubbed raw interaction archives
│   └── history_summary.md  ← High-level evolutionary timeline of AURIX
│
├── projects/               ← Active project dossiers & technical notes
│   ├── aurix.md            ← The AURIX system architecture dossier
│   └── README.md           ← Projects directory guide
│
├── people/                 ← User, team & contact profiles for automation
│   ├── huzaifa.md          ← Master dossier for Huzaifa
│   └── contacts_template.md← Template for new contacts
│
└── .index/                 ← Local search cache & manifest metadata
    ├── vault_manifest.json ← Vault schema metadata
    └── README.md           ← Index documentation
```

---

## ⚡ Core Operational Manifests

| Document | Primary Function | Primary Wikilink |
|---|---|---|
| **Model Identity & Rules** | Persona grounding, 8 traits, permission matrix, hard limits | [[model]] |
| **User Profile (Huzaifa)** | Daily routine, engineering stack, communication style | [[about_me]] |
| **Commands Manual** | Voice triggers ("Luna" / "Aurix"), app management, media | [[commands]] |
| **Tools Registry** | Complete schema for all `ai_brain` dispatchers | [[tools]] |
| **System Goals** | Near-term milestones, Student-5B QLoRA, sub-100ms voice | [[goals]] |
| **System Corrections** | Immutable behavioral patches & learned feedback | [[corrections]] |

---

## 🧠 Memory Sub-Vault

The [[memory/facts|Memory Sub-Vault]] houses grounded semantic knowledge, user habits, and episodic recollections:

* **[[memory/facts|Facts & Hardware]]:** Host system specifications, NVML limits, file jail rules, and model configurations.
* **[[memory/preferences|Preferences]]:** Brevity standards, dark cyberpunk theme, Spotify music preferences, and Python/Rust coding styles.
* **[[memory/procedures|Procedures (SOPs)]]:** Algorithmic protocols for WhatsApp dispatching, sandboxed file modifications, and power state changes.
* **[[memory/episodic/session_template|Episodic Memory]]:** Date-stamped session memory notes tracking milestones (e.g., [[memory/episodic/2026-09-12-vault-restructure|2026-09-12 Vault Restructure]]).
* **[[memory/working/current_context|Working Memory]]:** Active task scratchpad and live in-memory variables.

---

## 📜 History & Chronicles

* **[[history/history_summary|History Summary]]:** Chronological evolution of AURIX from Phase 1 prototype through Rust 2021 FFI integration, Power Governor v2, and vault modernization.
* **[[history/log/log_schema|Log Archive]]:** Scrubbed local logs guaranteeing 100% zero-cloud data privacy.

---

## 🚀 Projects & People

* **Projects:** Active technical tracking for [[projects/aurix|AURIX]].
* **People:** Priority dossiers including [[people/huzaifa|Huzaifa]] and templates for contact dispatching.

---

## 🔒 Security & Privacy Notice

> **100% On-Device & Air-Gapped:** All notes, memory vectors, logs, and identity specifications stored in this vault are strictly local. No content is uploaded to third-party cloud services.
