---
type: config
created: 2026-09-12
updated: 2026-09-12
confidence: stated
sensitive: false
salience: 5
---

# AURIX Commands Reference

## Wake-Word Activation
* **Primary:** `"Luna"` · **Alt:** `"Aurix"`
* Echo confirmation (*"Yes? Go ahead."*) prevents accidental multi-sentence captures.
* STT: Whisper GGML 16 kHz, 2.2 s silence threshold, 35 s max recording.

## Desktop Application Commands

| Intent | Example Phrases | Tier |
|---|---|---|
| Launch | *"Open VS Code"*, *"Launch Spotify"* | 1 |
| Focus | *"Switch to Chrome"* | 1 |
| Minimise | *"Minimise Discord"* | 1 |
| Close | *"Close Notepad"* | 1 |

## Media & Audio

| Intent | Example Phrases | Tier |
|---|---|---|
| Play | *"Play Starboy on Spotify"* | 1 |
| Pause / Resume | *"Pause playback"* | 1 |
| Skip | *"Next song"* | 1 |
| Volume | *"Set volume to 40%"* | 1 |
| YouTube | *"Play latest MKBHD on YouTube"* | 1 |

## Communications (Tier 2 — Confirmation Required)

| Intent | Example Phrases | Tier |
|---|---|---|
| WhatsApp message | *"Send Saad: 'Running 10 min late'"* | 2 |
| WhatsApp call | *"Call Mom on WhatsApp"* | 2 |
| Email | *"Draft email to supervisor about milestones"* | 2 |

## File System

| Intent | Example Phrases | Tier |
|---|---|---|
| Read | *"Read config.toml"* | 1 |
| List | *"What files are in data/"* | 1 |
| Write | *"Save this to notes.txt"* | 1 |
| Delete | *"Delete temp.py"* | 2 |
| Search | *"Find all *.py modified today"* | 1 |

## System Telemetry

| Intent | Example Phrases | Tier |
|---|---|---|
| GPU temp | *"What's my GPU temp?"* | 1 |
| Power state | *"What governor state?"* | 1 |
| Model info | *"What model is running?"* | 1 |
