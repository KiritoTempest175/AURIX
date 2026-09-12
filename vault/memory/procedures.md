---
type: procedure
created: 2026-09-12
updated: 2026-09-12
confidence: stated
sensitive: false
salience: 5
---

# Standard Operating Procedures

## SOP-01: WhatsApp Outbound Dispatch
1. Parse contact name + message from user request.
2. Validate contact against `people/` or recent history.
3. Present confirmation: *"Send to [Contact]: '[Message]'? Confirm with yes."*
4. On approval → focus WhatsApp Desktop → search contact → inject clipboard → send.
5. Report: *"Message sent to [Contact]."*

## SOP-02: Sandboxed File Modification
1. Canonicalise path; verify against `allowed_project_paths`.
2. Classify: Read/Append = Tier 1 (auto). Delete/Overwrite = Tier 2 (confirm).
3. Execute via `ai_brain.file_control`.
4. Log significant actions to episodic memory.

## SOP-03: Power Governor Transitions
| State | Trigger | Policy |
|---|---|---|
| `ACTIVE` | Input < 300 s | Inference priority; training throttled |
| `IDLE` | Input ≥ 300 s | Elevate LoRA training ceiling |
| `LOCKED` | `Win + L` | Maximise continuous learning |
| `SUSPENDING` | OS shutdown/sleep | Flush WAL, save AES-256-GCM checkpoint, release VRAM |

## SOP-04: Failure & Fallback
1. Catch exception or non-zero return code.
2. Determine if retry or alternative tool exists.
3. Explain in one sentence: what failed, why, next option.
4. If user corrects behaviour, record in [[corrections]].
