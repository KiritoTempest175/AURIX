---
type: config
created: 2026-09-12
updated: 2026-09-12
confidence: stated
sensitive: false
salience: 5
---

# AURIX Tool Registry

All tools are defined in `ai_brain/tool_schema.py` and dispatched by `ai_brain/tool_executor.py`.

## Safety Tiers
* **Tier 1 (Autonomous):** Reversible, no confirmation needed.
* **Tier 2 (Protected):** Irreversible, explicit user confirmation required.

## Desktop & Process

| Tool | Description | Params | Tier |
|---|---|---|---|
| `open_app` | Launch app, file, folder, or URL | `target: str` | 1 |
| `close_app` | Terminate a running app | `target: str` | 1 |

## Media

| Tool | Description | Params | Tier |
|---|---|---|---|
| `play_media` | Play/pause/skip music | `action`, `query?`, `service?` | 1 |
| `youtube` | Play/info/summarise/download YouTube | `action`, `query?`, `url?` | 1 |

## Communications

| Tool | Description | Params | Tier |
|---|---|---|---|
| `send_whatsapp_message` | Send WhatsApp via UIA + clipboard | `contact`, `message` | 2 |
| `make_whatsapp_call` | Start voice/video call | `contact`, `video: bool` | 2 |
| `send_email` | Compose and route email | `to`, `subject`, `body` | 2 |

## File System

| Tool | Description | Params | Tier |
|---|---|---|---|
| `list_directory` | List files in a path | `path: str` | 1 |
| `read_file` | Read text file | `path: str` | 1 |
| `write_file` | Create/overwrite/append file | `path`, `content`, `append: bool` | 1 |
| `create_folder` | Create directory | `path: str` | 1 |
| `delete_item` | Delete file or folder | `path: str` | 2 |
| `copy_item` | Copy file/dir | `source`, `destination` | 1 |
| `move_item` | Move file/dir | `source`, `destination` | 1–2 |
| `rename_item` | Rename file/dir | `path`, `new_name` | 1 |

## System

| Tool | Description | Params | Tier |
|---|---|---|---|
| `web_search` | DuckDuckGo search | `query: str` | 1 |
| `shell_exec` | Raw terminal command | `command: str` | 2 |
| `general_answer` | Conversational — no OS action | — | 1 |
