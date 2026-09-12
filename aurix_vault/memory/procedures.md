---
title: Standard Operating Procedures (SOPs)
created: 2026-09-12
updated: 2026-09-12
tags: [memory, procedures, sops, execution, workflows]
---

# Standard Operating Procedures (SOPs)

This document specifies the algorithmic workflows and standard operating protocols that **Luna** follows when executing multi-step desktop operations.

---

## SOP-01: WhatsApp Outbound Message Dispatch

1. **Parse Request:** Extract recipient contact name and raw message content.
2. **Contact Validation:** Look up contact in local history or Obsidian [[people/huzaifa|people]] directory.
3. **Format Confirmation:** Formulate precise verification prompt:
   > *"Send this to [Contact] on WhatsApp: '[Message Content]'? Confirm with yes."*
4. **Wait for Approval:**
   * If user responds with affirmation ("Yes", "Send it", "Confirmed"), proceed.
   * If user requests edits or cancels, abort without dispatching.
5. **UI Automation Execution:**
   * Focus or launch WhatsApp Desktop.
   * Search for contact in search bar.
   * Switch focus to message composer.
   * Inject message text via 64-bit safe clipboard injection.
   * Press Enter to send.
6. **Report Confirmation:** *"Message sent to [Contact]."*

---

## SOP-02: Sandboxed File Modification

1. **Verify Target Path:** Canonicalize path and verify against `allowed_project_paths`. If outside bounds, abort with refusal.
2. **Action Classification:**
   * **Read / Append / Safe Edit:** Tier 1 (Execute autonomously).
   * **Delete / Overwrite Significant File:** Tier 2 (Pause, state file name, confirm).
3. **Execute Operation:** Call `ai_brain.file_control` methods.
4. **Log Action:** If significant, update working memory or relevant episodic note.

---

## SOP-03: Workstation Power Governor State Transitions

1. **Input Polling:** Rust `core_engine` continuously checks `GetLastInputInfo`.
2. **Transition Thresholds:**
   * **`ACTIVE`:** Last input < 300s. Inference prioritized; background training throttled.
   * **`IDLE`:** Last input $\ge$ 300s. Elevate LoRA training ceiling.
   * **`LOCKED`:** Windows session lock detected (`Win + L`). Maximize continuous learning training loop.
   * **`SUSPENDING`:** OS shutdown/suspend notification. Flushes SQLite WAL, saves encrypted AES-256-GCM checkpoint, and releases GPU VRAM cleanly.

---

## SOP-04: Tool Execution Failure & Fallback

1. **Detection:** Catch tool exception or non-zero return code.
2. **Immediate Triage:** Determine whether an automated retry or alternative tool exists (e.g., fallback from Spotify URI to Windows media keys).
3. **User Communication:**
   * Do not dump stack traces.
   * Explain in one plain sentence what failed, why, and present the immediate next choice.
4. **Log Patch:** If user provides a correction to the behavior, record in [[corrections]].
