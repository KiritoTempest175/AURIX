# ─────────────────────────────────────────────────────────────────────────────
# ai_engine/training/qlora_loop.py
# ─────────────────────────────────────────────────────────────────────────────
# Unsloth 4-bit QLoRA fine-tuning loop for the AURIX 5B student model.
#
# This script is the main entry point for continuous background training.
# It loads a 5B parameter model in 4-bit quantisation via Unsloth, applies
# LoRA adapters, and trains with an SFTTrainer that respects the hardware
# constraints of the target machine:
#
#   GPU:  NVIDIA RTX 4060 — 8 GB total VRAM, 6 GB ceiling
#   RAM:  16 GB total, 12 GB ceiling
#   Disk: Mechanical HDD — checkpoint saves are slow
#
# Key optimisations:
#   - 4-bit NF4 quantisation via Unsloth (halves VRAM vs. FP16)
#   - Micro-batch size 1 with gradient accumulation steps 8
#     (effective batch size = 8 without 8× the VRAM)
#   - Unsloth gradient checkpointing (trades ~15% speed for ~40% VRAM)
#   - 8-bit AdamW optimiser (halves optimiser state memory)
#   - GovernorCallback evicts VRAM on hardware spikes via Rust FFI
#
# Blueprint invariant: Zero network sockets.  All data is streamed from
# local JSONL / SQLite via DynamicTelemetryDataset.
# ─────────────────────────────────────────────────────────────────────────────

import os
import torch
try:
    from unsloth import FastLanguageModel
    HAS_UNSLOTH = True
except ImportError:
    FastLanguageModel = None
    HAS_UNSLOTH = False

try:
    from transformers import TrainingArguments, TrainerCallback
    from trl import SFTTrainer
except ImportError:
    TrainingArguments = None
    TrainerCallback = object
    SFTTrainer = None

from ai_engine.training.memory_manager import GracefulMemoryManager
from ai_engine.training.dynamic_loader import DynamicTelemetryDataset


# ─── Blueprint Constants ─────────────────────────────────────────────────────

def _load_model_config():
    cfg_path = "./config.toml"
    defaults = {"model_name": "unsloth/Qwen3-4B", "max_seq_length": 2048, "load_in_4bit": True}
    if os.path.exists(cfg_path):
        try:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib
            with open(cfg_path, "rb") as f:
                parsed = tomllib.load(f)
                if "llm" in parsed:
                    defaults.update(parsed["llm"])
        except Exception:
            pass
    return defaults

_llm_cfg = _load_model_config()

# Model configuration
MODEL_NAME = _llm_cfg.get("model_name", "unsloth/Qwen3-4B")  # Qwen 3 4B base model
MAX_SEQ_LENGTH = int(_llm_cfg.get("max_seq_length", 2048))  # Context window — 2K tokens
LOAD_IN_4BIT = bool(_llm_cfg.get("load_in_4bit", True))     # NF4 quantisation via bitsandbytes

# LoRA adapter configuration
LORA_R = 16                              # Rank — lower = less VRAM, higher = more capacity
LORA_ALPHA = 32                          # Scaling factor — alpha/r = 2.0 is standard
LORA_DROPOUT = 0.0                       # Unsloth optimised — dropout = 0 for speed
LORA_TARGET_MODULES = [                  # All linear projections in the attention + MLP
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
]

# Training hyperparameters — VRAM-constrained profile
PER_DEVICE_BATCH_SIZE = 1                # Micro-batch size of 1 — minimum VRAM footprint
GRADIENT_ACCUMULATION_STEPS = 8          # Effective batch size = 1 × 8 = 8
LEARNING_RATE = 2e-4                     # Standard for QLoRA fine-tuning
NUM_TRAIN_EPOCHS = 3                     # Full passes over the telemetry dataset
WARMUP_STEPS = 10                        # Linear warmup before LR schedule kicks in
LOGGING_STEPS = 1                        # Log every step for fine-grained monitoring
SAVE_STEPS = 50                          # HF Trainer auto-save interval
MAX_GRAD_NORM = 0.3                      # Gradient clipping — prevents loss spikes
LR_SCHEDULER_TYPE = "linear"             # Linear decay after warmup
OPTIM = "adamw_8bit"                     # 8-bit AdamW — halves optimiser state memory

