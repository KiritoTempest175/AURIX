import os
import sqlite3
import queue
import threading
from typing import Optional

class TelemetryIngestionDaemon:
    """
    Live ingestion daemon that processes real-time hardware metrics and 
    execution logs from the Rust core into the relational SQLite schema.
    """
    def __init__(self, db_path: str = "./databases/telemetry/aurix_session.db"):
        self.db_path = db_path
        self.event_queue: queue.Queue = queue.Queue()
        self._listening = False

        # Ensure db directory exists
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        schema = """
        CREATE TABLE IF NOT EXISTS execution_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            action_type TEXT NOT NULL,
            target_command TEXT NOT NULL,
            status TEXT NOT NULL,
            return_code INTEGER,
            error_traceback TEXT
        );
        CREATE TABLE IF NOT EXISTS performance_telemetry (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            ram_allocated_gb REAL NOT NULL,
            vram_peak_gb REAL NOT NULL,
            training_state TEXT NOT NULL
        );
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(schema)
            conn.commit()

    def ingest_hardware_metrics(self, ram_gb: float, vram_gb: float, training_state: str):
        """
        Streams real-time RAM/VRAM polling data from Rust's sysinfo/nvml wrappers.
        """
        query = """
            INSERT INTO performance_telemetry (ram_allocated_gb, vram_peak_gb, training_state)
            VALUES (?, ?, ?)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(query, (ram_gb, vram_gb, training_state))
            conn.commit()

    def ingest_execution_log(
        self, 
        session_id: str, 
        action_type: str, 
        target_command: str, 
        status: str, 
        return_code: int, 
        error_traceback: Optional[str] = None
    ):
        """
        Logs every terminal command or UI action intercepted by the Rust sandbox.
        """
        query = """
            INSERT INTO execution_logs (session_id, action_type, target_command, status, return_code, error_traceback)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(query, (session_id, action_type, target_command, status, return_code, error_traceback))
            conn.commit()

    def consume_terminal_event(
        self,
        command: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        session_id: str = "active_desktop_session"
    ):
        """
        Continuously consumes stdout events captured from terminal_hook.rs
        during active desktop sessions and persists them to the telemetry database.
        """
        status = "SUCCESS" if exit_code == 0 else "FAILED"
        traceback = stderr if stderr.strip() else (stdout if exit_code != 0 else None)
        self.ingest_execution_log(
            session_id=session_id,
            action_type="TERMINAL_STDOUT_EVENT",
            target_command=command,
            status=status,
            return_code=exit_code,
            error_traceback=traceback
        )

    def start_stdout_listener_hook(self):
        """
        Starts a background daemon thread that continuously consumes queued terminal events.
        """
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
                        session_id=event.get("session_id", "active_desktop_session")
                    )
                except queue.Empty:
                    continue

        threading.Thread(target=listener_loop, daemon=True).start()

# --- Local Verification ---
if __name__ == "__main__":
    daemon = TelemetryIngestionDaemon()
    daemon.start_stdout_listener_hook()
    daemon.consume_terminal_event("echo Hello from terminal_hook.rs", stdout="Hello from terminal_hook.rs\n", stderr="", exit_code=0)
    print("[OK] Successfully wired telemetry daemon stdout hook.")