---
title: Interaction & Event Log Archive Schema
tags: [history, log, schema, archive]
---

# Interaction & Event Log Archive Schema

This directory (`aurix_vault/history/log/`) stores structured session archives, serialized conversation turns, and background execution traces.

## 1. File Naming Standard
`YYYY-MM-DD_HH-MM-SS_session.jsonl` or `YYYY-MM-DD_interaction.md`

## 2. Retention & Privacy Guarantee
* **Zero-Cloud:** All logs remain strictly on local storage.
* **Secret Scrubbing:** System API keys, passwords, personal tokens, and authorization cookies are automatically scrubbed via AURIX's regex scrubber prior to persistence.
* **Rotation:** Summaries are rolled up weekly into [[history_summary|history_summary.md]], and raw logs older than 90 days are archived or compacted.
