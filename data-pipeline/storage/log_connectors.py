import sqlite3
import duckdb
import os
from typing import List, Dict, Any

class UIQueryConnector:

    def __init__(self, db_path: str = "./databases/telemetry/aurix_session.db"):
        self.sqlite_path = db_path
        
        # Ensure database directory exists
        db_dir = os.path.dirname(self.sqlite_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
            
        # Initialize DuckDB and attach the SQLite database for analytical queries
        self.duck_conn = duckdb.connect(':memory:')
        try:
            self.duck_conn.execute("INSTALL sqlite;")
            self.duck_conn.execute("LOAD sqlite;")
            if os.path.exists(self.sqlite_path):
                self.duck_conn.execute(f"ATTACH '{self.sqlite_path}' AS sqlite_db (TYPE SQLITE);")
        except Exception:
            pass


    def fetch_execution_history(self, limit: int = 15) -> List[Dict[str, Any]]:
        """
        Fetches the most recent UI and terminal actions for the Slint command dashboard.
        Uses standard SQLite for fast, row-based retrieval.
        """
        if not os.path.exists(self.sqlite_path):
            return []

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT timestamp, action_type, target_command, status, return_code
                FROM execution_logs
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
            
            return [dict(row) for row in cursor.fetchall()]

    def fetch_hardware_telemetry(self, time_window_minutes: int = 5) -> List[Dict[str, Any]]:
        """
        Aggregates RAM/VRAM usage over time for the hardware HUD using DuckDB analytical queries.
        """
        if not os.path.exists(self.sqlite_path):
            return []

        query = f"""
            SELECT 
                timestamp,
                ram_allocated_gb,
                vram_peak_gb,
                training_state
            FROM sqlite_db.performance_telemetry
            WHERE timestamp >= datetime('now', '-{time_window_minutes} minutes')
            ORDER BY timestamp ASC
        """
        try:
            return self.duck_conn.execute(query).fetchdf().to_dict(orient='records')
        except Exception:
            return []

if __name__ == "__main__":
    connector = UIQueryConnector()
    print("AURIX Telemetry UIQueryConnector initialized.")
    print(f"Execution History ({len(connector.fetch_execution_history())} records found):", connector.fetch_execution_history())
    print(f"Hardware Telemetry ({len(connector.fetch_hardware_telemetry())} records found):", connector.fetch_hardware_telemetry())

