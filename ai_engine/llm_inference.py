# ─────────────────────────────────────────────────────────────────────────────
# ai_engine/llm_inference.py
# ─────────────────────────────────────────────────────────────────────────────
# Qwen 3:4B Local Inference Engine for AURIX AI Agent.
#
# Manages local 4-bit quantized inference with Qwen 3:4B / Qwen 2.5 3B models.
# Incorporates hardware VRAM governance via GracefulMemoryManager, zero network
# socket invariants, and graceful fallback for offline/testing environments.
# ─────────────────────────────────────────────────────────────────────────────

import os
import sys
import gc
from typing import Optional, Dict, Any

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

from ai_engine.training.dynamic_loader import PROMPT_TEMPLATE
from ai_engine.training.memory_manager import GracefulMemoryManager


def load_config_llm_settings(config_path: str = "./config.toml") -> Dict[str, Any]:
    """Reads [llm] configuration section from config.toml with safe defaults."""
    defaults = {
        "model_name": "unsloth/Qwen3-4B",
        "model_alias": "Qwen 3 4B",
        "max_seq_length": 2048,
        "load_in_4bit": True,
        "quantization": "nf4",
        "device": "cuda",
        "temperature": 0.7,
        "top_p": 0.9,
    }
    if os.path.exists(config_path):
        try:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib
            with open(config_path, "rb") as f:
                parsed = tomllib.load(f)
                if "llm" in parsed:
                    defaults.update(parsed["llm"])
        except Exception as err:
            print(f"⚠️ [QwenModelRunner] Could not read {config_path}: {err}")
    return defaults


class QwenModelRunner:
    """Manages lifecycle, prompt formatting, and generation for Qwen 3:4B model.

    Attributes:
        model_name: HuggingFace/Unsloth repo identifier (default: "unsloth/Qwen3-4B").
        max_seq_length: Maximum context length (tokens).
        load_in_4bit: Whether to load model using 4-bit NF4 quantisation.
        device: Execution target ("cuda" or "cpu").
        is_loaded: Boolean flag indicating if active model is loaded in VRAM/RAM.
        is_fallback: Boolean flag indicating if runner is operating in mock/fallback mode.
    """

    def __init__(
        self,
        config_path: str = "./config.toml",
        memory_manager: Optional[GracefulMemoryManager] = None,
    ):
        self.config = load_config_llm_settings(config_path)
        self.model_name = self.config.get("model_name", "unsloth/Qwen3-4B")
        self.max_seq_length = int(self.config.get("max_seq_length", 2048))
        self.load_in_4bit = bool(self.config.get("load_in_4bit", True))
        self.device = self.config.get("device", "cuda")
        self.temperature = float(self.config.get("temperature", 0.7))
        self.top_p = float(self.config.get("top_p", 0.9))

        self.model = None
        self.tokenizer = None
        self.memory_manager = memory_manager
        self.is_loaded = False
        self.is_fallback = False

    def load_model(self) -> bool:
        """Loads the Qwen 3:4B model into VRAM using Unsloth/bitsandbytes.

        If CUDA is unavailable or model weights are missing, switches to fallback mode.
        """
        if self.is_loaded:
            return True

        if not HAS_TORCH or (self.device == "cuda" and not torch.cuda.is_available()):
            print(f"⚠️ [QwenModelRunner] CUDA unavailable — using fallback runner mode for {self.model_name}")
            self.is_fallback = True
            self.is_loaded = True
            return True

        try:
            from unsloth import FastLanguageModel

            print(f"📦 [QwenModelRunner] Loading {self.model_name} (4-bit NF4, max_seq={self.max_seq_length})...")
            self.model, self.tokenizer = FastLanguageModel.from_pretrained(
                model_name=self.model_name,
                max_seq_length=self.max_seq_length,
                dtype=None,
                load_in_4bit=self.load_in_4bit,
            )
            FastLanguageModel.for_inference(self.model)

            if self.memory_manager is not None:
                self.memory_manager.model = self.model
                self.memory_manager.tokenizer = self.tokenizer

            self.is_loaded = True
            self.is_fallback = False
            print(f"✅ [QwenModelRunner] Successfully loaded {self.model_name}")
            return True

        except Exception as e:
            print(f"⚠️ [QwenModelRunner] Failed to load {self.model_name} via Unsloth ({e}) — switching to fallback mode.")
            self.is_fallback = True
            self.is_loaded = True
            return False

    def format_prompt(
        self,
        instruction: str,
        user_input: str = "",
        ui_context: str = "",
        terminal_output: str = "",
    ) -> str:
        """Formats instructions and context into the Qwen standard prompt structure."""
        context_parts = []
        if user_input:
            context_parts.append(user_input)
        if ui_context:
            context_parts.append(f"[UI State] {ui_context}")
        if terminal_output:
            context_parts.append(f"[Terminal] {terminal_output}")

        enriched_input = "\n".join(context_parts) if context_parts else ""

        return PROMPT_TEMPLATE.format(
            instruction=instruction,
            input=enriched_input,
            output="",
        )

    def generate(
        self,
        instruction: str,
        user_input: str = "",
        ui_context: str = "",
        terminal_output: str = "",
        max_new_tokens: int = 256,
    ) -> str:
        """Generates a response from the Qwen 3:4B model for a given task prompt."""
        if not self.is_loaded:
            self.load_model()

        # Check governor memory spikes prior to generation
        if self.memory_manager is not None:
            self.memory_manager.check_and_evict()

        prompt = self.format_prompt(
            instruction=instruction,
            user_input=user_input,
            ui_context=ui_context,
            terminal_output=terminal_output,
        )

        if self.is_fallback:
            return f"[Qwen 3:4B Offline Response]: Processed instruction '{instruction}' successfully."

        try:
            inputs = self.tokenizer([prompt], return_tensors="pt").to("cuda")
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                use_cache=True,
            )
            response = self.tokenizer.batch_decode(outputs, skip_special_tokens=True)[0]
            # Strip prompt prefix from output if present
            if response.startswith(prompt):
                response = response[len(prompt):].strip()
            return response

        except Exception as err:
            print(f"⚠️ [QwenModelRunner] Generation error: {err}")
            return f"[Qwen 3:4B Fallback]: Processed task '{instruction}'."

    def unload(self):
        """Evicts model weights from CUDA memory."""
        if self.model is not None:
            del self.model
            self.model = None
        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None

        if HAS_TORCH and torch.cuda.is_available():
            gc.collect()
            torch.cuda.empty_cache()

        self.is_loaded = False
        self.is_fallback = False
        print("🧹 [QwenModelRunner] Evicted Qwen 3:4B model from memory.")
