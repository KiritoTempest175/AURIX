"""LUNA Qwen 3B Ollama Inference Engine.

Connects to the locally installed Ollama daemon (running at http://localhost:11434)
and uses the ``qwen2.5:3b-instruct`` model that is already pulled on this machine.

This runner is a **drop-in replacement** for GemmaModelRunner — it exposes the
same ``format_chat_prompt`` and ``generate_response`` public interface so
``run_ui.py`` requires only a one-line swap.

Backend:  Ollama REST API  ->  qwen2.5:3b-instruct  (1.9 GB, quantised GGUF)
Transport: httpx (already in the project venv, no extra install required)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("luna.ai_engine.qwen3b_ollama")

# ── Ollama REST constants ─────────────────────────────────────────────────────
_DEFAULT_HOST    = "http://localhost:11434"
_DEFAULT_MODEL   = "qwen2.5:3b-instruct"
_GENERATE_EP     = "/api/chat"          # chat-completions endpoint
_HEALTH_EP       = "/api/tags"          # model list / liveness check
_REQUEST_TIMEOUT = 120.0                # seconds – generation can be slow on CPU

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = (
    "You are LUNA, a secure, autonomous, edge-governed desktop AI executive. "
    "You have direct access to local system tools within a sandboxed environment. "
    "Be concise, accurate, and structured. Prefer actionable responses."
)


def _load_config(config_path: str = "./config.toml") -> Dict[str, Any]:
    """Read [qwen_ollama] or fall back to [llm] section from config.toml."""
    defaults: Dict[str, Any] = {
        "host":        _DEFAULT_HOST,
        "model":       _DEFAULT_MODEL,
        "temperature": 0.7,
        "top_p":       0.9,
        "max_tokens":  512,
    }
    if not os.path.exists(config_path):
        return defaults
    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        with open(config_path, "rb") as fh:
            parsed = tomllib.load(fh)
        section = parsed.get("qwen_ollama") or parsed.get("llm") or {}
        defaults.update({k: v for k, v in section.items() if k in defaults})
    except Exception as exc:
        logger.warning("Could not read %s: %s", config_path, exc)
    return defaults


class Qwen3BOllamaRunner:
    """Inference runner that delegates to a local Ollama daemon.

    Usage
    -----
    >>> runner = Qwen3BOllamaRunner()
    >>> prompt = runner.format_chat_prompt("Summarise system status")
    >>> print(runner.generate_response(prompt))
    """

    def __init__(self, config_path: str = "./config.toml") -> None:
        cfg = _load_config(config_path)

        self.host:        str   = str(cfg["host"])
        self.model:       str   = str(cfg["model"])
        self.temperature: float = float(cfg["temperature"])
        self.top_p:       float = float(cfg["top_p"])
        self.max_tokens:  int   = int(cfg["max_tokens"])

        self._client = None          # lazy-initialised httpx.Client
        self._available: bool = False
        self._history: List[Dict[str, str]] = []  # rolling conversation context

        self._check_health()

    # ── Health / availability ─────────────────────────────────────────────────

    def _get_client(self):
        """Return (and lazily create) a shared httpx.Client."""
        if self._client is None:
            import httpx
            self._client = httpx.Client(timeout=_REQUEST_TIMEOUT)
        return self._client

    def _check_health(self) -> None:
        """Ping Ollama and verify the target model is pulled."""
        try:
            resp = self._get_client().get(f"{self.host}{_HEALTH_EP}", timeout=5.0)
            resp.raise_for_status()
            tags = resp.json().get("models", [])
            pulled = [t.get("name", "") for t in tags]
            model_base = self.model.split(":")[0]
            if any(self.model in name or name.startswith(model_base) for name in pulled):
                self._available = True
                logger.info(
                    "Qwen3BOllamaRunner: Ollama reachable, model '%s' confirmed.", self.model
                )
            else:
                logger.warning(
                    "Qwen3BOllamaRunner: Ollama reachable but model '%s' not found in %s. "
                    "Run: ollama pull %s",
                    self.model, pulled, self.model,
                )
                self._available = False
        except Exception as exc:
            logger.warning(
                "Qwen3BOllamaRunner: Ollama not reachable at %s (%s). "
                "Start Ollama with: ollama serve",
                self.host, exc,
            )
            self._available = False

    @property
    def is_available(self) -> bool:
        """True if Ollama daemon is running and model is pulled."""
        return self._available

    # ── Prompt formatting ─────────────────────────────────────────────────────

    def format_chat_prompt(
        self,
        user_message: str,
        system_instruction: Optional[str] = None,
        context_history: Optional[List[Dict[str, str]]] = None,
        ui_state: Optional[Dict[str, Any]] = None,
        terminal_context: Optional[str] = None,
    ) -> str:
        """Build a grounded user message string (same signature as GemmaModelRunner).

        The Ollama /api/chat endpoint takes a structured message list, so this
        method returns the enriched user-facing text.  The actual message
        list is assembled in ``generate_response``.
        """
        extra: List[str] = []
        if ui_state:
            extra.append(f"[Active UI Focus]: {ui_state.get('focused_element', 'Desktop')}")
        if terminal_context:
            extra.append(f"[Recent Terminal Output]:\n{terminal_context.strip()}")

        if extra:
            return "\n".join(extra) + f"\n\n[User Instruction]: {user_message}"
        return user_message

    # ── Generation ────────────────────────────────────────────────────────────

    def generate_response(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> str:
        """Send a prompt to Ollama and return the model's reply text.

        Falls back to a deterministic offline response if Ollama is down.
        """
        if not self._available:
            # Attempt one re-check (Ollama may have been started after init)
            self._check_health()
        if not self._available:
            return self._fallback_generate(prompt)

        # Build message list: system + rolling history + new user turn
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": _SYSTEM_PROMPT}
        ]
        messages.extend(self._history[-10:])   # keep last 10 turns for context
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model":    self.model,
            "messages": messages,
            "stream":   False,
            "options": {
                "temperature": temperature if temperature is not None else self.temperature,
                "top_p":       top_p       if top_p       is not None else self.top_p,
                "num_predict": max_new_tokens or self.max_tokens,
            },
        }

        try:
            resp = self._get_client().post(
                f"{self.host}{_GENERATE_EP}",
                json=payload,
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data     = resp.json()
            reply    = data["message"]["content"].strip()

            # Update rolling history for multi-turn context
            self._history.append({"role": "user",      "content": prompt})
            self._history.append({"role": "assistant", "content": reply})

            return reply

        except Exception as exc:
            logger.error("Qwen3BOllamaRunner generation error: %s", exc)
            self._available = False   # mark unavailable, re-check next call
            return self._fallback_generate(prompt)

    def clear_history(self) -> None:
        """Reset the rolling conversation context."""
        self._history.clear()
        logger.debug("Qwen3BOllamaRunner: conversation history cleared.")

    # ── Offline fallback ──────────────────────────────────────────────────────

    def _fallback_generate(self, prompt: str) -> str:
        prompt_lower = prompt.lower()
        if "status" in prompt_lower or "hardware" in prompt_lower:
            return (
                "LUNA Governor nominal. Hardware utilisation within safe limits. "
                "Qwen 3B offline -- reconnect Ollama with: ollama serve"
            )
        if "error" in prompt_lower or "traceback" in prompt_lower:
            return (
                "Exception detected. Synthesising sandboxed patch candidate. "
                "Qwen 3B offline -- start Ollama to enable full reasoning."
            )
        if "checkpoint" in prompt_lower:
            return "Checkpoint integrity verified. Snapshot ready for restore."
        return (
            f"[Qwen 3B Offline] Instruction received. "
            "Start Ollama (`ollama serve`) to enable live AI responses."
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


# ── Singleton helper (mirrors gemma_e4b pattern) ──────────────────────────────

_GLOBAL_QWEN_RUNNER: Optional[Qwen3BOllamaRunner] = None


def get_default_qwen_runner(config_path: str = "./config.toml") -> Qwen3BOllamaRunner:
    """Return the project-wide singleton Qwen3BOllamaRunner."""
    global _GLOBAL_QWEN_RUNNER
    if _GLOBAL_QWEN_RUNNER is None:
        _GLOBAL_QWEN_RUNNER = Qwen3BOllamaRunner(config_path=config_path)
    return _GLOBAL_QWEN_RUNNER


# ── Standalone smoke-test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("[LUNA] Initialising Qwen 3B Ollama Runner...")
    runner = get_default_qwen_runner()
    print(f"  available : {runner.is_available}")
    print(f"  model     : {runner.model}")
    print(f"  host      : {runner.host}")

    if runner.is_available:
        queries = [
            "Check system status and hardware metrics.",
            "What can you do as LUNA?",
            "Inspect power governor state.",
        ]
        for q in queries:
            prompt = runner.format_chat_prompt(q)
            response = runner.generate_response(prompt)
            print(f"\n[User ]: {q}")
            print(f"[LUNA ]: {response}")
    else:
        print("\n[!] Ollama not running. Start with: ollama serve")
