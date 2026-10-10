# AURIX Windows 0.2 preview — release readiness

**Release classification: unsigned technical preview. NOT a certified production release or a 10/10 score.**

AURIX is the Windows desktop product; LUNA is the agent. The active inference runtime
is user-selectable **Ollama** on loopback or optional direct GGUF. There is no
required QLoRA training and no fixed GPU/RAM ceiling. Older source specifications
that prohibited Ollama or enforced fixed resource caps have been superseded by
explicit later owner instructions.

## Evidence and exact-scope release gates

- Python: pytest + compileall on Windows CI; must pass on the release commit.
- Rust: workspace check/tests and Tauri release compile on Windows CI.
- Frontend: Vite/Vitest and Playwright Chromium 1180×740 and 880×560, including a focused axe accessibility check.
- Security: Gitleaks, pip-audit for the minimal runtime, npm audit using npm lockfile, and cargo-audit on freshly resolved workspace dependencies.
- Packaging: PyInstaller frozen-worker authenticated HTTP smoke and actual NSIS installation launched from outside the repo with Python, Node and Rust removed from PATH; evidence in `installer-smoke.json`.
- Model: Ollama installation, downloads, switching and real AI replies still require Windows user acceptance testing; weights are user-downloaded, not bundled.
- Hardware/third parties: microphone and system speech packs, Hey Luna, WhatsApp desktop UI, real SMTP credentials and delivery, CPU/GPU benchmark and accessibility screen readers require a real test machine/account.
- Production security: native protected IPC, OS process sandbox, signed binaries/updater, consent/policy penetration tests and trustworthy OS kill switch remain blocking work.

## Original audit categories — status, evidence, and gaps

The original uploaded plan lists the finding IDs but does not include every
full Phase 1 finding text. This table uses only the descriptions available in the
project's existing tracker. Source-level mitigation is not independent certification.

| Finding | Status | Implementation or remaining gate |
|---|---|---|
| C-01 | Partial | `frontend/bridge_server.py`, `frontend/src-tauri/src/main.rs`: random loopback port, secret bearer, no Origin/Referer/browser fetch, no proxy/redirect, timeouts, rate limits; protected native IPC still missing |
| C-02 | Partial | Rust Windows dialog, `security/permissions.py` + `tool_executor.py`: fingerprint-bound one-time approval; native authorization independent of Python remains incomplete |
| H-01 | Open | Generic shell disabled pending restricted Windows process sandbox |
| H-02 | Partial | Path-scoped file operations need atomic/race-safe native jail |
| H-03 | Partial | Vault containment checks exist; full adversarial integration needed |
| H-04 | Partial | Private data ignored in current tree; history cleanup and review needed |
| H-05 | Verified in CI if green | Frozen worker, startup diagnostics and installed-app smoke; actual clean VM pending |
| H-06 | Partial | Windows ICO used; install/uninstall branding audit pending |
| H-07 | Not applicable to active inference | No scheduled fine-tuning; legacy research modules remain |
| H-08 | Partial | Adaptive pressure/no hard limits; idle CPU/RAM/VRAM benchmark pending |
| H-09 | Partial | Native approval preview; richer safe diff previews pending |
| H-10 | Partial | Tauri CSP/capabilities; independent security review pending |
| M-01 | Partial | Bounded worker and busy response; full async task cancel/backpressure pending |
| M-02 | Partial | Structured errors and local rotating worker logs; exhaustive scrub review pending |
| M-03 | Partial | Fixed authenticated localhost + no proxy; process-tree recovery pending |
| M-04 | Partial | Tauri/browser segregation and browser tests; real Tauri E2E pending |
| M-05 | Partial | Native local speech, opt-in wake and fallback; actual microphone test pending |
| M-06 | Partial | Rust hardware telemetry/history; cross-device validation pending |
| M-07 | Partial | Active config schema validated; legacy config cleanup pending |
| M-08 | Partial | npm lock + dependency audits; generated workspace Cargo lock not yet committed |
| M-09 | Partial | Security abuse-case tests and frozen/installed smoke; native IPC fuzzing pending |
| M-10 | Partial | DPAPI-keyed local audit chain; independent trust boundary absent |
| M-11 | Partial | README and setup reflect local Ollama flow; verify every release claim |
| M-12 | Partial | Unsandboxed generic shell disabled, constrained helpers require process-tree kill |
| L-01 | Implemented | Single desktop app-controller class maintained |
| L-02 | Partial | Browser viewport/axe tests; full WCAG AA and native screen-reader test pending |
| L-03 | Partial | Models/Email/System/Memory/Telemetry/Activity panels exist; full SDK/tools UI pending |
| L-04 | Implemented | GitHub setup and source instructions documented |
| L-05 | Partial | Product AURIX/agent LUNA distinguished; remaining legacy naming needs cleanup |

## Owner acceptance protocol

Use the newest **GitHub prerelease**, not the obsolete v0.1 installer. First
verify worker connected and startup greeting; install Ollama and the selected
model from Models; test actual local answers, low-risk app open/close, native
approval prompts, mic and wake, encrypted email setup without sending to
unapproved recipients, WhatsApp UI in a signed-in test account, offline mode
and resource use. Record Windows version, CPU, GPU, RAM, exact installer tag,
observed outcome and a redacted worker log for every failure.

Do **not** assign 10/10 until security boundaries, hardware compatibility,
accessibility and signed distribution are independently validated.


## Desktop issue regression pass (October 10, 2026)

The desktop preview includes fixes aimed at user-reported noisy/failed speech input, incomplete email proposal templates, and WhatsApp chat-header targeting. Local Windows speech recognition chooses a system-installed recognizer rather than requiring en-US and ignores weak short-word transcripts. Email bodies with placeholders such as `[Insert Project Name]`, `[Your Name]`, `TBD` or other fill-in fields are never sent. WhatsApp attempts additional accessible chat-header control types but **will not send to an unverifiable recipient**. If the desktop UI exposes no trustworthy contact name, contact selection requires a human-supported app-version fix.

The Permission Center can persist approvals for selected low-risk operations, not blanket authorization for outgoing messages or calls. Replies are spoken by default until the owner disables voice output. Windows installed female voice is preferred; neural voice model support and actual speaker quality remain user acceptance checks. The brand sidebar uses `frontend/public/aurix-mark.svg` neon AURIX orbital monogram; Windows installer ICO branding still requires separate asset validation.

**Physical acceptance still required:** verify recorded microphone transcription across accents/languages, WhatsApp chat identity + actual send/voice-note/call in a test account, spoken voice quality, CPU readout vs Task Manager after 30 seconds, and the email's exact approved subject/body in a received mailbox. The release must not be described as a certified 10/10 product before these checks succeed.
