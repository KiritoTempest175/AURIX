from typing import Dict, Any

class SelfHealingHook:
    """
    Acts as the entry point for the Rust PTY interceptor. 
    Diagnoses terminal errors and enforces the strict N=3 retry ceiling.
    """
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self.attempt_tracker: Dict[str, int] = {}

    def process_execution_failure(
        self, 
        task_id: str, 
        failed_command: str, 
        error_traceback: str
    ) -> Dict[str, Any]:
        """
        Invoked via PyO3 when a terminal process returns a non-zero exit code.
        """
        # 1. Check current attempts for this specific task
        current_attempts = self.attempt_tracker.get(task_id, 0)

        # 2. Enforce the strict N=3 ceiling
        if current_attempts >= self.max_retries:
            return {
                "status": "HALTED",
                "message": f"Self-healing ceiling (N={self.max_retries}) reached. Yielding control to user.",
                "proposed_patch": None,
                "requires_ui_override": True
            }

        # 3. Increment the tracker
        self.attempt_tracker[task_id] = current_attempts + 1

        # 4. Generate the patch (In production, this queries the local LLM)
        proposed_patch = self._generate_candidate_patch(failed_command, error_traceback)

        # 5. Return the payload to trigger Zain's UI countdown modal
        return {
            "status": "PATCH_READY",
            "task_id": task_id,
            "attempt": self.attempt_tracker[task_id],
            "max_attempts": self.max_retries,
            "proposed_patch": proposed_patch,
            "countdown_seconds": 5
        }

    def _generate_candidate_patch(self, command: str, traceback: str) -> str:
        """
        Mock generation of a patch. This will eventually pipe into your QLoRA model.
        """
        return f"# Automated fix for: {command}\n# Error was: {traceback.splitlines()[-1]}"


# --- Local Verification ---
if __name__ == "__main__":
    hook = SelfHealingHook(max_retries=3)
    
    # Simulate a loop where the engine keeps failing
    for i in range(4):
        print(f"\n--- Failure Trigger {i+1} ---")
        result = hook.process_execution_failure(
            task_id="compile_job_01",
            failed_command="npm run build",
            error_traceback="Error: missing package.json"
        )
        print(f"Status: {result['status']} | Attempt: {result.get('attempt', 'MAX')}/{hook.max_retries}")