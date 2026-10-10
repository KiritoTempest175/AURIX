# AURIX / LUNA — Windows user acceptance checklist

Release candidate: **v0.2.0 preview**. Record the exact release tag and Windows version
when reporting failures. The app is an *unsigned test build*, not a certified
production release. The installer includes its own desktop worker; a user
should not install Python, Node, Rust or a separate PyAutoGUI package.

## P0 — Install and first run

- [ ] Download the latest v0.2.0 preview .exe from GitHub Releases (not old v0.1).
- [ ] Close and uninstall an older AURIX preview, then install the new build.
- [ ] Launch AURIX without opening a terminal or developer tools.
- [ ] See **Worker connected** and the initial LUNA greeting.
- [ ] Hear a startup greeting if Windows has a working voice output device.
- [ ] Navigate every panel (Models, Email, Telemetry, Memory, System, Activity).
- [ ] Scroll Models and System to the end, including at minimum window size.
- [ ] Exit AURIX, reopen, and confirm preferences persist.

## P0 — Ollama and local conversation

- [ ] Models panel offers **Enable model downloads**; Ollama can install using only UI.
- [ ] Start/detect Ollama from the app or Windows startup.
- [ ] Download a small recommended free local model (e.g. gemma3:1b).
- [ ] Progress and errors are displayed while downloading.
- [ ] Activate the model; LUNA answers a factual question without a cloud AI account.
- [ ] Have a 5-turn conversation; verify follow-up context stays coherent.
- [ ] Restart the app; the chosen model remains active.
- [ ] Disable internet and verify the installed model still responds.
- [ ] After about 30 seconds idle, Ollama can release model VRAM/RAM as configured.

## P0 — Voice and resource measurements

- [ ] Click mic, speak a simple instruction; transcription appears.
- [ ] Use System to opt in to Hey Luna; say 'Hey Luna' and get a response.
- [ ] Give a follow-up instruction without clicking the mic.
- [ ] Switch wake listening OFF and confirm the microphone is not continuously captured.
- [ ] Stop speaking output and use 'Hey Luna stop' for emergency action blocking.
- [ ] Confirm CPU%, RAM%, supported GPU% and GPU temperature are shown without fabricated data.
- [ ] Telemetry history persists after restart and CSV exports open correctly.
- [ ] Measure idle CPU/RAM with Ollama installed and one model downloaded.

## P1 — Local tasks and safety

- [ ] 'Open calculator' and 'close calculator' (no unnecessary confirmation).
- [ ] Open and close WhatsApp; confirm it does not require user-installed PyAutoGUI.
- [ ] Create a test folder/file, read, rename, copy and move them.
- [ ] Delete only a throwaway test file and verify the requested confirmation.
- [ ] Attempt a dangerous operation and verify LUNA does not silently execute it.
- [ ] Test scoped Git status, commit and push in a disposable repository.
- [ ] Confirm 'push it' asks for repo context rather than guessing the wrong project.
- [ ] Review an installation request; confirm no untrusted installer executes silently.
- [ ] Connect a test Gmail app password in Email, then disconnect and confirm it is removed.
- [ ] Draft and send an email to your own test address with clear recipient/body approval.
- [ ] Send a WhatsApp message to a consenting test contact with explicit approval.
- [ ] Test WhatsApp call/voice-note features only where explicitly supported; log unavailable features honestly.
- [ ] Opt into memory, save a preference, restart, retrieve it and delete it.
- [ ] Trigger emergency stop while an action is awaiting approval; resume and confirm the old approval is invalid.

## Known limitations — not accepted as production-ready

- Live WhatsApp **calling and voice-note automation** requires app-version-specific Windows testing and is not certified.
- Arbitrary terminal commands, package installation, Antigravity IDE control and unattended destructive changes are not safe to claim fully implemented without OS sandbox and real integrations.
- Only Ollama inference is active, and an Ollama model download initially requires network access and disk space.
- Background wake detection requires an installed Windows speech engine and microphone consent; audio drivers vary.
- Authenticated loopback HTTP is still used between Rust and Python; protected native IPC is pending.
- The build is unsigned, lacks a certified updater, and has not passed an independent security audit.

## Reporting a failed check

Record: release tag, Windows version, CPU/GPU/RAM, feature name, steps,
expected behavior, actual behavior, and a redacted excerpt of
`%LOCALAPPDATA%\AURIX\logs\worker.log`. Never send app passwords, tokens,
private chat messages or memory database files.