# Paths
OUTPUT_DIR = "./aurix_5b_student_output"
CHECKPOINT_DIR = "./aurix_5b_student_checkpoint"
DATA_PATH = "./data_pipeline/storage/telemetry.jsonl"


# ─── GovernorCallback ─────────────────────────────────────────────────────────

class GovernorCallback(TrainerCallback):
    """Hugging Face TrainerCallback that triggers VRAM eviction on hardware spikes.

    This callback is injected into the SFTTrainer and fires at the end of
    every training step.  It delegates to `GracefulMemoryManager.check_and_evict()`
    which polls the Rust governor's atomic suspend flag.

    If the governor has flagged a resource spike (RAM > 12GB or VRAM > 6GB),
    the memory manager will:
      1. Save the current LoRA weights to disk
      2. Flush gc + CUDA cache
      3. Block until resources stabilise
    """

    def __init__(self, memory_manager: GracefulMemoryManager):
        """Initialise with a reference to the active memory manager.

        Args:
            memory_manager:  A fully initialised GracefulMemoryManager instance
                             holding references to the model and tokenizer.
        """
        super().__init__()
        self.memory_manager = memory_manager

    def on_step_end(self, args, state, control, **kwargs):
        """Called at the end of every training step by the HF Trainer.

        Polls the Rust governor and evicts VRAM if a spike is detected.
        This is the critical integration point between the HF training loop
        and the Rust hardware governance layer.
        """
        evicted = self.memory_manager.check_and_evict()
        if evicted:
            # Log the eviction event for the telemetry pipeline.
            print(
                f"   📊 [GovernorCallback] Eviction at global step "
                f"{state.global_step}"
            )

    def on_train_end(self, args, state, control, **kwargs):
        """Called once when training finishes — save a final checkpoint."""
        print("\n🏁 [GovernorCallback] Training complete — saving final checkpoint")
        self.memory_manager.model.save_pretrained(CHECKPOINT_DIR)
        self.memory_manager.tokenizer.save_pretrained(CHECKPOINT_DIR)
        diag = self.memory_manager.get_diagnostics()
        print(f"   📊 Total evictions during training: {diag['total_evictions']}")


# ─── Main Training Function ──────────────────────────────────────────────────

