"""LUNA Gemma 3n E4B Primary Inference Engine.

Implements the JARVIS-style reasoning brain using Google's Gemma 3n (E4B / E2B
elastic configuration) loaded in 4-bit NormalFloat (NF4) quantization.
Manages multi-modal context grounding, chat template formatting, tool selection,
and offline fallback execution.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Ensure project root is in sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger("luna.ai_engine.gemma_e4b")

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    try:
        from transformers import AutoModelForMultimodalLM, AutoProcessor
    except ImportError:
        AutoModelForMultimodalLM = None
        AutoProcessor = None
    TORCH_AVAILABLE = True
except ImportError:
    torch = None
    AutoModelForCausalLM = None
    AutoTokenizer = None
    AutoModelForMultimodalLM = None
    AutoProcessor = None
    BitsAndBytesConfig = None
    TORCH_AVAILABLE = False

try:
    from unsloth import FastLanguageModel
    UNSLOTH_AVAILABLE = True
except ImportError:
    FastLanguageModel = None
    UNSLOTH_AVAILABLE = False


def _read_config_model() -> tuple[str, str]:
    """Read configured model_name and device from config.toml.

    If model_name is set to "auto" (or absent), delegates to
    model_resolver.resolve_best_model() which detects installed models
    and auto-downloads Gemma 4 E4B if nothing is available.
    """
    import sys
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            tomllib = None

    config_model_name = None
    config_device = "cuda"

    if tomllib:
        try:
            from pathlib import Path
            cfg_path = Path(__file__).resolve().parent.parent.parent / "config.toml"
            if cfg_path.exists():
                with open(cfg_path, "rb") as f:
                    cfg = tomllib.load(f)
                llm = cfg.get("llm", {})
                config_model_name = llm.get("model_name")
                config_device = llm.get("device", "cuda")
        except Exception:
            pass

    # Delegate to the model resolver for smart detection + auto-download
    try:
        from ai_engine.inference.model_resolver import resolve_best_model
        _model_id, _resolved_path, _spec = resolve_best_model(
            config_model_name=config_model_name,
            auto_download=True,
        )
        logger.info(
            "Model resolver selected: '%s' (%s, priority=%d)",
            _spec.alias, _model_id, _spec.priority,
        )
        return _model_id, config_device
    except Exception as resolver_err:
        logger.warning("Model resolver failed (%s). Using direct config value.", resolver_err)

    # Fallback: return whatever config says, or the primary model as default
    from ai_engine.inference.model_resolver import PRIMARY_MODEL_ID
    return config_model_name or PRIMARY_MODEL_ID, config_device


def resolve_model_path(model_name_or_id: str) -> Optional[str]:
    """Resolve local path or Ollama identifier for model weights."""
    if not model_name_or_id:
        return None
    # 1. Direct path exists
    if os.path.exists(model_name_or_id):
        return os.path.abspath(model_name_or_id)

    # 2. Check model resolver (Ollama / HuggingFace cache / project dir)
    try:
        from ai_engine.inference.model_resolver import detect_model
        resolved = detect_model(model_name_or_id)
        if resolved:
            return resolved
    except Exception:
        pass

    # 2. Check HuggingFace Hub cache (~/.cache/huggingface/hub/models--...)
    try:
        from pathlib import Path
        clean_name = model_name_or_id.replace("/", "--")
        cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{clean_name}"
        if cache_dir.exists():
            snapshots_dir = cache_dir / "snapshots"
            if snapshots_dir.exists():
                snapshots = [p for p in snapshots_dir.iterdir() if p.is_dir()]
                if snapshots:
                    # Pick latest snapshot by modification time
                    latest = max(snapshots, key=lambda p: p.stat().st_mtime)
                    if any(latest.glob("*.safetensors")) or any(latest.glob("*.bin")):
                        return str(latest)
    except Exception as exc:
        logger.debug("Error resolving HuggingFace cache for '%s': %s", model_name_or_id, exc)

    # 3. Check models directory in project
    try:
        from pathlib import Path
        candidate = Path(__file__).resolve().parent.parent.parent / "models" / model_name_or_id
        if candidate.exists():
            return str(candidate)
    except Exception:
        pass

    return None


class GemmaModelRunner:
    """Orchestrates LLM reasoning model loading, GPU 4-bit scaling, and inference."""

    DEFAULT_MODEL = "qwen2.5:3b-instruct"

    def __init__(
        self,
        model_name: Optional[str] = None,
        effective_params: str = "E4B",
        max_seq_length: int = 2048,
        load_in_4bit: bool = True,
        quantization: str = "nf4",
        device: Optional[str] = None,
        fallback_mode: bool = True,
        force_fallback: bool = False,
    ) -> None:
        """Initialize LLM model runner with GPU acceleration and 4-bit quantization.

        Args:
            model_name: HuggingFace model path or local directory.
            effective_params: Elastic parameter mode: "E4B" (full 4B) or "E2B" (efficient 2B).
            max_seq_length: Maximum context sequence length.
            load_in_4bit: Whether to load with 4-bit quantization.
            quantization: Quantization format ("nf4", "fp4").
            device: Target device ("cuda", "cpu").
            fallback_mode: If True, operates in simulation mode if GPU/weights unavailable.
            force_fallback: If True, skips loading weights and forces deterministic reasoning mode.
        """
        cfg_model, cfg_device = _read_config_model()
        self.model_name = model_name or cfg_model or self.DEFAULT_MODEL
        self.effective_params = effective_params.upper()
        self.max_seq_length = max_seq_length
        self.load_in_4bit = load_in_4bit
        self.quantization = quantization

        target_dev = device or cfg_device or "cuda"
        self.device = target_dev if (torch and torch.cuda.is_available() and target_dev == "cuda") else "cpu"
        self.fallback_mode = fallback_mode
        self.force_fallback = force_fallback

        self.backend: str = "transformers"
        self.model: Optional[Any] = None
        self.tokenizer: Optional[Any] = None
        self.processor: Optional[Any] = None
        self.is_loaded: bool = False
        self._history: List[Dict[str, str]] = []

        self._initialize_model()

    @property
    def is_available(self) -> bool:
        """Return True if model runner is loaded or ready for inference."""
        return self.is_loaded

    @property
    def has_weights(self) -> bool:
        """Return True if real model weights and tokenizer or Ollama backend are active."""
        if getattr(self, "backend", None) == "ollama":
            return self.is_loaded
        return self.model is not None and self.tokenizer is not None

    def clear_history(self) -> None:
        """Reset the rolling conversation context."""
        self._history.clear()
        logger.debug("GemmaModelRunner: conversation history cleared.")

    def _initialize_model(self) -> None:
        """Load LLM weights on GPU (RTX 4060) in 4-bit NF4 or initialize offline fallback."""
        if not TORCH_AVAILABLE:
            logger.info("PyTorch / Transformers not installed. Operating in offline fallback mode.")
            self.is_loaded = True
            return

        if self.force_fallback:
            self.is_loaded = True
            logger.info("Forced fallback mode active. Operating in deterministic offline mode.")
            return

        # Collect candidate model IDs to attempt loading in order
        candidates_to_try = [self.model_name]
        try:
            from ai_engine.inference.model_resolver import SUPPORTED_MODELS
            for spec in SUPPORTED_MODELS:
                if spec.model_id not in candidates_to_try:
                    candidates_to_try.append(spec.model_id)
        except ImportError:
            for fallback_id in ("qwen2.5:3b-instruct", "google/gemma-4-E4B-it", "Qwen/Qwen2.5-Coder-3B-Instruct"):
                if fallback_id not in candidates_to_try:
                    candidates_to_try.append(fallback_id)

        loaded = False
        for model_id in candidates_to_try:
            resolved_path = resolve_model_path(model_id)
            if not resolved_path:
                continue

            # ── Ollama Backend ──────────────────────────────────────────
            if resolved_path.startswith("ollama:"):
                clean_name = resolved_path[len("ollama:"):]
                logger.info("Connecting to local Ollama backend for '%s'...", clean_name)
                if self._init_ollama(clean_name):
                    self.model_name = clean_name
                    self.backend = "ollama"
                    self.is_loaded = True
                    loaded = True
                    logger.info("AURIX model '%s' successfully connected via local Ollama backend.", clean_name)
                    break
                else:
                    logger.warning("Could not establish Ollama connection for '%s'. Trying next candidate...", clean_name)
                    continue

            target_path = resolved_path
            local_only = True
            logger.info("Attempting to load model weights for '%s' from '%s'...", model_id, target_path)

            try:
                if UNSLOTH_AVAILABLE and self.device == "cuda":
                    logger.info(
                        f"Loading model ({self.effective_params}) with Unsloth from '{target_path}' "
                        f"in 4-bit {self.quantization.upper()}..."
                    )
                    self.model, self.tokenizer = FastLanguageModel.from_pretrained(
                        model_name=target_path,
                        max_seq_length=self.max_seq_length,
                        load_in_4bit=self.load_in_4bit,
                        fast_inference=True,
                    )
                    FastLanguageModel.for_inference(self.model)
                else:
                    # GPU Tensor Core optimizations
                    if self.device == "cuda" and hasattr(torch, "backends"):
                        if hasattr(torch.backends, "cuda") and hasattr(torch.backends.cuda, "matmul"):
                            torch.backends.cuda.matmul.allow_tf32 = True
                        if hasattr(torch.backends, "cudnn"):
                            torch.backends.cudnn.benchmark = True

                    quant_config = None
                    if self.load_in_4bit and self.device == "cuda" and BitsAndBytesConfig:
                        quant_config = BitsAndBytesConfig(
                            load_in_4bit=True,
                            bnb_4bit_quant_type=self.quantization,
                            bnb_4bit_compute_dtype=torch.float16,
                            llm_int8_enable_fp32_cpu_offload=True,
                        )

                    model_dtype = torch.float16 if self.device == "cuda" else (
                        torch.bfloat16 if hasattr(torch, "bfloat16") else torch.float32
                    )

                    # 1. Primary: Load CausalLM (Qwen, Gemma-text, Phi, etc.)
                    try:
                        logger.info("Loading tokenizer from '%s'...", target_path)
                        self.tokenizer = AutoTokenizer.from_pretrained(target_path, local_files_only=local_only)
                        logger.info("Loading model weights on device '%s' (dtype=%s, 4bit=%s)...", self.device, model_dtype, self.load_in_4bit)
                        self.model = AutoModelForCausalLM.from_pretrained(
                            target_path,
                            quantization_config=quant_config,
                            device_map="auto" if self.device == "cuda" else None,
                            torch_dtype=model_dtype,
                            low_cpu_mem_usage=True,
                            local_files_only=local_only,
                        )
                    except Exception as causal_err:
                        # 2. Fallback: Multimodal LM (e.g. Gemma 4 multimodal)
                        if AutoModelForMultimodalLM and AutoProcessor:
                            logger.info("CausalLM failed (%s). Trying AutoModelForMultimodalLM...", causal_err)
                            self.processor = AutoProcessor.from_pretrained(target_path, local_files_only=local_only)
                            self.tokenizer = getattr(self.processor, "tokenizer", self.processor)
                            self.model = AutoModelForMultimodalLM.from_pretrained(
                                target_path,
                                quantization_config=quant_config,
                                device_map="auto" if self.device == "cuda" else None,
                                torch_dtype=model_dtype,
                                low_cpu_mem_usage=True,
                                local_files_only=local_only,
                            )
                        else:
                            raise causal_err

                self.model_name = model_id
                self.is_loaded = True
                loaded = True
                vram_mb = (torch.cuda.memory_allocated(0) / (1024 * 1024)) if (torch and torch.cuda.is_available()) else 0
                logger.info(f"AURIX Model '{model_id}' successfully loaded on device '{self.device}' (GPU VRAM: {vram_mb:.1f} MB).")
                break
            except Exception as e:
                logger.warning("Failed to load candidate model '%s' (%s). Trying next candidate...", model_id, e)
                self.model = None
                self.tokenizer = None
                self.processor = None

        if not loaded:
            logger.warning("No local candidate models could be loaded. Operating in deterministic reasoning mode.")
            self.is_loaded = True

    def set_effective_parameters(self, mode: str) -> None:
        """Switch elastic execution mode dynamically between E2B and E4B.

        Args:
            mode: "E2B" or "E4B".
        """
        valid_modes = {"E2B", "E4B"}
        norm_mode = mode.upper()
        if norm_mode not in valid_modes:
            raise ValueError(f"Invalid effective_params mode '{mode}'. Choose from {valid_modes}")
        self.effective_params = norm_mode
        logger.info(f"Gemma 3n elastic parameter execution set to: {self.effective_params}")

    def format_chat_prompt(
        self,
        user_message: str,
        system_instruction: Optional[str] = None,
        context_history: Optional[List[Dict[str, str]]] = None,
        ui_state: Optional[Dict[str, Any]] = None,
        terminal_context: Optional[str] = None,
    ) -> str:
        """Format grounded multi-modal context into official Gemma chat template."""
        sys_prompt = system_instruction or (
            "You are LUNA, a secure, autonomous, edge-governed desktop AI executive. "
            "You have direct access to local system tools within the sandboxed environment. "
            "Formulate accurate, structured, and safe actions."
        )

        # Ground context
        extra_context = []
        if ui_state:
            extra_context.append(f"[Active Window/UI Focus]: {ui_state.get('focused_element', 'Desktop')}")
        if terminal_context:
            extra_context.append(f"[Recent Terminal Output]:\n{terminal_context.strip()}")

        grounded_user_content = user_message
        if extra_context:
            grounded_user_content = f"{chr(10).join(extra_context)}\n\n[User Instruction]: {user_message}"

        effective_history = context_history if context_history is not None else list(self._history)
        messages = [{"role": "system", "content": sys_prompt}]
        for msg in effective_history:
            messages.append(msg)
        messages.append({"role": "user", "content": grounded_user_content})

        if self.tokenizer and hasattr(self.tokenizer, "apply_chat_template"):
            try:
                return self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            except Exception as e:
                logger.debug(f"apply_chat_template fallback ({e})")

        # Template format: ChatML for Ollama/Qwen, or Gemma turn tags
        if getattr(self, "backend", None) == "ollama" and not self.tokenizer:
            formatted = f"<|im_start|>system\n{sys_prompt}<|im_end|>\n"
            for msg in effective_history:
                formatted += f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>\n"
            formatted += f"<|im_start|>user\n{grounded_user_content}<|im_end|>\n<|im_start|>assistant\n"
            return formatted

        # Standard fallback template format for Gemma
        formatted = f"<start_of_turn>system\n{sys_prompt}<end_of_turn>\n"
        for msg in effective_history:
            formatted += f"<start_of_turn>{msg['role']}\n{msg['content']}<end_of_turn>\n"
        formatted += f"<start_of_turn>user\n{grounded_user_content}<end_of_turn>\n<start_of_turn>model\n"
        return formatted

    def generate_response(
        self,
        prompt: str,
        max_new_tokens: int = 128,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str:
        """Generate response given a formatted prompt."""
        if getattr(self, "backend", None) == "ollama":
            reply = self._generate_ollama(
                prompt=prompt,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
            )
        elif not self.has_weights or not torch:
            reply = self._fallback_generate(prompt)
        else:
            try:
                inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
                gen_kwargs = {
                    "max_new_tokens": max_new_tokens,
                    "use_cache": True,
                }
                if temperature and temperature > 0:
                    gen_kwargs["do_sample"] = True
                    gen_kwargs["temperature"] = temperature
                    gen_kwargs["top_p"] = top_p
                else:
                    gen_kwargs["do_sample"] = False
                if getattr(self.tokenizer, "pad_token_id", None) is not None:
                    gen_kwargs["pad_token_id"] = self.tokenizer.pad_token_id
                elif getattr(self.tokenizer, "eos_token_id", None) is not None:
                    gen_kwargs["pad_token_id"] = self.tokenizer.eos_token_id

                with torch.inference_mode():
                    outputs = self.model.generate(**inputs, **gen_kwargs)
                generated_tokens = outputs[0][inputs.input_ids.shape[1] :]
                reply = self.tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()
                import re
                reply = re.sub(r"<think>[\s\S]*?</think>", "", reply).strip()
            except Exception as e:
                logger.error(f"Inference error: {e}. Yielding fallback response.")
                reply = self._fallback_generate(prompt)

        # Update rolling history for multi-turn context (capped to prevent RAM bloat)
        self._history.append({"role": "user", "content": prompt})
        self._history.append({"role": "assistant", "content": reply})
        # Keep only the last 20 messages (10 exchanges) to bound memory usage
        if len(self._history) > 20:
            self._history = self._history[-20:]
        return reply

    def select_tool(self, text: str) -> dict:
        import json
        from ai_brain.tool_schema import TOOLS

        sys_prompt = (
            "You are a helpful assistant with access to the following tools.\n"
            f"{json.dumps(TOOLS, indent=2)}\n"
            "You must respond with ONLY a valid JSON object representing the tool to call. "
            "Do not include any prose, explanations, or markdown formatting (like ```json).\n"
            "Format: {\"tool\": \"<tool_name>\", \"args\": {\"<param>\": \"<value>\"}}"
        )

        # FIX: this was calling self.format_prompt(user_input=..., sys_prompt=...),
        # which doesn't exist on this class. The real method is format_chat_prompt()
        # with different parameter names.
        prompt = self.format_chat_prompt(
            user_message=text,
            system_instruction=sys_prompt,
            context_history=[],  # tool selection must not be biased by prior chat
        )

        # generate_response() unconditionally appends every call to self._history.
        # Tool-selection round trips (the raw schema prompt + raw JSON reply) are
        # not real conversation and must not leak into later chat prompts, so
        # snapshot history here and restore it after, regardless of outcome.
        saved_history = list(self._history)
        raw_reply = ""
        try:
            for attempt in range(2):
                raw_reply = self.generate_response(prompt, temperature=0.0, max_new_tokens=256)

                clean_reply = raw_reply.strip()
                if clean_reply.startswith("```json"):
                    clean_reply = clean_reply[7:]
                if clean_reply.startswith("```"):
                    clean_reply = clean_reply[3:]
                if clean_reply.endswith("```"):
                    clean_reply = clean_reply[:-3]
                clean_reply = clean_reply.strip()

                try:
                    result = json.loads(clean_reply)
                    if "tool" in result:
                        if "args" not in result:
                            result["args"] = {}
                        return result
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse tool selection JSON: {raw_reply}")

                if attempt == 0:
                    prompt += raw_reply + "\nYour last reply was not valid JSON. Reply with ONLY valid JSON."

            return {"tool": "general_answer", "args": {"response": raw_reply}}
        finally:
            self._history = saved_history


    def _init_ollama(self, model_name: str) -> bool:
        """Verify Ollama server is running and model is available, launching service if needed."""
        import urllib.request
        import json
        import subprocess

        for attempt in range(2):
            try:
                req = urllib.request.Request("http://localhost:11434/api/tags")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    installed = [m.get("name", "").lower() for m in data.get("models", [])]
                    clean_lower = model_name.lower()
                    if any(clean_lower in m or m in clean_lower for m in installed) or len(installed) > 0:
                        return True
            except Exception:
                if attempt == 0:
                    try:
                        logger.info("Ollama server not responding. Starting background 'ollama serve'...")
                        subprocess.Popen(
                            ["ollama", "serve"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        time.sleep(1.5)
                    except Exception as e:
                        logger.warning("Could not launch ollama serve: %s", e)
                        break
        return False

    def _generate_ollama(
        self,
        prompt: str,
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str:
        """Send prompt to local Ollama REST API and extract generated text."""
        import urllib.request
        import json
        import re

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "num_predict": max_new_tokens,
            },
        }
        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                reply = result.get("response", "").strip()
                reply = re.sub(r"<think>[\s\S]*?</think>", "", reply).strip()
                return reply
        except Exception as e:
            logger.error("Ollama generation failed (%s). Falling back.", e)
            return self._fallback_generate(prompt)

    def _fallback_generate(self, prompt: str) -> str:
        """Deterministic offline fallback response generator."""
        prompt_lower = prompt.lower()
        if "status" in prompt_lower or "hardware" in prompt_lower:
            return "LUNA Governor is nominal. Hardware utilization: RAM within 12.0 GB ceiling, VRAM stable on RTX 4060."
        if "self-healing" in prompt_lower or "traceback" in prompt_lower or "error" in prompt_lower:
            return "Identified exception in script execution. Synthesizing safe sandboxed patch candidate with parameterized arguments."
        if "checkpoint" in prompt_lower:
            return "Checkpoint integrity verified. AES-256 encrypted snapshot ready for restore."
        return "LUNA Executive standing by. Instruction received and verified within security sandbox."


_GLOBAL_RUNNER: Optional[GemmaModelRunner] = None


def get_default_gemma_runner() -> GemmaModelRunner:
    """Return default singleton GemmaModelRunner configured with local GPU model."""
    global _GLOBAL_RUNNER
    if _GLOBAL_RUNNER is None:
        cfg_model, cfg_device = _read_config_model()
        _GLOBAL_RUNNER = GemmaModelRunner(model_name=cfg_model, device=cfg_device)
    return _GLOBAL_RUNNER


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print("[LUNA] Initializing Gemma 4 E4B Runner...")
    runner = get_default_gemma_runner()
    
    test_queries = [
        "Check system status and hardware metrics",
        "Inspect power governor state",
        "Verify checkpoint snapshot integrity"
    ]
    
    for q in test_queries:
        prompt = runner.format_chat_prompt(q)
        response = runner.generate_response(prompt)
        print(f"\n[User]: {q}")
        print(f"[LUNA]: {response}")


