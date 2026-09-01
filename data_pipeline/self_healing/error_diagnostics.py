"""LUNA Autonomous Self-Healing Diagnostic Engine.

Parses raw stderr streams intercepted by the PTY daemon, isolates exception patterns,
synthesizes diagnostic prompts for Gemma 3n / Student-5B, supports dry-run preview mode,
and enforces a strict N=3 retry mitigation ceiling.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("luna.data_pipeline.self_healing")


@dataclass
class ErrorDiagnostic:
    error_type: str
    error_message: str
    failed_line: Optional[str]
    raw_traceback: str


class TracebackAnalyzer:
    """Parses raw stderr streams intercepted by the Rust PTY daemon into structured diagnostics."""

    @staticmethod
    def parse_stderr(stderr_text: str) -> ErrorDiagnostic:
        lines = stderr_text.strip().split("\n")
        error_type = "UnknownError"
        error_message = "An unhandled execution error occurred."
        failed_line = None

        exception_pattern = r"^([A-Za-z_][A-Za-z0-9_]*Error|Exception):\s*(.*)$"

        for line in reversed(lines):
            match = re.match(exception_pattern, line.strip())
            if match:
                error_type = match.group(1)
                error_message = match.group(2)
                break

        for line in lines:
            if "File " in line and "line " in line:
                failed_line = line.strip()

        return ErrorDiagnostic(
            error_type=error_type,
            error_message=error_message,
            failed_line=failed_line,
            raw_traceback=stderr_text,
        )


class SelfHealingEngine:
    """Manages automated diagnostic prompts, patch generation, dry-run previews, and retry ceilings."""

    MAX_RETRIES = 3

    def __init__(self, llm_pipeline: Optional[Any] = None) -> None:
        self.llm_pipeline = llm_pipeline
        self.retry_tracker: Dict[str, int] = {}

    def handle_execution_failure(
        self,
        task_id: str,
        failed_script: str,
        stderr_stream: str,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Handle terminal execution failure and produce candidate patch."""
        current_attempts = self.retry_tracker.get(task_id, 0)

        if current_attempts >= self.MAX_RETRIES:
            logger.warning(f"Task '{task_id}' reached max retry limit ({self.MAX_RETRIES}).")
            return {
                "status": "HALTED_MAX_RETRIES_EXCEEDED",
                "message": f"Self-healing ceiling (N={self.MAX_RETRIES}) reached. Control yielded to user.",
                "proposed_patch": None,
                "show_alert_modal": True,
            }

        diagnostic = TracebackAnalyzer.parse_stderr(stderr_stream)
        prompt = self._construct_diagnostic_prompt(failed_script, diagnostic)
        proposed_patch = self._query_model_for_patch(prompt)

        self.retry_tracker[task_id] = current_attempts + 1

        return {
            "status": "PROPOSED_PATCH_READY",
            "task_id": task_id,
            "attempt": self.retry_tracker[task_id],
            "max_attempts": self.MAX_RETRIES,
            "error_summary": f"{diagnostic.error_type}: {diagnostic.error_message}",
            "original_script": failed_script,
            "proposed_patch": proposed_patch,
            "dry_run": dry_run,
            "countdown_seconds": 5,
        }

    def _construct_diagnostic_prompt(self, script: str, diag: ErrorDiagnostic) -> str:
        return f"""[LUNA SELF-HEALING DIAGNOSTIC]
An automated task failed execution in the terminal.

FAILED SCRIPT:
{script}

DIAGNOSTIC REPORT:
- Error Type: {diag.error_type}
- Message: {diag.error_message}
- Failed Line: {diag.failed_line or 'N/A'}

TRACEBACK LOG:
{diag.raw_traceback}

INSTRUCTION:
Fix the error above. Output ONLY the corrected script code. Do not include markdown commentary."""

    def _query_model_for_patch(self, prompt: str) -> str:
        if self.llm_pipeline and hasattr(self.llm_pipeline, "generate_response"):
            return self.llm_pipeline.generate_response(prompt)
        return "# Self-healing patch\nimport os\nos.makedirs('./data', exist_ok=True)\n"
