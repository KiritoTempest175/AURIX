#!/usr/bin/env python3
"""
AURIX Bridge Server
-------------------
Lightweight HTTP JSON API that exposes the AURIX AI brain to the
Tauri desktop frontend. Runs on localhost:9721 by default.

The Tauri frontend (Rust side) spawns this process as a sidecar and
communicates via simple HTTP requests.

Endpoints:
    POST /dispatch        {"text": "..."}       -> {"reply": "...", "action": false}
    GET  /telemetry                              -> {"cpu": .., "ram": .., "gpu": .., "gpu_temp": ..}
    POST /execute_trust   {"request": "..."}     -> {"result": "..."}
    GET  /health                                 -> {"status": "ok"}
"""

from __future__ import annotations

import json
import logging
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict

# Ensure project root is on sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# UTF-8 safety for Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aurix.bridge")

# ---------------------------------------------------------------------------
# Telemetry (psutil-based, graceful fallback)
# ---------------------------------------------------------------------------
try:
    import psutil

    def get_telemetry() -> Dict[str, float]:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        ram = mem.percent
        # GPU data requires pynvml or similar — placeholder for now
        return {"cpu": round(cpu, 1), "ram": round(ram, 1), "gpu": 0.0, "gpu_temp": 0.0}

except ImportError:
    logger.warning("psutil not installed — telemetry will return demo values")

    def get_telemetry() -> Dict[str, float]:
        return {"cpu": 0.0, "ram": 0.0, "gpu": 0.0, "gpu_temp": 0.0}


# ---------------------------------------------------------------------------
# AI Brain (lazy init)
# ---------------------------------------------------------------------------
_dispatcher = None


def _get_dispatcher():
    global _dispatcher
    if _dispatcher is None:
        try:
            from ai_brain.dispatcher import BrainDispatcher
            _dispatcher = BrainDispatcher()
            logger.info("BrainDispatcher initialized successfully")
        except Exception as exc:
            logger.error("Failed to initialize BrainDispatcher: %s", exc)
            _dispatcher = None
    return _dispatcher


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------
class BridgeHandler(BaseHTTPRequestHandler):
    """Minimal JSON API handler."""

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # CORS for local dev (Vite dev-server on different port)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    # --- Routes ----------------------------------------------------------

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self._send_json({})

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"status": "ok"})
        elif self.path == "/telemetry":
            self._send_json(get_telemetry())
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/dispatch":
            data = self._read_json()
            text = data.get("text", "").strip()
            if not text:
                self._send_json({"reply": "", "action": False})
                return

            dispatcher = _get_dispatcher()
            if dispatcher is None:
                self._send_json({
                    "reply": "AI brain is not available. Check server logs.",
                    "action": False,
                })
                return

            try:
                reply, action = dispatcher.dispatch(text)
                self._send_json({"reply": reply, "action": action})
            except Exception as exc:
                logger.exception("dispatch error")
                self._send_json({
                    "reply": f"Error: {exc}",
                    "action": False,
                })

        elif self.path == "/execute_trust":
            data = self._read_json()
            request = data.get("request", "").strip()

            dispatcher = _get_dispatcher()
            if dispatcher is None:
                self._send_json({"result": "AI brain is not available."})
                return

            try:
                result = dispatcher.execute_trust_token(request)
                self._send_json({"result": result})
            except Exception as exc:
                logger.exception("execute_trust error")
                self._send_json({"result": f"Error: {exc}"})

        else:
            self._send_json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        """Route HTTP logs through the standard logger."""
        logger.debug(fmt, *args)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    host = os.environ.get("AURIX_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("AURIX_BRIDGE_PORT", "9721"))

    server = HTTPServer((host, port), BridgeHandler)
    logger.info("AURIX Bridge Server listening on http://%s:%d", host, port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Bridge server shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
