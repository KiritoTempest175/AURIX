"""AURIX AI Brain — YouTube Video Controller.

Handles YouTube video playback via Chrome Guest Mode, fetches video metadata,
extracts transcripts, generates summaries, and downloads videos using yt-dlp.
"""

import os
import re
import time
import logging
import platform
import subprocess
from pathlib import Path

try:
    import pyautogui
    pyautogui.PAUSE = 0.15
    pyautogui.FAILSAFE = True
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    TRANSCRIPT_AVAILABLE = True
except ImportError:
    TRANSCRIPT_AVAILABLE = False

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

logger = logging.getLogger("aurix.ai_brain.youtube_video")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── CORE YOUTUBE FUNCTIONS ─────────────────────────────────────────────

def _extract_video_id(url: str) -> str:
    patterns = [r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([A-Za-z0-9_-]{11})"]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""

def _is_valid_youtube_url(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url or ""))

def _handle_play(query: str) -> str:
    """Plays a YouTube video by automating Chrome in Guest Mode."""
    if not PYAUTOGUI_AVAILABLE:
        return "PyAutoGUI is required for visual YouTube playback."
    
    if not query:
        return "No search query provided for playback."

    logger.info("YouTube: Launching Chrome Guest Mode to play '%s'", query)
    
    try:
        # Launch Chrome cleanly in Guest Mode
        subprocess.Popen("start chrome --guest", shell=True)
        time.sleep(2.5)
        
        # Navigate directly to the search results
        safe_query = query.replace(" ", "+")
        search_url = f"https://www.youtube.com/results?search_query={safe_query}"
        
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.3)
        pyautogui.write(search_url, interval=0.02)
        pyautogui.press("enter")
        
        # Wait for YouTube results to load
        time.sleep(3.5)
        
        # Tab targeting to strike the first video thumbnail/title
        for _ in range(4):
            pyautogui.press("tab")
            time.sleep(0.15)
            
        pyautogui.press("enter")
        
        return f"Playing top result for '{query}' on YouTube."
        
    except Exception as e:
        logger.error("YouTube playback automation failed: %s", e)
        return f"Playback automation failed: {e}"

def _handle_download(url: str) -> str:
    """Downloads a YouTube video to the user's Downloads folder using yt-dlp."""
    if not YT_DLP_AVAILABLE:
        return "Missing 'yt-dlp' library. Please install it via pip (pip install yt-dlp)."
    if not _is_valid_youtube_url(url):
        return "Invalid YouTube URL provided for download."

    logger.info("YouTube: Downloading video from '%s'", url)
    
    try:
        downloads_dir = Path.home() / "Downloads" / "AURIX_Downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        
        # By removing the 'format' key entirely, we allow yt-dlp to use its 
        # native default behavior (exactly matching how it works in your PowerShell).
        ydl_opts = {
            'format': 'mp4',
            'outtmpl': str(downloads_dir / '%(title)s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Unknown Video')
            
        return f"Successfully downloaded '{title}' to your Downloads/AURIX_Downloads folder."
        
    except Exception as e:
        logger.error("Download failed: %s", e)
        return f"Download failed: {e}"

def _handle_summarize(url: str) -> str:
    """Fetches the transcript and generates an AI summary."""
    if not TRANSCRIPT_AVAILABLE:
        return "Missing 'youtube-transcript-api'. Please install it via pip."
    if not _is_valid_youtube_url(url):
        return "Invalid YouTube URL provided for summarization."

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract a valid video ID from the URL."

    # Fetch Transcript
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript_data = None
        
        # Try finding manual or auto-generated English/primary transcripts
        for t in transcript_list:
            transcript_data = t
            break
            
        if not transcript_data:
            return "No transcript available for this video."
            
        fetched = transcript_data.fetch()
        full_text = " ".join(entry["text"] for entry in fetched)
        
    except Exception as e:
        logger.error("Transcript fetch failed: %s", e)
        return f"Failed to retrieve transcript: {e}"
        
        truncated = full_text[:80000] 
        response = model.generate_content(f"Summarize this transcript:\n\n{truncated}")
        
        _save_summary_to_desktop(response.text, url)
        
        return response.text.strip()
        
    except ImportError:
        return "Missing 'google-generativeai'. Transcript fetched, but cannot summarize."
    except Exception as e:
        logger.error("AI Summarization failed: %s", e)
        return f"Summary generation failed: {e}"

def _save_summary_to_desktop(content: str, url: str) -> None:
    from datetime import datetime
    try:
        desktop = Path.home() / "Desktop"
        filename = f"Luna_YT_Summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = desktop / filename
        
        header = f"AURIX (Luna) — Video Summary\n{'─' * 40}\nURL: {url}\n{'─' * 40}\n\n"
        filepath.write_text(header + content, encoding="utf-8")
        
        if platform.system() == "Windows":
            os.startfile(filepath)
    except Exception as e:
        logger.warning("Failed to save summary to desktop: %s", e)

def _handle_get_info(url: str) -> str:
    """Scrapes basic video metadata without an API key."""
    if not REQUESTS_AVAILABLE:
        return "Missing 'requests' library."
    if not _is_valid_youtube_url(url):
        return "Invalid YouTube URL provided."

    video_id = _extract_video_id(url)
    target_url = f"https://www.youtube.com/watch?v={video_id}"
    
    try:
        r = requests.get(target_url, headers=HEADERS, timeout=10)
        html = r.text
        
        title = re.search(r'"title":\{"runs":\[\{"text":"([^"]+)"', html)
        channel = re.search(r'"ownerChannelName":"([^"]+)"', html)
        views = re.search(r'"viewCount":"(\d+)"', html)
        
        info = []
        if title: info.append(f"Title: {title.group(1)}")
        if channel: info.append(f"Channel: {channel.group(1)}")
        if views: info.append(f"Views: {int(views.group(1)):,}")
        
        return "\n".join(info) if info else "Could not parse video details."
        
    except Exception as e:
        return f"Scraping failed: {e}"

def _handle_trending(region: str = "US") -> str:
    """Scrapes the current YouTube trending page."""
    if not REQUESTS_AVAILABLE:
        return "Missing 'requests' library."

    url = f"https://www.youtube.com/feed/trending?gl={region.upper()}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        
        titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]', r.text)
        channels = re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', r.text)
        
        if not titles:
            return "No trending data could be parsed."
            
        results = [f"Top Trending ({region.upper()}):"]
        seen = set()
        count = 1
        
        for i, t in enumerate(titles):
            if t in seen or len(t) < 5: continue
            seen.add(t)
            c = channels[i] if i < len(channels) else "Unknown"
            results.append(f"{count}. {t} — {c}")
            count += 1
            if count > 5: break
            
        return "\n".join(results)
    except Exception as e:
        return f"Trending fetch failed: {e}"

