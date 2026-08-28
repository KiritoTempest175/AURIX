# ─────────────────────────────────────────────────────────────────────────────
# ai_engine/training/memory_manager.py
# ─────────────────────────────────────────────────────────────────────────────
# Graceful VRAM eviction manager — bridges the PyTorch training loop with
# the Rust hardware governor via the PyO3 `aurix_core.SystemState()` class.
#
# When the Rust governor detects RAM > 12 GB or VRAM > 6 GB, it sets the
# atomic suspend flag. This class polls that flag at the end of every
# training step, and if set:
#   1. Saves the LoRA adapter weights + tokenizer to disk
#   2. Flushes the Python garbage collector
#   3. Releases all cached CUDA VRAM back to the OS
#   4. Blocks in a sleep loop until resources stabilise
#
# Hardware context:
#   GPU:  NVIDIA RTX 4060 — 8 GB total VRAM, 6 GB ceiling
#   RAM:  16 GB total, 12 GB ceiling
#   Disk: Mechanical HDD — checkpoint saves take 3–8 seconds
# ─────────────────────────────────────────────────────────────────────────────

import gc
import os
import time
import torch

try:
    import aurix_core
except ImportError:
    # Graceful fallback when the compiled PyO3 extension is not installed in the active environment
    class _MockSystemState:
        def __init__(self):
            self._suspended = False

        def check_suspended(self) -> bool:
            return self._suspended

        def pause(self):
            self._suspended = True

        def resume(self):
            self._suspended = False

    class _MockAurixCore:
        SystemState = _MockSystemState

    aurix_core = _MockAurixCore()


class GracefulMemoryManager:
    """Manages VRAM eviction and state synchronisation between the Rust
    hardware governor and the PyTorch QLoRA training loop.

    The Rust governor runs on a dedicated OS thread polling sysinfo + NVML
    every 1000ms. This class reads the resulting atomic boolean flag via
    the PyO3 `SystemState` class — zero network sockets, zero IPC overhead.

    Attributes:
        VRAM_LIMIT:  Soft VRAM budget in bytes (5 GB). The Rust governor
                     enforces a hard 6 GB ceiling; we target 5 GB to leave
                     headroom for CUDA context and driver allocations.
        RAM_LIMIT:   Hard RAM ceiling in bytes (12 GB).
        SAVE_PATH:   Default disk path for emergency checkpoint saves.
    """

    VRAM_LIMIT = 5 * 1024**3          # 5 GB in bytes
    RAM_LIMIT = 12 * 1024**3          # 12 GB in bytes
    STEPS_BETWEEN_SAVES = 5           # Periodic checkpoint frequency (every N steps)
    SAVE_INTERVAL = 60                # Minimum seconds between periodic saves
    POLL_SLEEP_INTERVAL = 1.0         # Sleep duration (seconds) while waiting for recovery

    def __init__(
        self,
        model,
        tokenizer,
        save_path="./aurix_5b_student_checkpoint",
    ):
        """Initialise the memory manager with references to the active model.

        Args:
            model:      The Hugging Face / Unsloth model (with LoRA adapters).
                        Must support `.save_pretrained(path)`.
            tokenizer:  The tokenizer paired with the model.
                        Must support `.save_pretrained(path)`.
            save_path:  Filesystem path for emergency checkpoint saves.
                        WARNING: On mechanical HDDs this write blocks for
                        3–8 seconds depending on adapter size.
        """
        self.model = model
        self.tokenizer = tokenizer
        self.save_path = save_path
        self.system_state = aurix_core.SystemState()

        # Step tracking for periodic saves
        self.steps_since_last_save = 0
        self.last_save_time = 0.0
        self.total_evictions = 0

        # Ensure target checkpoint directory exists
        os.makedirs(self.save_path, exist_ok=True)

    def check_and_evict(self) -> bool:
        """Polls the Rust governor.

        If a system spike is active (RAM > 12GB or VRAM > 6GB), saves the model
        checkpoint to disk, flushes CUDA VRAM, and sleeps until resources stabilize.

        Returns:
            bool: True if an eviction occurred, False otherwise.
        """
        # 1. Call self.system_state.check_suspended() to check if RAM > 12GB or VRAM > 6GB.
        if not self.system_state.check_suspended():
            self.steps_since_last_save += 1
            self._maybe_periodic_save()
            return False

        # 2. If suspended:
        self.total_evictions += 1
        print(
            f"\n⚠️  [AURIX Governor] RESOURCE SPIKE DETECTED (RAM > 12GB or VRAM > 6GB) — "
            f"eviction #{self.total_evictions}"
        )

        # a. Save the current LoRA adapter weights and tokenizer to self.save_path.
        #    WARNING: On mechanical spinning hard drives, this I/O write will block execution
        #    for a few seconds (typically 3–8 seconds) while buffers are flushed.
        print(f"   💾 [Mechanical HDD Warning] Writing checkpoint to {self.save_path} ...")
        save_start = time.time()
        self.model.save_pretrained(self.save_path)
        self.tokenizer.save_pretrained(self.save_path)
        save_elapsed = time.time() - save_start
        print(f"   ✓ Checkpoint safely written to disk in {save_elapsed:.2f}s")

        self.steps_since_last_save = 0
        self.last_save_time = time.time()

        # b. Call gc.collect() to clear Python garbage references.
        collected = gc.collect()
        print(f"   🗑️  gc.collect() freed {collected} unreferenced objects")

        # c. Call torch.cuda.empty_cache() to immediately release allocated VRAM back to the OS.
        if torch.cuda.is_available():
            vram_before = torch.cuda.memory_allocated()
            torch.cuda.empty_cache()
            vram_after = torch.cuda.memory_allocated()
            freed_mb = (vram_before - vram_after) / (1024**2)
            print(f"   🔥 torch.cuda.empty_cache() released: {freed_mb:.2f} MB VRAM")

        # d. Enter a while-loop that sleeps (time.sleep(1)) as long as check_suspended() returns True.
        print("   ⏳ Entering sleep loop — waiting for host resources to stabilize...")
        wait_start = time.time()
        while self.system_state.check_suspended():
            time.sleep(self.POLL_SLEEP_INTERVAL)

        # e. Log or notify that resources stabilized when the loop exits.
        wait_elapsed = time.time() - wait_start
        print(
            f"   ✅ Resources stabilized after {wait_elapsed:.2f}s — resuming training loop.\n"
        )
        return True

    def _maybe_periodic_save(self):
        """Perform a periodic checkpoint save if enough steps/time elapsed."""
        if self.steps_since_last_save < self.STEPS_BETWEEN_SAVES:
            return

        now = time.time()
        if (now - self.last_save_time) < self.SAVE_INTERVAL:
            return

        print(f"   📝 Periodic checkpoint save to {self.save_path}")
        self.model.save_pretrained(self.save_path)
        self.tokenizer.save_pretrained(self.save_path)
        self.steps_since_last_save = 0
        self.last_save_time = now

    def get_diagnostics(self) -> dict:
        """Return a snapshot of memory manager state for telemetry logging."""
        diag = {
            "total_evictions": self.total_evictions,
            "steps_since_last_save": self.steps_since_last_save,
            "is_suspended": self.system_state.check_suspended(),
            "cuda_allocated_mb": 0.0,
            "cuda_cached_mb": 0.0,
        }
        if torch.cuda.is_available():
            diag["cuda_allocated_mb"] = torch.cuda.memory_allocated() / (1024**2)
            diag["cuda_cached_mb"] = torch.cuda.memory_reserved() / (1024**2)
        return diag