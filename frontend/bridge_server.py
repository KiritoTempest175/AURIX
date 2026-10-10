#!/usr/bin/env python3
"""Private AURIX loopback bridge.

Only the Tauri-owned process knows AURIX_BRIDGE_TOKEN. No browser CORS
access is allowed. This is an interim transport until named-pipe IPC ships.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG = logging.getLogger("aurix.bridge")
MAX_BODY = 64 * 1024
_dispatcher = None
_dispatcher_lock = threading.Lock()
_execute_lock = threading.Lock()


def dispatcher():
    global _dispatcher
    with _dispatcher_lock:
        if _dispatcher is None:
            from ai_brain.dispatcher import BrainDispatcher
            _dispatcher = BrainDispatcher()
        return _dispatcher


def telemetry() -> dict:
    try:
        import psutil
        return {
            "cpu": round(psutil.cpu_percent(interval=None), 1),
            "ram": round(psutil.virtual_memory().percent, 1),
            "gpu": None,
            "gpu_temp": None,
        }
    except ImportError:
        return {"cpu": None, "ram": None, "gpu": None, "gpu_temp": None}


class SecureServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, token: str):
        super().__init__(address, handler)
        self.token = token
        self.limit = threading.BoundedSemaphore(8)

    def process_request(self, request, client_address):
        if not self.limit.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.limit.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.limit.release()


class BridgeHandler(BaseHTTPRequestHandler):
    server: SecureServer

    def _json(self, value: dict, status: int = 200):
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        port = self.server.server_port
        host = self.headers.get("Host", "").lower()
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        # A browser is not an authorized client. Neither CORS nor preflight
        # responses are granted, even when browser JS knows a port.
        if self.headers.get("Origin") is not None:
            return False
        expected = "Bearer " + self.server.token
        return secrets.compare_digest(
            self.headers.get("Authorization", ""), expected
        )

    def _body(self) -> dict:
        size = self.headers.get("Content-Length")
        if size is None or not size.isdecimal():
            raise ValueError("CONTENT_LENGTH_REQUIRED")
        length = int(size)
        if length > MAX_BODY:
            raise OverflowError("PAYLOAD_TOO_LARGE")
        if length == 0:
            raise ValueError("EMPTY_BODY")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("OBJECT_REQUIRED")
        return data

    def do_OPTIONS(self):
        self._json({"error": "METHOD_NOT_ALLOWED"}, 405)

    def do_GET(self):
        if not self._authorized():
            return self._json({"error": "UNAUTHORIZED"}, 401)
        if self.path == "/health":
            return self._json({"status": "ok", "model": "not-verified"})
        if self.path == "/telemetry":
            return self._json(telemetry())
        self._json({"error": "NOT_FOUND"}, 404)

    def do_POST(self):
        if not self._authorized():
            return self._json({"error": "UNAUTHORIZED"}, 401)
        try:
            data = self._body()
        except OverflowError:
            return self._json({"error": "PAYLOAD_TOO_LARGE"}, 413)
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return self._json({"error": "INVALID_JSON"}, 400)

        if self.path not in ("/dispatch", "/trust_preview", "/execute_trust"):
            return self._json({"error": "NOT_FOUND"}, 404)

        with _execute_lock:
            try:
                brain = dispatcher()
                if self.path == "/dispatch":
                    message = data.get("text")
                    if not isinstance(message, str) or len(message) > 16000:
                        return self._json({"error": "INVALID_MESSAGE"}, 400)
                    reply, action = brain.dispatch(message.strip())
                    return self._json({"reply": reply, "action": bool(action)})
                request = data.get("request")
                if not isinstance(request, str) or len(request) > 512:
                    return self._json({"error": "INVALID_REQUEST"}, 400)
                if self.path == "/trust_preview":
                    return self._json(brain.executor.preview_pending(request))
                # The Rust Tauri command must first show the native OS dialog.
                return self._json({"result": brain.execute_trust_token(request)})
            except Exception:
                LOG.exception("Worker operation failed")
                return self._json({"error": "WORKER_FAILURE"}, 500)

    def log_message(self, fmt, *args):
        LOG.debug(fmt, *args)


def main():
    logging.basicConfig(level=logging.INFO)
    token = os.environ.get("AURIX_BRIDGE_TOKEN", "")
    if len(token) < 40:
        raise SystemExit("Bridge requires a Tauri-generated session secret")
    server = SecureServer(("127.0.0.1", 9721), BridgeHandler, token)
    LOG.info("Private bridge running on 127.0.0.1 (authenticated)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
