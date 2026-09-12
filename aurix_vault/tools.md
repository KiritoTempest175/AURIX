---
title: AURIX Tool Registry & Technical Schema
created: 2026-09-12
updated: 2026-09-12
tags: [tools, schema, ai_brain, executor, safety]
---

# AURIX Tool Registry & Technical Schema

This document defines the complete technical specifications for all executable tools exposed to **Luna**'s reasoning engine via `ai_brain/tool_schema.py` and executed by `ai_brain/tool_executor.py`.

---

## 1. Safety Tiers & Execution Guarantees

Every tool operates under a strict execution contract:

* **Tier 1 (Autonomous / Reversible):** Safe to execute immediately without prior confirmation. Errors are reported calmly.
* **Tier 2 (Protected / Irreversible):** Requires user confirmation before execution. High blast-radius operations (communications, deletes, raw shell commands).
* **File Jail Sandbox:** All file operations are constrained to canonical allowed paths (`allowed_project_paths` in `config.toml`). Attempts to traverse outside the jail raise security violations.

---

## 2. Desktop Application & Process Tools

### `open_app`
* **Description:** Open or launch a local Windows application, file, folder, or URL.
* **Parameters:**
  * `target` (string, required): Application name, executable path, or target URL (e.g., `"chrome"`, `"whatsapp"`, `"vscode"`).
* **Safety Tier:** **Tier 1**
* **Handler:** `ai_brain.app_control.launch_application(target)`

### `close_app`
* **Description:** Close or terminate a running application process.
* **Parameters:**
  * `target` (string, required): Application name or process identifier (e.g., `"notepad.exe"`, `"discord"`).
* **Safety Tier:** **Tier 1**
* **Handler:** `ai_brain.app_control.terminate_application(target)`

---

## 3. Media & Audio Tools

### `play_media`
* **Description:** Control media playback, track navigation, or play specific songs, artists, or playlists.
* **Parameters:**
  * `action` (string, required): `"play" | "pause" | "next" | "previous"`
  * `query` (string, optional): Song name, artist, or playlist title (e.g., `"Starboy"`).
  * `service` (string, optional): `"spotify" | "youtube music" | "default"` (defaults to Spotify).
* **Safety Tier:** **Tier 1**
* **Handler:** `ai_brain.media_player.control_media(action, query, service)`

### `youtube`
* **Description:** Play, inspect, summarize, or download a YouTube video.
* **Parameters:**
  * `action` (string, required): `"play" | "info" | "summarize" | "download" | "trending"`
  * `query` (string, optional): Video search title or keywords.
  * `url` (string, optional): Direct YouTube URL.
* **Safety Tier:** **Tier 1**
* **Handler:** `ai_brain.youtube_video.handle_youtube(action, query, url)`

---

## 4. Communications & Messaging Tools

### `send_whatsapp_message`
* **Description:** Send a WhatsApp message to a specific contact via WhatsApp Desktop UI Automation and clipboard injection.
* **Parameters:**
  * `contact` (string, required): Contact name as saved in WhatsApp (e.g., `"Saad"`).
  * `message` (string, required): Plain text message content to transmit.
* **Safety Tier:** **Tier 2 (Explicit Confirmation Required)**
* **Handler:** `ai_brain.message_control.send_whatsapp_message(contact, message)`

### `make_whatsapp_call`
* **Description:** Start a WhatsApp voice or video call with a saved contact.
* **Parameters:**
  * `contact` (string, required): Target contact name.
  * `video` (boolean, required): `true` for video call, `false` for voice call.
* **Safety Tier:** **Tier 2 (Explicit Confirmation Required)**
* **Handler:** `ai_brain.call_control.start_whatsapp_call(contact, video)`

### `send_email`
* **Description:** Compose and draft an email to a designated recipient.
* **Parameters:**
  * `to` (string, required): Recipient email address.
  * `subject` (string, required): Email subject line.
  * `body` (string, required): Email body text.
* **Safety Tier:** **Tier 2 (Explicit Confirmation Required)**
* **Handler:** `ai_brain.email_control.compose_email(to, subject, body)`

---

## 5. File System & Storage Tools

### `list_directory`
* **Description:** List files and folders in a specified local directory.
* **Parameters:**
  * `path` (string, required): Target directory path.
* **Safety Tier:** **Tier 1**
* **Handler:** `ai_brain.file_control.list_dir(path)`

### `read_file`
* **Description:** Read text content from a local file.
* **Parameters:**
  * `path` (string, required): Target file path.
* **Safety Tier:** **Tier 1**
* **Handler:** `ai_brain.file_control.read_file(path)`

### `write_file`
* **Description:** Create, overwrite, or append text content to a local file.
* **Parameters:**
  * `path` (string, required): Target file path.
  * `content` (string, required): Content string to write.
  * `append` (boolean, required): If `true`, appends; if `false`, overwrites.
* **Safety Tier:** **Tier 1** (within allowed jail; if overwriting important files, caution is applied).
* **Handler:** `ai_brain.file_control.write_file(path, content, append)`

### `create_folder`
* **Description:** Create a new directory.
* **Parameters:**
  * `path` (string, required): Path of the folder to create.
* **Safety Tier:** **Tier 1**
* **Handler:** `ai_brain.file_control.create_directory(path)`

### `delete_item`
* **Description:** Delete a file or directory.
* **Parameters:**
  * `path` (string, required): Target file or directory path.
* **Safety Tier:** **Tier 2 (Explicit Confirmation Required)**
* **Handler:** `ai_brain.file_control.delete_item(path)`

### `copy_item` & `move_item`
* **Description:** Copy or move a local file or directory from source to destination.
* **Parameters:**
  * `source` (string, required): Origin path.
  * `destination` (string, required): Target path.
* **Safety Tier:** **Tier 1** (Copy) / **Tier 2** (Move if source is deleted)
* **Handler:** `ai_brain.file_control.copy_or_move(source, destination, is_move)`

### `rename_item`
* **Description:** Rename a file or directory.
* **Parameters:**
  * `path` (string, required): Current item path.
  * `new_name` (string, required): New file/directory name.
* **Safety Tier:** **Tier 1**
* **Handler:** `ai_brain.file_control.rename_item(path, new_name)`

---

## 6. System Execution & General Intelligence

### `web_search`
* **Description:** Search the public web for real-time information and documentation.
* **Parameters:**
  * `query` (string, required): Search query keywords.
* **Safety Tier:** **Tier 1**
* **Handler:** `ai_brain.web_search.search_duckduckgo(query)`

### `shell_exec`
* **Description:** Execute a terminal command when direct shell execution is required. Never used when a dedicated safe tool exists.
* **Parameters:**
  * `command` (string, required): Shell command string.
* **Safety Tier:** **Tier 2 (Explicit Confirmation Required, Guarded by Trust Token)**
* **Handler:** `ai_brain.tool_executor.execute_shell(command)`

### `general_answer`
* **Description:** Used for natural conversational responses, coding explanations, reasoning, and planning that require no operating system action.
* **Parameters:** None.
* **Safety Tier:** **Tier 1**
