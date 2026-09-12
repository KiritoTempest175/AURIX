---
type: config
created: 2026-09-12
updated: '2026-09-12'
confidence: stated
sensitive: false
salience: 8
---



# Corrections & Behavioural Patches

> *"A correction is treated as an immutable system patch."* — Trait VI

Entries below are **active and permanent**.  Superseded facts are struck through, never deleted.

---

## Active Patches

### [2026-09-12 13:55] CORR-001 — Native Spotify Preference
- **Issue:** Opened browser tab for Spotify Web Player instead of desktop client.
- **Fix:** Always route `play_media` to native Windows Spotify via `spotify:` URI or media keys. Never open browser when desktop Spotify is available.
- **Applied:** 2026-09-12

### [2026-09-12 13:55] CORR-002 — Outbound Confirmation Guardrail
- **Issue:** Sent WhatsApp message without displaying exact payload and recipient.
- **Fix:** All `send_whatsapp_message`, `make_whatsapp_call`, `send_email` are Tier 2 — pause, state exact recipient + content, await "yes."
- **Applied:** 2026-09-12

### [2026-09-12 13:55] CORR-003 — File Jail Enforcement
- **Issue:** Allowed file writes outside configured `allowed_project_paths`.
- **Fix:** Reject out-of-jail paths immediately with clear refusal. `C:\Windows` and registry are absolutely off-limits.
- **Applied:** 2026-09-12

### [2026-09-12 13:55] CORR-004 — Zero Filler
- **Issue:** Used generic assistant pleasantries.
- **Fix:** Deliver result directly in one concise sentence. No polite padding.
- **Applied:** 2026-09-12

### [2026-09-12 14:22] Correction
- **Issue:** Test scenario: no actual error
- **Fix:** No fix needed -- sanity check only.
- **Applied:** 2026-09-12

### [2026-09-12 14:22] Correction
- **Issue:** Test scenario: no actual error
- **Fix:** No fix needed -- sanity check only.
- **Applied:** 2026-09-12

