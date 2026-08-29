import sqlite3
from typing import Optional

class TelemetryIngestionDaemon:
    """
    Live ingestion daemon that processes real-time hardware metrics and 
    execution logs from the Rust core into the relational SQLite schema.
    """
    def __init__(self, db_path: str = "./databases/telemetry/aurix_session.db"):
        self.db_path = db_path

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

# --- Local Verification ---
if __name__ == "__main__":
    daemon = TelemetryIngestionDaemon()
    
    # Simulate an incoming metric from Rust
    daemon.ingest_hardware_metrics(ram_gb=8.4, vram_gb=3.8, training_state="TRAINING")
    print("✓ Successfully ingested live hardware frame.")