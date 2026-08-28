import re
from typing import Dict, Any, Optional
from dataclasses import dataclass

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
        lines = stderr_text.strip().split('\n')
        error_type = "UnknownError"
        error_message = "An unhandled execution error occurred."
        failed_line = None
        
        # Regex pattern for standard exception strings
        exception_pattern = r"^([A-Za-z_][A-Za-z0-9_]*Error|Exception):\s*(.*)$"
        
        # Scan backward from stderr bottom to locate the core exception
        for line in reversed(lines):
            match = re.match(exception_pattern, line.strip())
            if match:
                error_type = match.group(1)
                error_message = match.group(2)
                break
                
        # Extract line context from Python stack trace
        for line in lines:
            if "File " in line and "line " in line:
                failed_line = line.strip()
                
        return ErrorDiagnostic(
            error_type=error_type,
            error_message=error_message,
            failed_line=failed_line,
            raw_traceback=stderr_text
        )


class SelfHealingEngine:
    """
    Manages automated diagnostic prompts, candidate patch generation, 
    and strict retry ceiling (N=3) enforcement.
    """
    
    MAX_RETRIES = 3  # Mitigates infinite self-healing loops per system spec

    def __init__(self, llm_pipeline=None):
        self.llm_pipeline = llm_pipeline
        self.retry_tracker: Dict[str, int] = {}  # Tracks attempts per task_id

    def handle_execution_failure(
        self, 
        task_id: str, 
        failed_script: str, 
        stderr_stream: str
    ) -> Dict[str, Any]:
        """
        Main entry point invoked when a terminal execution fails.
        Emits structured patch data for the Slint 5-second countdown override modal.
        """
        current_attempts = self.retry_tracker.get(task_id, 0)
        
        # Mitigation: Cut off infinite loops at max retry ceiling
        if current_attempts >= self.MAX_RETRIES:
            return {
                "status": "HALTED_MAX_RETRIES_EXCEEDED",
                "message": f"Self-healing ceiling (N={self.MAX_RETRIES}) reached. Control yielded to user.",
                "proposed_patch": None,
                "show_alert_modal": True
            }
            
        # 1. Parse stderr stack trace
        diagnostic = TracebackAnalyzer.parse_stderr(stderr_stream)
        
        # 2. Build diagnostic prompt context
        prompt = self._construct_diagnostic_prompt(failed_script, diagnostic)
        
        # 3. Request proposed fix from the local QLoRA model
        proposed_patch = self._query_model_for_patch(prompt)
        
        # 4. Increment retry state tracker
        self.retry_tracker[task_id] = current_attempts + 1
        
        # 5. Return payload for Zain's Slint UI modal
        return {
            "status": "PROPOSED_PATCH_READY",
            "task_id": task_id,
            "attempt": self.retry_tracker[task_id],
            "max_attempts": self.MAX_RETRIES,
            "error_summary": f"{diagnostic.error_type}: {diagnostic.error_message}",
            "original_script": failed_script,
            "proposed_patch": proposed_patch,
            "countdown_seconds": 5  # Slint dashboard triggers 5s countdown
        }

    def _construct_diagnostic_prompt(self, script: str, diag: ErrorDiagnostic) -> str:
        return f"""[AURIX SELF-HEALING DIAGNOSTIC]
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
        if self.llm_pipeline:
            return self.llm_pipeline.generate(prompt)
        return "# Self-healing patch\nimport os\nos.makedirs('./data', exist_ok=True)\n"
