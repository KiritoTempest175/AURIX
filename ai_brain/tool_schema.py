"""AURIX tool definitions exposed to the reasoning model."""

TOOLS = [
    {
        "name": "open_app",
        "description": (
            "Open or launch a local Windows application, file, folder or URL. "
            "Use this whenever the user asks to open, launch, start or access "
            "an application such as Chrome, WhatsApp, Notepad, Calculator or VS Code."
        ),
        "parameters": {
            "target": "string"
        },
    },

    {
        "name": "close_app",
        "description": "Close or terminate a running application.",
        "parameters": {
            "target": "string"
        },
    },

    {
        "name": "play_media",
        "description": (
            "Control media playback or play a song, artist or playlist."
        ),
        "parameters": {
            "action": "play | pause | next | previous",
            "query": "string, optional",
            "service": "spotify | youtube music | default",
        },
    },

    {
        "name": "web_search",
        "description": (
            "Search the internet for information. "
            "Use only when the user actually wants current/web information."
        ),
        "parameters": {
            "query": "string"
        },
    },

    {
        "name": "youtube",
        "description": "Play, inspect, summarize or download a YouTube video.",
        "parameters": {
            "action": "play | info | summarize | download | trending",
            "query": "string, optional",
            "url": "string, optional",
        },
    },

    {
        "name": "send_email",
        "description": "Compose and send an email.",
        "parameters": {
            "to": "string",
            "subject": "string",
            "body": "string",
        },
    },

    {
        "name": "send_whatsapp_message",
        "description": (
            "Send a WhatsApp message to a person. "
            "Do not use merely to open WhatsApp."
        ),
        "parameters": {
            "contact": "string",
            "message": "string",
        },
    },

    {
        "name": "make_whatsapp_call",
        "description": "Start a WhatsApp voice or video call.",
        "parameters": {
            "contact": "string",
            "video": "boolean",
        },
    },

    {
        "name": "list_directory",
        "description": "List files and folders in a directory.",
        "parameters": {
            "path": "string"
        },
    },

    {
        "name": "read_file",
        "description": "Read the contents of a local text file.",
        "parameters": {
            "path": "string"
        },
    },

    {
        "name": "write_file",
        "description": "Create, overwrite or append text to a file.",
        "parameters": {
            "path": "string",
            "content": "string",
            "append": "boolean",
        },
    },

    {
        "name": "create_folder",
        "description": "Create a folder.",
        "parameters": {
            "path": "string"
        },
    },

    {
        "name": "delete_item",
        "description": "Delete a file or folder.",
        "parameters": {
            "path": "string"
        },
    },

    {
        "name": "copy_item",
        "description": "Copy a local file or directory.",
        "parameters": {
            "source": "string",
            "destination": "string",
        },
    },

    {
        "name": "move_item",
        "description": "Move a local file or directory.",
        "parameters": {
            "source": "string",
            "destination": "string",
        },
    },

    {
        "name": "rename_item",
        "description": "Rename a file or directory.",
        "parameters": {
            "path": "string",
            "new_name": "string",
        },
    },

    {
        "name": "shell_exec",
        "description": (
            "Execute a terminal command when direct shell execution is actually "
            "required. Never use this when a safer dedicated tool exists."
        ),
        "parameters": {
            "command": "string"
        },
    },

    {
        "name": "general_answer",
        "description": (
            "Use for normal conversation, questions, explanations and reasoning "
            "that require no computer action."
        ),
        "parameters": {},
    },
]