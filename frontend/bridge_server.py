#!/usr/bin/env python3
"""Private AURIX loopback bridge.

Only the Tauri-owned process knows AURIX_BRIDGE_TOKEN. No browser CORS
access is allowed. This is an interim transport until named-pipe IPC ships.
"""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent.parent
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
from security.config_loader import program_root, install_user_config, user_data_root
ROOT = program_root()

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
    # Release an idle GGUF model without loading it merely to serve telemetry.
    if _dispatcher is not None:
        runner = getattr(_dispatcher.router, "_runner", None)
        if runner is not None and hasattr(runner, "unload_if_idle"):
            runner.unload_if_idle()
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
            try:
                from ai_engine.inference.ollama_runtime import get_model_runner
                runner = get_model_runner()
                return self._json({
                    "status": "ok", "model_ready": runner.is_available,
                    "model_loaded": getattr(runner, "_model", None) is not None,
                    "backend": runner.backend,
                })
            except Exception:
                return self._json({"status": "ok", "model_ready": False, "model_loaded": False})
        if self.path == "/telemetry":
            return self._json(telemetry())
        if self.path == "/models":
            from ai_engine.inference.ollama_runtime import (
                RECOMMENDED_MODELS, selection, installed_models,
            )
            chosen = selection()
            try:
                installed = installed_models()
                connected = True
            except (OSError, ValueError, RuntimeError):
                installed = []
                connected = False
            return self._json({
                "backend": chosen["backend"],
                "selected": chosen["model"],
                "ollama_connected": connected,
                "installed": installed,
                "recommendations": RECOMMENDED_MODELS,
            })
        if self.path == "/settings":
            from security.action_control import offline_mode, action_is_stopped
            from ai_brain.secure_memory import memory_enabled
            return self._json({"offline": offline_mode(), "stopped": action_is_stopped(),
                               "memory_enabled": memory_enabled()})
        if self.path == "/audit":
            from security.action_audit import default_audit
            try:
                ledger = default_audit()
                return self._json({
                    "enabled": ledger is not None,
                    "verified": ledger.verify() if ledger else False,
                    "events": ledger.recent(100) if ledger else [],
                })
            except Exception:
                LOG.exception("Audit read failed")
                return self._json({"error": "AUDIT_UNAVAILABLE"}, 503)
        if self.path == "/memory":
            from ai_brain.secure_memory import memory_enabled, get_memory_store
            if not memory_enabled():
                return self._json({"enabled": False, "items": []})
            try:
                return self._json({"enabled": True, "items": get_memory_store().list(100)})
            except Exception:
                LOG.exception("Memory could not be accessed")
                return self._json({"error": "MEMORY_UNAVAILABLE"}, 503)
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

        if self.path == "/kill":
            from security.action_control import stop_actions
            stop_actions()
            return self._json({"stopped": True, "note": "new actions blocked"})
        if self.path == "/resume":
            from security.action_control import resume_actions
            resume_actions()
            return self._json({"stopped": False})
        if self.path == "/models/activate":
            from ai_engine.inference.ollama_runtime import (
                set_selection, selection,
            )
            backend, model = data.get("backend"), data.get("model")
            try:
                if not isinstance(backend, str) or not isinstance(model, str):
                    return self._json({"error": "INVALID_MODEL"}, 400)
                result = set_selection(backend, model)
                return self._json(result)
            except ValueError as exc:
                code = str(exc)
                if code not in {"INVALID_BACKEND", "INVALID_MODEL", "MODEL_NOT_INSTALLED"}:
                    code = "INVALID_MODEL"
                return self._json({"error": code}, 400)
            except (OSError, TimeoutError):
                return self._json({"error": "OLLAMA_UNAVAILABLE"}, 503)
        if self.path == "/settings":
            if set(data) == {"offline"} and type(data.get("offline")) is bool:
                from security.action_control import set_offline_mode
                return self._json({"offline": set_offline_mode(data["offline"])})
            if set(data) == {"memory_enabled"} and type(data.get("memory_enabled")) is bool:
                from ai_brain.secure_memory import set_memory_enabled
                try:
                    return self._json({"memory_enabled": set_memory_enabled(data["memory_enabled"])})
                except Exception:
                    LOG.exception("Memory opt-in preflight or save failed")
                    return self._json({"error": "MEMORY_SETTINGS_UNAVAILABLE"}, 503)
            return self._json({"error": "INVALID_SETTINGS"}, 400)
        if self.path == "/memory":
            from ai_brain.secure_memory import memory_enabled, get_memory_store, KINDS
            if not memory_enabled():
                return self._json({"error": "MEMORY_DISABLED"}, 403)
            try:
                store = get_memory_store()
                action = data.get("action")
                if action == "add":
                    kind, content = data.get("kind"), data.get("content")
                    if kind not in KINDS or not isinstance(content, str):
                        return self._json({"error": "INVALID_MEMORY"}, 400)
                    return self._json({"id": store.add(kind, content)})
                if action == "delete":
                    key = data.get("id")
                    if not isinstance(key, str) or len(key) != 32 or not all(c in "0123456789abcdef" for c in key):
                        return self._json({"error": "INVALID_MEMORY_ID"}, 400)
                    return self._json({"deleted": store.delete(key)})
                return self._json({"error": "INVALID_ACTION"}, 400)
            except ValueError:
                return self._json({"error": "INVALID_MEMORY"}, 400)
            except Exception:
                LOG.exception("Memory operation failed")
                return self._json({"error": "MEMORY_UNAVAILABLE"}, 503)
        if self.path == "/voice/speak":
            try:
                from native_ui.audio.offline_tts import speak_async
                content = data.get("text")
                if not isinstance(content, str) or not 1 <= len(content.strip()) <= 800:
                    return self._json({"error": "INVALID_SPEECH"}, 400)
                speak_async(content.strip())
                return self._json({"queued": True})
            except RuntimeError as exc:
                error = str(exc)
                if not error.startswith("TTS_"):
                    error = "TTS_UNAVAILABLE"
                return self._json({"error": error}, 503)
            except Exception:
                LOG.exception("Local TTS failed to start")
                return self._json({"error": "TTS_UNAVAILABLE"}, 503)
        if self.path == "/voice/stop":
            from native_ui.audio.offline_tts import stop
            stop()
            return self._json({"stopped": True})
        if self.path == "/voice/transcribe":
            try:
                from native_ui.audio.offline_voice import transcribe_microphone
                return self._json({"text": transcribe_microphone()})
            except RuntimeError as exc:
                reason = str(exc)
                code = reason if reason in {"NO_STT_MODEL", "VOICE_BUSY", "VOICE_DEPENDENCY_MISSING"} else "VOICE_UNAVAILABLE"
                return self._json({"error": code}, 503)
            except Exception:
                LOG.exception("Local STT failed")
                return self._json({"error": "VOICE_UNAVAILABLE"}, 503)
        if self.path not in ("/dispatch", "/trust_preview", "/execute_trust", "/reject_trust"):
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
                if self.path == "/reject_trust":
                    return self._json({"rejected": brain.executor.reject_pending(request)})
                # The Rust Tauri command must first show the native OS dialog.
                return self._json({"result": brain.execute_trust_token(request)})
            except Exception:
                LOG.exception("Worker operation failed")
                return self._json({"error": "WORKER_FAILURE"}, 500)

    def log_message(self, fmt, *args):
        LOG.debug(fmt, *args)


def configure_worker_logging() -> Path:
    """Keep startup errors visible even in a --noconsole Windows executable."""
    path = user_data_root() / "logs" / "worker.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")],
        force=True,
    )
    return path


def main():
    configure_worker_logging()
    LOG.info("Starting AURIX Python bridge")
    if getattr(sys, "frozen", False):
        install_user_config()
    token = os.environ.get("AURIX_BRIDGE_TOKEN", "")
    if len(token) < 40:
        raise SystemExit("Bridge requires a Tauri-generated session secret")
    server = SecureServer(("127.0.0.1", 9721), BridgeHandler, token)
    LOG.info("Private bridge running on 127.0.0.1 (authenticated)")
    def reap_idle_model():
        while not stop_reaper.wait(10.0):
            if _dispatcher is not None:
                runner = getattr(_dispatcher.router, "_runner", None)
                if runner is not None and hasattr(runner, "unload_if_idle"):
                    try:
                        runner.unload_if_idle()
                    except Exception:
                        LOG.exception("Could not release idle model")
    stop_reaper = threading.Event()
    reaper = threading.Thread(target=reap_idle_model, name="model-unloader", daemon=True)
    reaper.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_reaper.set()
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        LOG.exception("AURIX worker startup failed")
        raise
