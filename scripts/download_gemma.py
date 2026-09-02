"""Helper utility to download or verify the Google Gemma 4 E4B model weights."""

import os
import sys
from huggingface_hub import snapshot_download

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MODEL_ID = "google/gemma-4-E4B-it"

def main():
    print(f"[LUNA] Checking / downloading weights for '{MODEL_ID}'...")
    try:
        path = snapshot_download(
            repo_id=MODEL_ID,
            allow_patterns=["*.json", "*.jinja", "*.md", "*.safetensors"],
        )
        print(f"[LUNA] [SUCCESS] Downloaded and cached '{MODEL_ID}' at:")
        print(f"       {path}")
    except Exception as e:
        print(f"[LUNA] [ERROR] Download error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
