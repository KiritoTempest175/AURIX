---
type: config
created: 2026-09-12
updated: 2026-09-12
confidence: stated
sensitive: false
salience: 10
---

# AURIX Knowledge Vault — Master Index

This is the root navigation hub of Luna's **Second Brain**: a local, air-gapped, Obsidian-compatible markdown vault that persists identity, memory, history, and learned corrections across sessions.

---

## Vault Map

| File / Directory | Purpose | Retrieval Priority |
|---|---|---|
| [[model]] | Luna persona, identity, 8-trait architecture, operational rules | **Always loaded first** |
| [[about_me]] | User profile — Huzaifa's workflow, preferences, schedule | Session start |
| [[commands]] | Voice & text command syntax reference | On demand |
| [[tools]] | Tool registry — schemas, safety tiers, handlers | On demand |
| [[goals]] | Strategic roadmap & active milestones | Session start |
| [[corrections]] | Immutable behavioural patches & learned fixes | Session start |

### Memory Sub-Vault (`memory/`)
| File | Purpose |
|---|---|
| [[memory/facts\|facts]] | Persistent semantic facts with provenance tags |
| [[memory/preferences\|preferences]] | User interaction, UI, coding & audio preferences |
| [[memory/procedures\|procedures]] | Standard Operating Procedures for recurring workflows |
| `memory/episodic/YYYY-MM.md` | Chronological per-month event log |
| `memory/working/session_scratch.md` | Short-lived scratchpad cleared between sessions |

### History (`history/`)
| File | Purpose |
|---|---|
| `history/log/YYYY-MM.md` | Raw timestamped command ↔ response log |
| [[history/history_summary\|history_summary]] | Consolidated monthly summaries |

### Projects & People
| Directory | Purpose |
|---|---|
| `projects/` | Technical dossiers for tracked projects |
| `people/` | Contact profiles for messaging & scheduling dispatch |

### Generated Index
| Directory | Purpose |
|---|---|
| `.index/` | Machine-generated search cache — **do not hand-edit** |

---

## Context Assembly Order

When `SecondBrain.load_context()` is called at session start, files are assembled in this order:

1. `model.md` — identity grounding (always first)
2. `vault_index.md` — structural orientation
3. `memory/working/session_scratch.md` — carry-over context
4. `corrections.md` — active behavioural patches
5. `memory/facts.md` — persistent knowledge
6. `memory/preferences.md` — user preferences
7. `about_me.md` — user profile

> Content tagged `[sensitive]` or with `sensitive: true` in frontmatter is **excluded** from context assembly unless explicitly requested.
