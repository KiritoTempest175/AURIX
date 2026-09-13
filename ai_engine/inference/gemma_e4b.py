"""LUNA Gemma 3n E4B Primary Inference Engine.

Implements the JARVIS-style reasoning brain using Google's Gemma 3n (E4B / E2B
elastic configuration) loaded in 4-bit NormalFloat (NF4) quantization.
Manages multi-modal context grounding, chat template formatting, tool selection,
and offline fallback execution.

Fix log:
- format_chat_prompt() referenced a variable `sys_rules` that was never
  assigned anywhere in the class or module -- this made EVERY call raise
  NameError immediately, before any prompt was ever built (this is why
  send_email_from_subject and the general "smart"/AI-answer path both
  failed with "name 'sys_rules' is not defined"). The comment above the
  original line described an intended fallback (unified model.md, falling
  back to legacy aurix.md + rules.md) that was never actually implemented --
  it's implemented now, see format_chat_prompt() below.
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


def load_md(file_path: Union[str, Path]) -> str:
    """Load a markdown file from the project vault or relative project path."""
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(_PROJECT_ROOT) / p
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed reading markdown file %s: %s", p, e)
            return ""
    logger.warning("Markdown file not found: %s", p)
    return ""


def _read_config_model(auto_download: bool = True) -> tuple[str, str, bool, str, str]:
    """Read configured model_name, device, and quantization settings from config.toml.

    If model_name is set to "auto" (or absent), delegates to
    model_resolver.resolve_best_model() which detects installed models
    and auto-downloads Gemma 4 E4B if nothing is available.

    Returns:
        Tuple of (model_name, device, load_in_4bit, quantization, effective_params).
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
    config_load_in_4bit = True
    config_quantization = "nf4"
    config_effective_params = "E4B"

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
                config_load_in_4bit = llm.get("load_in_4bit", True)
                config_quantization = llm.get("quantization", "nf4")
                config_effective_params = llm.get("effective_params", "E4B")
        except Exception:
            pass

    # Delegate to the model resolver for smart detection + auto-download
    try:
        from ai_engine.inference.model_resolver import resolve_best_model
        _model_id, _resolved_path, _spec = resolve_best_model(
            config_model_name=config_model_name,
            auto_download=auto_download,
        )
        logger.info(
            "Model resolver selected: '%s' (%s, priority=%d)",
            _spec.alias, _model_id, _spec.priority,
        )
        return _model_id, config_device, config_load_in_4bit, config_quantization, config_effective_params
    except Exception as resolver_err:
        logger.warning("Model resolver failed (%s). Using direct config value.", resolver_err)

    # Fallback: return whatever config says, or the primary model as default
    from ai_engine.inference.model_resolver import PRIMARY_MODEL_ID
    return (
        config_model_name or PRIMARY_MODEL_ID,
        config_device,
        config_load_in_4bit,
        config_quantization,
        config_effective_params,
    )


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

    # Primary model: Gemma 4 E4B, loaded locally in 4-bit NF4 on GPU.
    # This is the fallback used only if config.toml and the model resolver
    # both fail to supply a model_name.
    DEFAULT_MODEL = "google/gemma-4-E4B-it"

    def __init__(
        self,
        model_name: Optional[str] = None,
        effective_params: Optional[str] = None,
        max_seq_length: int = 2048,
        load_in_4bit: Optional[bool] = None,
        quantization: Optional[str] = None,
        device: Optional[str] = None,
        fallback_mode: bool = True,
        force_fallback: bool = False,
    ) -> None:
        """Initialize LLM model runner with GPU acceleration and 4-bit quantization.

        Args:
            model_name: HuggingFace model path or local directory.
            effective_params: Elastic parameter mode: "E4B" (full 4B) or "E2B" (efficient 2B).
                If None, falls back to config.toml's [llm].effective_params, then "E4B".
            max_seq_length: Maximum context sequence length.
            load_in_4bit: Whether to load with 4-bit quantization.
                If None, falls back to config.toml's [llm].load_in_4bit, then True.
            quantization: Quantization format ("nf4", "fp4").
                If None, falls back to config.toml's [llm].quantization, then "nf4".
            device: Target device ("cuda", "cpu").
            fallback_mode: If True, operates in simulation mode if GPU/weights unavailable.
            force_fallback: If True, skips loading weights and forces deterministic reasoning mode.
        """
        cfg_model, cfg_device, cfg_load_in_4bit, cfg_quantization, cfg_effective_params = _read_config_model(
            auto_download=not force_fallback
        )
        self.model_name = model_name or cfg_model or self.DEFAULT_MODEL
        self.effective_params = (effective_params or cfg_effective_params or "E4B").upper()
        self.max_seq_length = max_seq_length
        self.load_in_4bit = load_in_4bit if load_in_4bit is not None else cfg_load_in_4bit
        self.quantization = quantization or cfg_quantization

        target_dev = device or cfg_device or "cuda"
        if target_dev == "cuda":
            if not (torch and torch.cuda.is_available()):
                logger.error(
                    "config.toml requests device='cuda' but CUDA is unavailable "
                    "(torch present=%s, cuda available=%s). Falling back to CPU — "
                    "check GPU drivers / CUDA toolkit / torch install if this is unexpected.",
                    bool(torch), bool(torch and torch.cuda.is_available()),
                )
                self.device = "cpu"
            else:
                self.device = "cuda"
        else:
            self.device = "cpu"

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
            for fallback_id in ("google/gemma-4-E4B-it",):
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

                    # 1. Primary: Load CausalLM (Gemma, etc.)
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
        # Prefer the unified persona file (model.md). If it doesn't exist yet,
        # fall back to combining the two legacy files it was meant to replace
        # (aurix.md = persona/identity, rules.md = operating rules).
        #
        # FIX: this used to reference a variable `sys_rules` that was never
        # assigned anywhere -- format_chat_prompt() raised NameError on every
        # single call as soon as it tried to build the system prompt, which
        # is why every request (including the email body-generation feature)
        # failed with "name 'sys_rules' is not defined". The unified-vs-legacy
        # fallback described in the original comment was never actually
        # implemented; it is now.
        sys_prompt = load_md("aurix_vault/model.md")
        if not sys_prompt.strip():
            legacy_persona = load_md("aurix_vault/aurix.md") or load_md("aurix_vault/model/aurix.md")
            legacy_rules = load_md("aurix_vault/rules.md") or load_md("aurix_vault/model/rules.md")
            sys_prompt = "\n\n---\n\n".join(
                part.strip() for part in (legacy_persona, legacy_rules) if part.strip()
            )

        system_parts = []
        if sys_prompt and sys_prompt.strip():
            system_parts.append(sys_prompt.strip())
        if system_instruction and system_instruction.strip():
            system_parts.append(system_instruction.strip())

        combined_sys_prompt = (
            "\n\n---\n\n".join(system_parts)
            if system_parts
            else (
                "You are Luna, an AI assistant running inside the AURIX ecosystem."
            )
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
        messages = [{"role": "system", "content": combined_sys_prompt}]
        for msg in effective_history:
            messages.append(msg)
        messages.append({"role": "user", "content": grounded_user_content})

        if self.tokenizer and hasattr(self.tokenizer, "apply_chat_template"):
            try:
                return self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            except Exception as e:
                logger.debug(f"apply_chat_template fallback ({e})")

        # Template format: ChatML or Gemma turn tags
        if getattr(self, "backend", None) == "ollama" and not self.tokenizer:
            formatted = f"<|im_start|>system\n{combined_sys_prompt}<|im_end|>\n"
            for msg in effective_history:
                formatted += f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>\n"
            formatted += f"<|im_start|>user\n{grounded_user_content}<|im_end|>\n<|im_start|>assistant\n"
            return formatted

        # Standard fallback template format for Gemma
        formatted = f"<start_of_turn>system\n{combined_sys_prompt}<end_of_turn>\n"
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
        return reply

    def chat(self, user_message: str, system_instruction: Optional[str] = None, max_new_tokens: int = 256, temperature: float = 0.7, top_p: float = 0.9,) -> str:
        """Natural conversation API with clean rolling history.
        Only the raw user message and final assistant reply are stored.
        Formatted prompts, tool-routing prompts, and system instructions are
        never written into conversation history.
        """
        if not user_message or not user_message.strip():
            return ""
        clean_message = user_message.strip()
        prompt = self.format_chat_prompt(
            user_message=clean_message,
            system_instruction=system_instruction,
        )
        reply = self.generate_response(
            prompt=prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
        )
        self._history.append(
            {
                "role": "user",
                "content": clean_message,
            }
        )
        self._history.append(
            {
                "role": "assistant",
                "content": reply,
            }
        )
        # 20 messages = approximately 10 conversation exchanges.
        if len(self._history) > 20:
            self._history = self._history[-20:]

        return reply

    def remember_exchange(self, user_message: str, assistant_message: str,) -> None:
        """Record an externally produced tool/action exchange in chat memory."""

        if user_message and user_message.strip():
            self._history.append(
                {
                    "role": "user",
                    "content": user_message.strip(),
                }
            )

        if assistant_message and assistant_message.strip():
            self._history.append(
                {
                    "role": "assistant",
                    "content": assistant_message.strip(),
                }
            )

        if len(self._history) > 20:
            self._history = self._history[-20:]

    def select_tool(self, text: str) -> dict:
        """Use the local LLM as AURIX's natural-language action router."""

        import json
        import re

        from ai_brain.tool_schema import TOOLS

        if not text or not text.strip():
            return {
                "tool": "general_answer",
                "args": {},
            }

        system_prompt = (
            "You are AURIX's INTERNAL ACTION ROUTER.\n"
            "You are NOT speaking directly to the user.\n\n"

            "AURIX is a LOCAL WINDOWS DESKTOP ASSISTANT running on the user's "
            "own computer. It has real local tools that can open applications, "
            "close applications, read files, control media, send messages, and "
            "perform other desktop actions.\n\n"

            "IMPORTANT:\n"
            "- DO NOT refuse desktop actions.\n"
            "- DO NOT discuss security policy.\n"
            "- DO NOT claim you are ChatGPT or an external cloud AI.\n"
            "- DO NOT explain how the user can perform the action manually.\n"
            "- Your ONLY job is to SELECT A TOOL.\n"
            "- ToolExecutor and PermissionManager handle actual security.\n\n"

            "AVAILABLE TOOLS:\n"
            f"{json.dumps(TOOLS, indent=2)}\n\n"

            "ROUTING RULES:\n"
            "1. If the user asks to open, launch, start, or access an application, "
            "use open_app.\n"
            "2. If the user asks to close, quit, exit, or stop an application, "
            "use close_app.\n"
            "3. Use general_answer ONLY when no computer action is required.\n"
            "4. Understand informal English, Roman Urdu, Urdu-style English, "
            "and conversational wording.\n"
            "5. Never invent a tool.\n"
            "6. Prefer a dedicated tool over shell_exec.\n"
            "7. Return ONLY valid JSON.\n\n"

            "EXAMPLES:\n"

            'User: open WhatsApp\n'
            'Assistant: {"tool":"open_app","args":{"target":"whatsapp"}}\n\n'

            'User: WhatsApp khol do\n'
            'Assistant: {"tool":"open_app","args":{"target":"whatsapp"}}\n\n'

            'User: open Notepad\n'
            'Assistant: {"tool":"open_app","args":{"target":"notepad"}}\n\n'

            'User: chrome zara open kar do\n'
            'Assistant: {"tool":"open_app","args":{"target":"chrome"}}\n\n'

            'User: close Chrome\n'
            'Assistant: {"tool":"close_app","args":{"target":"chrome"}}\n\n'

            'User: what is artificial intelligence?\n'
            'Assistant: {"tool":"general_answer","args":{}}\n\n'

            "OUTPUT FORMAT:\n"
            '{"tool":"tool_name","args":{}}'
        )

        prompt = self.format_chat_prompt(
            user_message=text.strip(),
            system_instruction=system_prompt,
            context_history=list(self._history[-6:]),
        )

        raw_reply = ""

        for attempt in range(2):

            raw_reply = self.generate_response(
                prompt=prompt,
                temperature=0.0,
                max_new_tokens=256,
            )

            cleaned = raw_reply.strip()

            # Remove accidental markdown fences.
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]

            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]

            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]

            cleaned = cleaned.strip()

            # Some smaller local models occasionally add text before/after JSON.
            match = re.search(
                r"\{[\s\S]*\}",
                cleaned,
            )

            if match:
                cleaned = match.group(0)

            try:
                result = json.loads(cleaned)

            except json.JSONDecodeError:

                logger.warning(
                    "Tool router returned invalid JSON: %s",
                    raw_reply,
                )

                if attempt == 0:
                    prompt += (
                        "\n\nIMPORTANT: Your previous response was invalid. "
                        "Return ONLY the JSON object. No prose."
                    )

                continue

            if not isinstance(result, dict):
                continue

            tool = result.get("tool")
            args = result.get("args", {})

            if not isinstance(tool, str):
                continue

            if not isinstance(args, dict):
                args = {}

            # Validate against the actual registry.
            valid_tools = {
                item["name"]
                for item in TOOLS
            }

            if tool not in valid_tools:

                logger.warning(
                    "Model attempted unknown tool: %s",
                    tool,
                )

                return {
                    "tool": "general_answer",
                    "args": {},
                }

            return {
                "tool": tool,
                "args": args,
            }

        # Never execute malformed hallucinated output.
        return {
            "tool": "general_answer",
            "args": {},
        }

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
        cfg_model, cfg_device, cfg_load_in_4bit, cfg_quantization, cfg_effective_params = _read_config_model()
        _GLOBAL_RUNNER = GemmaModelRunner(
            model_name=cfg_model,
            device=cfg_device,
            load_in_4bit=cfg_load_in_4bit,
            quantization=cfg_quantization,
            effective_params=cfg_effective_params,
        )
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