---
title: AURIX Commands Reference Manual
created: 2026-09-12
updated: 2026-09-12
tags: [commands, voice, shortcuts, execution, luna, aurix]
---

# AURIX Commands Reference Manual

This manual documents the voice wake-word protocols, natural language command patterns, and execution triggers recognized by **Luna** within the **AURIX** desktop environment.

---

## 1. Wake-Word Architecture & Voice Activation

AURIX operates a continuous offline wake-word detection pipeline using high-efficiency audio sampling (16 kHz mono):

* **Primary Wake Keywords:**
  * `"Luna"` (Primary agent trigger)
  * `"Aurix"` (Alternative system trigger)
* **Echo Confirmation Guardrail:**
  * Upon detecting the wake word, Luna responds with a low-latency vocal echo (*"Yes? Go ahead."* or *"Listening."*) to prevent accidental multi-sentence captures.
* **Continuous Audio Buffer:**
  * STT uses local Whisper GGML (`ggml-base.en.bin`) with adaptive silence detection (2.2s silence threshold, 35s maximum recording window).

---

## 2. Desktop Application & Process Commands

| Intent | Natural Voice / Text Patterns | Underlying Action | Safety Tier |
|---|---|---|---|
| **Launch App** | *"Open VS Code"*, *"Launch Spotify"*, *"Start Notepad"* | Scans process registry and launches executable | **Tier 1** |
| **Focus App** | *"Switch to Chrome"*, *"Bring WhatsApp to front"* | Windows UIA focus switch | **Tier 1** |
| **Minimize App** | *"Minimize Discord"*, *"Minimize this window"* | Sends SW_MINIMIZE signal | **Tier 1** |
| **Close App** | *"Close Notepad"*, *"Kill Calculator"* | Graceful process termination | **Tier 1** |

---

## 3. Media & Audio Orchestration Commands

| Intent | Natural Voice / Text Patterns | Underlying Action | Safety Tier |
|---|---|---|---|
| **Play Music** | *"Play Starboy on Spotify"*, *"Play some lo-fi"* | Native Spotify URI / playback trigger | **Tier 1** |
| **Pause / Resume** | *"Pause playback"*, *"Resume music"*, *"Pause"* | Sends VK_MEDIA_PLAY_PAUSE | **Tier 1** |
| **Next / Previous Track** | *"Next song"*, *"Skip this track"*, *"Previous track"* | Sends VK_MEDIA_NEXT_TRACK | **Tier 1** |
| **Volume Adjustment** | *"Set volume to 40%"*, *"Mute audio"*, *"Volume up"* | Windows CoreAudio master volume API | **Tier 1** |
| **YouTube Video** | *"Play latest Marques Brownlee video on YouTube"* | Launches browser/embedded video playback | **Tier 1** |

---

## 4. WhatsApp & Communication Commands

> [!IMPORTANT]
> All outbound communication commands belong to **Tier 2 (High-Stakes)** and require explicit verbal or text confirmation before transmission.

| Intent | Natural Voice / Text Patterns | Flow & Confirmation Requirement | Safety Tier |
|---|---|---|---|
| **Send WhatsApp Message** | *"Send a message to Saad saying I'm running 10 minutes late"* | 1. Parse contact and message.<br>2. Ask: *"Send this to Saad: 'I'm running 10 minutes late'? Confirm with yes."*<br>3. On confirmation, safely inject clipboard into WhatsApp UIA. | **Tier 2** |
| **WhatsApp Voice Call** | *"Call Saad on WhatsApp"* | 1. Verify target contact.<br>2. Confirm intent.<br>3. Trigger voice call button in WhatsApp Desktop. | **Tier 2** |
| **WhatsApp Video Call** | *"Start a video call with Alex on WhatsApp"* | 1. Verify target contact.<br>2. Confirm intent.<br>3. Trigger video call button. | **Tier 2** |
| **Compose Email** | *"Draft an email to supervisor about project milestones"* | Composes draft in client/browser; holds transmission until review. | **Tier 2** |

---

## 5. File System & Knowledge Base Commands

| Intent | Natural Voice / Text Patterns | Underlying Action | Safety Tier |
|---|---|---|---|
| **Read File** | *"Read config.toml"*, *"Check lines 10 to 40 of frontend.py"* | Sandboxed file read | **Tier 1** |
| **List Directory** | *"What files are in the data directory?"*, *"List tests"* | Path-jailed directory scan | **Tier 1** |
| **Write / Append File** | *"Save this snippet to notes.txt"*, *"Append this log"* | Sandboxed file write | **Tier 1** |
| **Delete File** | *"Delete temporary_test.py"* | 1. Require explicit confirmation.<br>2. Perform delete once confirmed. | **Tier 2** |
| **Search Files** | *"Find all files modified today"*, *"Search for test_*.py"* | File jail index query | **Tier 1** |
| **Vault Notes** | *"Save this note to my vault"*, *"Check notes on architecture"* | Direct update to `aurix_vault/` | **Tier 1** |

---

## 6. System & Hardware Telemetry Commands

| Intent | Natural Voice / Text Patterns | Response Type | Safety Tier |
|---|---|---|---|
| **Hardware Status** | *"What is my GPU temp?"*, *"How much RAM is free?"* | Returns live metrics from NVML / psutil | **Tier 1** |
| **Power State** | *"What governor state is active?"* | Reports `ACTIVE`, `IDLE`, or `LOCKED` | **Tier 1** |
| **Model Status** | *"What model is currently running?"* | Reports active LLM (Gemma 4 E4B) | **Tier 1** |