# ─── LLM DISPATCHER INTERFACE ───────────────────────────────────────────

def youtube_video(parameters: dict, response=None, player=None, session_memory=None) -> str:
    """Entry point for tool-dispatch calling from Luna's cognitive layer."""
    params = parameters or {}
    action = params.get("action", "play").lower().strip()
    query = params.get("query", "").strip()
    url = params.get("url", "").strip()

    if player:
        player.write_log(f"[YouTube] Executing action: {action}")

    if action == "play":
        return _handle_play(query)
    elif action == "download":
        return _handle_download(url)
    elif action == "summarize":
        return _handle_summarize(url)
    elif action in ["info", "get_info"]:
        return _handle_get_info(url)
    elif action == "trending":
        region = params.get("region", "US")
        return _handle_trending(region)
    else:
        return f"Unknown YouTube action: '{action}'"


# ─── STANDALONE INTERACTIVE TEST MODE ───────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(levelname)s: %(message)s")

    print("=" * 65)
    print("AURIX YouTube Controller -- Standalone Test Mode")
    print("Commands:")
    print("  play <query>       - Opens Chrome Guest Mode and plays video")
    print("  download <url>     - Downloads the video to your local machine")
    print("  info <url>         - Fetches metadata for a YouTube video")
    print("  summarize <url>    - Generates an AI summary of a video")
    print("  trending <region>  - Lists top 5 trending videos (e.g. US, TR)")
    print("  exit               - Quit")
    print("=" * 65)

    while True:
        try:
            raw_input = input("\n[YouTube] >>> ").strip()
            if not raw_input:
                continue

            cmd_lower = raw_input.lower()
            if cmd_lower in ["exit", "quit"]:
                break

            if cmd_lower.startswith("play "):
                print(youtube_video({"action": "play", "query": raw_input[5:].strip()}))
            elif cmd_lower.startswith("download "):
                print(youtube_video({"action": "download", "url": raw_input[9:].strip()}))
            elif cmd_lower.startswith("info "):
                print(youtube_video({"action": "info", "url": raw_input[5:].strip()}))
            elif cmd_lower.startswith("summarize "):
                print(youtube_video({"action": "summarize", "url": raw_input[10:].strip()}))
            elif cmd_lower.startswith("trending "):
                print(youtube_video({"action": "trending", "region": raw_input[9:].strip()}))
            elif cmd_lower == "trending":
                print(youtube_video({"action": "trending"}))
            else:
                print("Unknown command. Check available commands above.")

        except KeyboardInterrupt:
            break