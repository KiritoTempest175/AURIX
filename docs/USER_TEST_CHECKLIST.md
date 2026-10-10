# AURIX / LUNA — Windows user acceptance checklist

Build: newest **v0.2.0-preview** on https://github.com/KiritoTempest175/AURIX/releases
Do not use the older v0.1 package for these tests. Work only with your own
test files and accounts. Record **Pass / Fail / Not tested**, Windows version,
exact installer filename and a screenshot or redacted worker log for failures.

## Installer & startup
- [ ] Close and uninstall the older preview, then install the new EXE on Windows.
- [ ] Run AURIX without Python, Node.js, Rust, Git or a command prompt.
- [ ] Worker shows connected and LUNA greets once in chat and (when spoken replies ON) speaks.
- [ ] Shut down/reopen AURIX 3 times: no stuck worker or port conflict.

## UI & performance
- [ ] Main area and right chat/status panes scroll at 880x560 and maximized.
- [ ] Brand mark/icon appear in the main app and Windows installer.
- [ ] Open Permissions, change safe-app permission, restart, verify it is saved.
- [ ] Known allowed apps open without approval; unfamiliar executables still require it.
- [ ] Compare AURIX CPU/RAM telemetry with Windows Task Manager after 10–20 seconds.
- [ ] Compare GPU/GPU temperature with vendor tools when supported; unsupported GPU may show N/A.
- [ ] Export telemetry CSV and inspect timestamps / non-fabricated values.

## AI
- [ ] In Models, install Ollama and download a local model through the UI.
- [ ] Ask LUNA a complex question and a follow-up; replies are locally generated.
- [ ] Ask for model change; restart AURIX and confirm selection persists.
- [ ] Switch offline mode ON: installed model still responds without cloud API.

## Voice
- [ ] Spoken replies ON: ask 5 text questions and hear 5 responses; choose OFF and hear none.
- [ ] Female voice is used when Windows has an installed female voice; record actual voice.
- [ ] Test push-to-talk with quiet background, then with ambient noise.
- [ ] Say "Hey Luna" only after opting into background listening; verify greeting/reply.
- [ ] With wake listener ON, use mic button repeatedly; no VOICE_BUSY or stuck microphone.
- [ ] Test Roman Urdu and English; log misrecognized short fragments without sending them as commands.
- [ ] Verify LUNA does not re-trigger herself from her own speaker audio.

## Email
- [ ] Configure Gmail address + app password in Email (do not send password or logs to ChatGPT).
- [ ] Ask for proposal with missing project details: expect clarification, NOT fabricated fields.
- [ ] Email containing [Project Name] / [Your Name] must be blocked before sending.
- [ ] Send a complete approved test message only to an account you control; verify subject and body.
- [ ] Test rejecting the native approval; no email is sent.
- [ ] Disconnect the saved email account; verify sending is no longer automatic.

## WhatsApp Desktop
- [ ] Open WhatsApp using LUNA; select a test chat with explicit contact name.
- [ ] Ask LUNA to send a short text to the known contact; confirm delivery in that chat.
- [ ] Repeat with a different contact; verify LUNA never sends to a wrong/unverified chat.
- [ ] Test non-ASCII text via paste, and confirm previous clipboard is restored.
- [ ] If it reports "Cannot verify toolbar" or "Cannot locate message composer",
      send UI-version details/screenshots; **do not disable recipient verification**.
- [ ] WhatsApp calls and voice-note automation are NOT release-certified and require
      separate real WhatsApp acceptance tests; do not assume success from a simulated reply.

## Memory and security
- [ ] Opt in to encrypted memory; save a harmless fact, restart, then recall it.
- [ ] Emergency block and approval rejection prevent changes.
- [ ] Destructive edits, outbound communications and unknown software require exact-action approval.
- [ ] Check Activity for accurate execution/failure events.

**If any item fails:** capture only the specific screen and the relevant lines in
`%LOCALAPPDATA%\AURIX\logs\worker.log`, after removing addresses, passwords,
tokens and private messages. A passing CI run cannot replace hardware tests.
