"""Downloads Piper Female Voice model (en_US-amy-medium) for LUNA."""

import os
import sys
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
VOICES_DIR = BASE_DIR / "voices"

MODEL_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx"
CONFIG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx.json"

def download_file(url: str, dest: Path) -> None:
    print(f"[Downloading] {dest.name} from HuggingFace...")
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)
    print(f"[Saved] {dest}")

def main():
    print("[LUNA] Female Voice Model Downloader (Piper Amy Medium)")
    model_dest = VOICES_DIR / "en_US-amy-medium.onnx"
    config_dest = VOICES_DIR / "en_US-amy-medium.onnx.json"

    try:
        if not model_dest.exists():
            download_file(MODEL_URL, model_dest)
        else:
            print(f"[Ready] Voice model already exists: {model_dest}")

        if not config_dest.exists():
            download_file(CONFIG_URL, config_dest)
        else:
            print(f"[Ready] Voice config already exists: {config_dest}")

        print("\n[Success] LUNA female voice models downloaded and ready!")
    except Exception as e:
        print(f"[Error] downloading voice model: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
