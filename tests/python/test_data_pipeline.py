"""Integration tests for Data Pipeline: SQLite schema, telemetry ingestion, and secret scrubbing."""

import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from data_pipeline.storage.telemetry_daemon import TelemetryIngestionDaemon
from data_pipeline.self_healing.error_diagnostics import SelfHealingEngine, TracebackAnalyzer


@contextmanager
def get_temp_db_path():
    temp_dir = tempfile.mkdtemp(prefix="luna_db_test_")
    db_file = os.path.join(temp_dir, "test_session.db")
    try:
        yield db_file
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def test_telemetry_ingestion_and_secret_scrubbing(db_path: str):
    daemon = TelemetryIngestionDaemon(db_path=db_path)

    # Ingest command containing sensitive API key
    secret_cmd = "curl -H 'Authorization: Bearer sk-1234567890abcdef1234567890abcdef' https://api.local/endpoint"
    daemon.ingest_execution_log(
        session_id="test_sess",
        action_type="TERMINAL_COMMAND",
        target_command=secret_cmd,
        status="SUCCESS",
        return_code=0,
    )

    # Ingest hardware metrics
    daemon.ingest_hardware_metrics(ram_gb=8.5, vram_gb=3.2, training_state="RUNNING", power_state="IDLE")

    # Verify database contents
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT target_command FROM execution_logs WHERE session_id = 'test_sess'")
        row = cursor.fetchone()
        assert row is not None
        stored_cmd = row[0]
        assert "sk-1234567890" not in stored_cmd
        assert "[REDACTED_SECRET]" in stored_cmd

        cursor.execute("SELECT power_state, training_state FROM performance_telemetry")
        perf_row = cursor.fetchone()
        assert perf_row is not None
        assert perf_row[0] == "IDLE"
        assert perf_row[1] == "RUNNING"


def test_self_healing_traceback_parser():
    stderr_sample = """
Traceback (most recent call last):
  File "train.py", line 42, in <module>
    import unknown_library
ModuleNotFoundError: No module named 'unknown_library'
"""
    diagnostic = TracebackAnalyzer.parse_stderr(stderr_sample)
    assert diagnostic.error_type == "ModuleNotFoundError"
    assert "unknown_library" in diagnostic.error_message
    assert "train.py" in str(diagnostic.failed_line)


def test_self_healing_max_retries_ceiling():
    engine = SelfHealingEngine()
    task_id = "task_failure_test_1"
    failed_script = "import nonexistent"
    stderr = "ModuleNotFoundError: No module named 'nonexistent'"

    # Attempts 1, 2, 3
    r1 = engine.handle_execution_failure(task_id, failed_script, stderr)
    assert r1["status"] == "PROPOSED_PATCH_READY"
    assert r1["attempt"] == 1

    r2 = engine.handle_execution_failure(task_id, failed_script, stderr)
    assert r2["attempt"] == 2

    r3 = engine.handle_execution_failure(task_id, failed_script, stderr)
    assert r3["attempt"] == 3

    # Attempt 4 should halt due to retry ceiling
    r4 = engine.handle_execution_failure(task_id, failed_script, stderr)
    assert r4["status"] == "HALTED_MAX_RETRIES_EXCEEDED"