def run_training():
    """Load the model, configure LoRA, and launch the SFTTrainer.

    This is the top-level function called by the AURIX agent to start or
    resume background fine-tuning.  It handles:
      1. Model + tokenizer loading with 4-bit quantisation
      2. LoRA adapter injection targeting all linear modules
      3. Training data streaming via DynamicTelemetryDataset
      4. SFTTrainer launch with GovernorCallback for VRAM safety

    The entire pipeline runs in-process with zero network sockets.
    """
    print("═══════════════════════════════════════════════════════════")
    print("  AURIX QLoRA Training Loop — Initialising")
    print("═══════════════════════════════════════════════════════════\n")

    # ── Step 1: Load the base model in 4-bit quantisation ─────────────────
    # Unsloth's FastLanguageModel handles bitsandbytes NF4 quantisation
    # internally.  The 4-bit representation cuts VRAM from ~10GB to ~2.5GB
    # for a 5B model, fitting comfortably within our 6GB ceiling.
    print(f"📦 Loading model: {MODEL_NAME} (4-bit NF4)")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_NAME,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,                  # Auto-detect (float16 on Ampere+)
        load_in_4bit=LOAD_IN_4BIT,
    )
    print(f"   ✓ Model loaded — {MODEL_NAME}")

    # ── Step 2: Apply LoRA adapters ───────────────────────────────────────
    # We target ALL linear modules in the attention and MLP layers.
    # `use_gradient_checkpointing="unsloth"` trades ~15% wall-clock speed
    # for ~40% VRAM reduction by recomputing activations during backward.
    print(f"🔧 Applying LoRA adapters (r={LORA_R}, alpha={LORA_ALPHA})")
    model = FastLanguageModel.get_peft_model(
        model,
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=LORA_TARGET_MODULES,
        bias="none",                 # No bias training — saves VRAM
        use_gradient_checkpointing="unsloth",
        random_state=42,
        use_rslora=False,            # Standard LoRA scaling
        loftq_config=None,
    )
    print("   ✓ LoRA adapters applied")

    # ── Step 3: Initialise the Memory Manager ─────────────────────────────
    # The memory manager holds references to the model and tokenizer so it
    # can save checkpoints and flush VRAM when the Rust governor signals.
    memory_manager = GracefulMemoryManager(
        model=model,
        tokenizer=tokenizer,
        save_path=CHECKPOINT_DIR,
    )
    print("   ✓ GracefulMemoryManager initialised")

    # ── Step 4: Load the training dataset ─────────────────────────────────
    # DynamicTelemetryDataset streams samples from local storage without
    # loading the entire dataset into RAM.
    print(f"📂 Loading telemetry dataset from {DATA_PATH}")
    dataset = DynamicTelemetryDataset(data_path=DATA_PATH)
    print("   ✓ Dataset stream ready")

    # ── Step 5: Configure training arguments ──────────────────────────────
    # Every parameter here is tuned for the RTX 4060 / 8GB VRAM constraint.
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=PER_DEVICE_BATCH_SIZE,
        gradient_accumulation_steps=GRADIENT_ACCUMULATION_STEPS,
        num_train_epochs=NUM_TRAIN_EPOCHS,
        learning_rate=LEARNING_RATE,
        warmup_steps=WARMUP_STEPS,
        logging_steps=LOGGING_STEPS,
        save_steps=SAVE_STEPS,
        max_grad_norm=MAX_GRAD_NORM,
        lr_scheduler_type=LR_SCHEDULER_TYPE,
        optim=OPTIM,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        save_total_limit=2,          # Keep only 2 checkpoints to save disk
        report_to="none",            # No W&B / MLflow — fully offline
        seed=42,
    )

    # ── Step 6: Create the SFTTrainer with GovernorCallback ───────────────
    # The GovernorCallback fires at the end of every step, polling the Rust
    # suspend flag and evicting VRAM if a hardware spike is detected.
    governor_callback = GovernorCallback(memory_manager=memory_manager)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=training_args,
        callbacks=[governor_callback],
        max_seq_length=MAX_SEQ_LENGTH,
        packing=False,               # No example packing — simpler gradient flow
    )

    # ── Step 7: Launch training ───────────────────────────────────────────
    print("\n🚀 Starting QLoRA fine-tuning loop")
    print(f"   Batch size:    {PER_DEVICE_BATCH_SIZE}")
    print(f"   Grad accum:    {GRADIENT_ACCUMULATION_STEPS}")
    print(f"   Effective BS:  {PER_DEVICE_BATCH_SIZE * GRADIENT_ACCUMULATION_STEPS}")
    print(f"   Optimiser:     {OPTIM}")
    print(f"   Learning rate: {LEARNING_RATE}")
    print(f"   Epochs:        {NUM_TRAIN_EPOCHS}")
    print("───────────────────────────────────────────────────────────\n")

    trainer.train()

    # ── Step 8: Save final model ──────────────────────────────────────────
    print(f"\n💾 Saving final model to {CHECKPOINT_DIR}")
    model.save_pretrained(CHECKPOINT_DIR)
    tokenizer.save_pretrained(CHECKPOINT_DIR)
    print("✅ Training complete\n")


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_training()
