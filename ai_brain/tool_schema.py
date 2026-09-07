# ai_brain/tool_schema.py

TOOLS = [
    {
        "name": "open_app",
        "description": "Open or launch an application, program, folder, or file on the user's system (e.g. 'open whatsapp', 'open vs code', 'launch terminal'). Do not use to send messages.",
        "parameters": {"target": "string — app/folder/file name as the user said it"},
    },
    {
        "name": "close_app",
        "description": "Close/terminate a running application.",
        "parameters": {"target": "string"},
    },
    {
        "name": "play_media",
        "description": "Play, pause, or search for a song/artist/playlist. Prefer Spotify desktop if installed and running; otherwise fall back to the web player or the named service.",
        "parameters": {
            "query": "string — song/artist/playlist name",
            "service": "string — 'spotify' | 'youtube' | 'web' | named by user, default 'spotify'",
            "action": "string — 'play' | 'pause' | 'next' | 'previous', default 'play'",
        },
    },
    {
        "name": "web_search",
        "description": "Search the web and summarize results for the user.",
        "parameters": {"query": "string"},
    },
    {
        "name": "send_email",
        "description": "Compose and send an email.",
        "parameters": {"to": "string", "subject": "string", "body": "string"},
    },
    {
        "name": "send_whatsapp_message",
        "description": "Send a chat message or text to a contact via WhatsApp. Requires a recipient contact and message content (e.g. 'message saad hi', 'message haad \"hi\"', 'tell alex I am here'). Do NOT use to simply open or launch the app.",
        "parameters": {"contact": "string — recipient name", "message": "string — message body"},
    },
    {
        "name": "make_phone_call",
        "description": "Place a voice or phone call to a contact via WhatsApp or phone, optionally speaking a message (e.g. 'call haad \"hello what are you doing\"', 'call haad hello what are you doing', 'call alex', 'phone mom').",
        "parameters": {
            "contact": "string — contact or person name to call",
            "message": "string — message to say or announce during the call (if any)",
        },
    },
    {
        "name": "general_answer",
        "description": "Answer a general knowledge question or chit-chat conversation directly with no system action. Do NOT use if the user asks to message, email, call, open, or close anything.",
        "parameters": {"response": "string — the answer itself"},
    },
]
