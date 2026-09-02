# ─────────────────────────────────────────────────────────────────────────────
# ai_engine/training/dynamic_loader.py
# ─────────────────────────────────────────────────────────────────────────────
# Streaming telemetry dataset — yields training samples one at a time from
# local JSONL or SQLite storage without loading the full dataset into RAM.
#
# On a 16 GB RAM system with a 12 GB ceiling, we cannot afford to load a
# multi-GB dataset into memory alongside the model and optimiser states.
# This IterableDataset streams samples lazily, keeping RAM usage bounded
# to a single sample at a time plus Python's read buffer (~64 KB).
#
# Blueprint invariant: All data is local.  Zero network fetches.
# ─────────────────────────────────────────────────────────────────────────────

import json
import os
from typing import List, Optional, Union
from torch.utils.data import IterableDataset


# ─── Prompt Template ─────────────────────────────────────────────────────────
# Standard instruction-response template for supervised fine-tuning.
# The model learns to generate the <response> given the <instruction> + <input>.
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_TEMPLATE = """### Instruction:
{instruction}

### Input:
{input}

### Response:
{output}"""


class DynamicTelemetryDataset(IterableDataset):
    """Streaming dataset that lazily yields formatted training samples from
    a local JSONL file without loading the entire file into memory.

    Each line of the JSONL file is expected to be a JSON object with at least:
      - "instruction": The task description or user request.
      - "input":       Context or additional information (can be empty string).
      - "output":      The expected model response.

    Optional fields:
      - "ui_context":  Serialised UIA tree data from the observer.
      - "terminal_output": Captured stdout/stderr from the terminal hook.

    Usage:
        dataset = DynamicTelemetryDataset(data_path="./telemetry.jsonl")
        for sample in dataset:
            print(sample["text"])  # Formatted prompt string

    Args:
        data_path:  Path to the JSONL file containing telemetry records.
                    Each line must be a valid JSON object.
        max_samples: Optional cap on the number of samples to yield per
                     epoch.  `None` means yield all samples.
    """

    def __init__(
        self,
        data_path: Union[str, List[str]] = "./data_pipeline/storage/telemetry.jsonl",
        max_samples: Optional[int] = None,
    ):
        super().__init__()
        self.data_paths = [data_path] if isinstance(data_path, str) else list(data_path)
        self.max_samples = max_samples

        # Validate that at least one data file exists at init time
        any_found = any(os.path.exists(p) for p in self.data_paths)
        if not any_found:
            print(
                f"⚠️  [DynamicTelemetryDataset] Data file(s) not found: "
                f"{self.data_paths} — dataset will yield 0 samples."
            )

    def __iter__(self):
        """Lazily stream samples from the JSONL file(s), one line at a time.

        Yields:
            dict: {"text": str, "source": str}
        """
        count = 0
        for path in self.data_paths:
            if not os.path.exists(path):
                continue

            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue  # Skip blank lines

                    try:
                        raw_sample = json.loads(line)
                    except json.JSONDecodeError:
                        print(
                            f"⚠️  [DynamicTelemetryDataset] Skipping malformed "
                            f"JSON line: {line[:80]}..."
                        )
                        continue

                    # Format the raw sample into a prompt string.
                    formatted = self.parse_sample(raw_sample)
                    if formatted is not None:
                        source = raw_sample.get("source", "synthetic_general" if "synthetic" in path else "live_interaction")
                        yield {"text": formatted, "source": source}
                        count += 1

                        if self.max_samples is not None and count >= self.max_samples:
                            return

    @staticmethod
    def parse_sample(raw: dict) -> str:
        """Format a raw telemetry record into the training prompt template.

        Merges optional UI context and terminal output into the input field
        so the model learns to condition its responses on observed system state.

        Args:
            raw:  A dictionary with keys "instruction", "input", "output".
                  Optional: "ui_context", "terminal_output".

        Returns:
            str:  Formatted prompt string, or None if required fields are missing.
        """
        instruction = raw.get("instruction", "")
        user_input = raw.get("input", "")
        output = raw.get("output", "")

        if not instruction or not output:
            # Both instruction and output are required for SFT.
            return None

        # ── Enrich the input with observer context (if available) ─────────
        # This grounds the model's learning in real UI state + terminal output.
        context_parts = []
        if user_input:
            context_parts.append(user_input)

        ui_context = raw.get("ui_context", "")
        if ui_context:
            context_parts.append(f"[UI State] {ui_context}")

        terminal_output = raw.get("terminal_output", "")
        if terminal_output:
            context_parts.append(f"[Terminal] {terminal_output}")

        enriched_input = "\n".join(context_parts) if context_parts else ""

        return PROMPT_TEMPLATE.format(
            instruction=instruction,
            input=enriched_input,
            output=output,
        )
