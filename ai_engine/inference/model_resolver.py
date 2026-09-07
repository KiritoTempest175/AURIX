"""AURIX Multi-Model Resolver — Automatic model detection, priority selection, and download.

Detects which supported LLM models are available locally (HuggingFace cache or
project models directory), selects the highest-priority model, and auto-downloads
the primary model (Gemma 4 E4B) if no supported models are found.

Supported models (priority order):
    1. google/gemma-4-E4B-it    — Primary   (used by default)
    2. Qwen/Qwen2.5-Coder-3B-Instruct — Secondary (friend's model)
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("aurix.ai_engine.model_resolver")


# ═══════════════════════════════════════════════════════════════════════════════
#  Supported Model Registry
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ModelSpec:
    """Specification for a supported model."""
    model_id: str           # HuggingFace repo ID (e.g. "google/gemma-4-E4B-it")
    alias: str              # Human-readable display name
    effective_params: str   # Parameter tier label (e.g. "E4B", "3B")
    priority: int           # Lower = higher priority (1 = primary)
    download_patterns: List[str] = field(default_factory=lambda: [
        "*.json", "*.jinja", "*.md", "*.safetensors",
    ])


# Ordered by priority (index 0 = highest priority)
SUPPORTED_MODELS: List[ModelSpec] = [
    ModelSpec(
        model_id="google/gemma-4-E4B-it",
        alias="Gemma 4 E4B Instruct (Primary)",
        effective_params="E4B",
        priority=1,
    ),
    ModelSpec(
        model_id="Qwen/Qwen2.5-Coder-3B-Instruct",
        alias="Qwen 2.5 Coder 3B Instruct (Secondary)",
        effective_params="3B",
        priority=2,
    ),
]

# Quick lookup by model_id
_MODEL_REGISTRY: Dict[str, ModelSpec] = {m.model_id: m for m in SUPPORTED_MODELS}

PRIMARY_MODEL_ID = SUPPORTED_MODELS[0].model_id   # "google/gemma-4-E4B-it"
SECONDARY_MODEL_ID = SUPPORTED_MODELS[1].model_id  # "Qwen/Qwen2.5-Coder-3B-Instruct"


# ═══════════════════════════════════════════════════════════════════════════════
#  Detection Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _hf_cache_dir() -> Path:
    """Return the HuggingFace Hub cache directory."""
    # Respect HF_HOME / HUGGINGFACE_HUB_CACHE env vars if set
    hf_cache = os.environ.get("HUGGINGFACE_HUB_CACHE")
    if hf_cache:
        return Path(hf_cache)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _check_hf_cache(model_id: str) -> Optional[str]:
    """Check if a model exists in the HuggingFace Hub local cache.

    Returns the path to the latest snapshot directory if found, else None.
    """
    clean_name = model_id.replace("/", "--")
    cache_dir = _hf_cache_dir() / f"models--{clean_name}"
    if not cache_dir.exists():
        return None

    snapshots_dir = cache_dir / "snapshots"
    if not snapshots_dir.exists():
        return None

    snapshots = [p for p in snapshots_dir.iterdir() if p.is_dir()]
    if not snapshots:
        return None

    # Pick the most recently modified snapshot
    latest = max(snapshots, key=lambda p: p.stat().st_mtime)

    # Verify it contains actual model weight files (not just metadata)
    has_weights = (
        any(latest.glob("*.safetensors"))
        or any(latest.glob("*.bin"))
        or any(latest.glob("*.gguf"))
    )
    if has_weights:
        return str(latest)

    return None


def _check_project_models_dir(model_id: str) -> Optional[str]:
    """Check if a model exists in the project's local models/ directory."""
    try:
        project_root = Path(__file__).resolve().parent.parent.parent
        # Try both the full repo id path and just the model name
        candidates = [
            project_root / "models" / model_id,
            project_root / "models" / model_id.split("/")[-1],
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                has_weights = (
                    any(candidate.glob("*.safetensors"))
                    or any(candidate.glob("*.bin"))
                    or any(candidate.glob("*.gguf"))
                )
                if has_weights:
                    return str(candidate)
    except Exception:
        pass
    return None


def _check_direct_path(path: str) -> Optional[str]:
    """Check if a direct filesystem path contains model weights."""
    if os.path.isdir(path):
        p = Path(path)
        has_weights = (
            any(p.glob("*.safetensors"))
            or any(p.glob("*.bin"))
            or any(p.glob("*.gguf"))
        )
        if has_weights:
            return str(p.resolve())
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Core Resolution API
# ═══════════════════════════════════════════════════════════════════════════════

def detect_model(model_id: str) -> Optional[str]:
    """Detect if a specific model is available locally.

    Searches:
        1. Direct filesystem path (if model_id looks like a path)
        2. HuggingFace Hub cache
        3. Project models/ directory

    Returns:
        Resolved local path to the model weights, or None if not found.
    """
    # 1. Direct path
    if os.sep in model_id or "/" in model_id and os.path.exists(model_id):
        result = _check_direct_path(model_id)
        if result:
            return result

    # 2. HuggingFace cache
    result = _check_hf_cache(model_id)
    if result:
        return result

    # 3. Project models directory
    result = _check_project_models_dir(model_id)
    if result:
        return result

    return None


def detect_available_models() -> Dict[str, str]:
    """Scan for all supported models that are locally available.

    Returns:
        Dict mapping model_id → local_path for each model found.
    """
    available = {}
    for spec in SUPPORTED_MODELS:
        path = detect_model(spec.model_id)
        if path:
            available[spec.model_id] = path
            logger.info(
                "Detected locally available model: '%s' at '%s' (priority=%d)",
                spec.alias, path, spec.priority,
            )
    return available


def download_primary_model(progress_callback=None) -> str:
    """Download the primary model (Gemma 4 E4B) via huggingface_hub.

    Args:
        progress_callback: Optional callable(message: str) for progress updates.

    Returns:
        Local cache path where the model was downloaded.

    Raises:
        RuntimeError: If the download fails.
    """
    primary = SUPPORTED_MODELS[0]

    def _log(msg: str):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    _log(
        f"No supported models found locally. "
        f"Downloading primary model: '{primary.alias}' ({primary.model_id})..."
    )

    try:
        from huggingface_hub import snapshot_download

        path = snapshot_download(
            repo_id=primary.model_id,
            allow_patterns=primary.download_patterns,
        )
        _log(f"Successfully downloaded '{primary.model_id}' to: {path}")
        return path

    except ImportError:
        error_msg = (
            "huggingface_hub is not installed. Cannot auto-download model.\n"
            "Install it with: pip install huggingface-hub\n"
            "Or manually download the model with: python scripts/download_gemma.py"
        )
        _log(f"[ERROR] {error_msg}")
        raise RuntimeError(error_msg)

    except Exception as e:
        error_msg = (
            f"Failed to download '{primary.model_id}': {e}\n"
            "Check your internet connection and HuggingFace authentication.\n"
            "You can also manually download with: python scripts/download_gemma.py"
        )
        _log(f"[ERROR] {error_msg}")
        raise RuntimeError(error_msg)


def resolve_best_model(
    config_model_name: Optional[str] = None,
    auto_download: bool = True,
    progress_callback=None,
) -> Tuple[str, str, ModelSpec]:
    """Resolve the best available model to use.

    Priority logic:
        1. If config specifies a concrete model (not "auto"), check if it's available
           locally. If yes, use it. If no, fall through to auto-detection.
        2. Scan for supported models in priority order (Gemma 4 E4B first, then Qwen 2.5 3B).
        3. If no supported model is found and auto_download is True, download Gemma 4 E4B.
        4. If download also fails, return the primary model ID for remote/fallback loading.

    Args:
        config_model_name: Model name from config.toml. Use "auto" or None for auto-detect.
        auto_download: Whether to auto-download the primary model if none are found.
        progress_callback: Optional callable(message: str) for status updates.

    Returns:
        Tuple of (model_id_or_path, resolved_local_path_or_model_id, ModelSpec).
    """
    def _log(msg: str):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    # ── Step 1: If config specifies a concrete model, try to use it ────────
    if config_model_name and config_model_name.lower() != "auto":
        # Check if it's a known supported model
        spec = _MODEL_REGISTRY.get(config_model_name)

        # Check if it exists locally
        local_path = detect_model(config_model_name)
        if local_path:
            if spec:
                _log(f"Using configured model: '{spec.alias}' (found locally)")
                return config_model_name, local_path, spec
            else:
                # Custom model not in registry — create an ad-hoc spec
                custom_spec = ModelSpec(
                    model_id=config_model_name,
                    alias=config_model_name,
                    effective_params="custom",
                    priority=99,
                )
                _log(f"Using configured custom model: '{config_model_name}' (found locally)")
                return config_model_name, local_path, custom_spec
        else:
            _log(
                f"Configured model '{config_model_name}' not found locally. "
                f"Falling back to auto-detection..."
            )

    # ── Step 2: Auto-detect supported models in priority order ─────────────
    _log("Auto-detecting available models...")
    available = detect_available_models()

    if available:
        # Pick the highest-priority model (lowest priority number)
        best_id = min(available.keys(), key=lambda mid: _MODEL_REGISTRY[mid].priority)
        best_spec = _MODEL_REGISTRY[best_id]
        best_path = available[best_id]
        _log(
            f"Auto-selected model: '{best_spec.alias}' "
            f"(priority={best_spec.priority}, path='{best_path}')"
        )
        return best_id, best_path, best_spec

    # ── Step 3: No models found — attempt download ────────────────────────
    if auto_download:
        try:
            downloaded_path = download_primary_model(progress_callback=progress_callback)
            primary_spec = SUPPORTED_MODELS[0]
            return primary_spec.model_id, downloaded_path, primary_spec
        except RuntimeError:
            _log("Auto-download failed. Will attempt remote loading or fallback mode.")

    # ── Step 4: Last resort — return primary model ID for remote/fallback ──
    primary_spec = SUPPORTED_MODELS[0]
    _log(
        f"No local models found. Returning primary model ID '{primary_spec.model_id}' "
        f"for remote loading or fallback mode."
    )
    return primary_spec.model_id, primary_spec.model_id, primary_spec


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI Entry Point (for manual testing)
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 70)
    print("  AURIX Model Resolver — Detection & Selection")
    print("=" * 70)

    # Show all supported models
    print("\n[Supported Models]")
    for spec in SUPPORTED_MODELS:
        print(f"  Priority {spec.priority}: {spec.alias} ({spec.model_id})")

    # Detect what's available
    print("\n[Scanning for locally available models...]")
    available = detect_available_models()

    if available:
        print(f"\n[Found {len(available)} model(s)]")
        for model_id, path in available.items():
            spec = _MODEL_REGISTRY[model_id]
            print(f"  ✓ {spec.alias}")
            print(f"    Path: {path}")
    else:
        print("\n[No supported models found locally]")

    # Resolve the best model (without auto-download in CLI test mode)
    print("\n[Resolving best model (auto_download=False)...]")
    model_id, resolved_path, spec = resolve_best_model(auto_download=False)
    print(f"\n[Selected Model]")
    print(f"  Model:    {spec.alias}")
    print(f"  ID:       {model_id}")
    print(f"  Path:     {resolved_path}")
    print(f"  Priority: {spec.priority}")
    print(f"  Params:   {spec.effective_params}")
    print("=" * 70)
