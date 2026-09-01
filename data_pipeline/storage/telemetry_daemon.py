"""LUNA Live Telemetry Ingestion Daemon.

Processes real-time hardware metrics, power-state transitions, and execution logs
from the Rust core into SQLite schema, ensuring secrets are scrubbed before persistence.
"""

from __future__ import annotations

import logging
import os
import queue
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from security.secret_scrubber import SecretScrubber, get_default_scrubber

logger = logging.getLogger("luna.data_pipeline.telemetry_daemon")


class TelemetryIngestionDaemon:
    """Live ingestion daemon that processes hardware metrics and scrubbed execution logs."""

    def __init__(
        self,
        db_path: str = "./databases/telemetry/luna_session.db",
        scrubber: Optional[SecretScrubber] = None,
    ) -> None:
        self.db_path = db_path
        self.scrubber = scrubber or get_default_scrubber()
        self.event_queue: queue.Queue[Dict[str, Any]] = queue.Queue()
        self._listening = False

        # Ensure db directory exists
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        schema_file = Path(__file__).parent / "schema.sql"
        if schema_file.exists():
            schema = schema_file.read_text(encoding="utf-8")
        else:
            schema = """
            CREATE TABLE IF NOT EXISTS execution_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                action_type TEXT NOT NULL,
                target_command TEXT NOT NULL,
                status TEXT NOT NULL,
                return_code INTEGER,
                error_traceback TEXT,
                dataset_version_hash TEXT
            );
            CREATE TABLE IF NOT EXISTS performance_telemetry (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                ram_allocated_gb REAL NOT NULL,
                vram_peak_gb REAL NOT NULL,
                power_state TEXT NOT NULL DEFAULT 'ACTIVE',
                training_state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS security_audit_trails (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                requested_path TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                trust_token_id TEXT,
                approval_status TEXT NOT NULL,
                sandbox_enforced BOOLEAN NOT NULL DEFAULT 1
            );
            """
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(schema)
            conn.commit()

    def ingest_hardware_metrics(
        self,
        ram_gb: float,
        vram_gb: float,
        training_state: str,
        power_state: str = "ACTIVE",
    ) -> None:
        """Stream real-time RAM/VRAM and PowerState telemetry."""
        query = """
            INSERT INTO performance_telemetry (ram_allocated_gb, vram_peak_gb, power_state, training_state)
            VALUES (?, ?, ?, ?)
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(query, (ram_gb, vram_gb, power_state, training_state))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to ingest hardware metrics: {e}")

    def ingest_execution_log(
        self,
        session_id: str,
        action_type: str,
        target_command: str,
        status: str,
        return_code: int,
        error_traceback: Optional[str] = None,
        dataset_version_hash: Optional[str] = None,
    ) -> None:
        """Log execution events with credential redaction applied."""
        scrubbed_cmd = self.scrubber.scrub_text(target_command)
        scrubbed_traceback = self.scrubber.scrub_text(error_traceback) if error_traceback else None

        query = """
            INSERT INTO execution_logs (session_id, action_type, target_command, status, return_code, error_traceback, dataset_version_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    query,
                    (session_id, action_type, scrubbed_cmd, status, return_code, scrubbed_traceback, dataset_version_hash),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to ingest execution log: {e}")

    def consume_terminal_event(
        self,
        command: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        session_id: str = "active_desktop_session",
    ) -> None:
        """Consume stdout/stderr events from PTY execution, scrub secrets, and persist."""
        status = "SUCCESS" if exit_code == 0 else "FAILED"
        traceback = stderr if stderr.strip() else (stdout if exit_code != 0 else None)
        self.ingest_execution_log(
            session_id=session_id,
            action_type="TERMINAL_STDOUT_EVENT",
            target_command=command,
            status=status,
            return_code=exit_code,
            error_traceback=traceback,
        )

    def start_stdout_listener_hook(self) -> None:
        """Start background queue consumer thread."""
        if self._listening:
            return
        self._listening = True

        def listener_loop():
            while self._listening:
                try:
                    event = self.event_queue.get(timeout=1.0)
                    self.consume_terminal_event(
                        command=event.get("command", ""),
                        stdout=event.get("stdout", ""),
                        stderr=event.get("stderr", ""),
                        exit_code=event.get("exit_code", 0),
                        session_id=event.get("session_id", "active_desktop_session"),
                    )
                except queue.Empty:
                    continue

        threading.Thread(target=listener_loop, daemon=True, name="TelemetryListener").start()


_GLOBAL_TELEMETRY_DAEMON: Optional[TelemetryIngestionDaemon] = None


def get_default_telemetry_daemon() -> TelemetryIngestionDaemon:
    """Return default singleton TelemetryIngestionDaemon."""
    global _GLOBAL_TELEMETRY_DAEMON
    if _GLOBAL_TELEMETRY_DAEMON is None:
        _GLOBAL_TELEMETRY_DAEMON = TelemetryIngestionDaemon()
    return _GLOBAL_TELEMETRY_DAEMON