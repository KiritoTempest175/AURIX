import os
import sqlite3
import duckdb
from typing import List, Dict, Any

class UIQueryConnector:

    def __init__(self, db_path: str = "./databases/telemetry/aurix_session.db"):
        self.sqlite_path = db_path
        
        # Ensure database directory and file exist prior to attaching in DuckDB
        os.makedirs(os.path.dirname(self.sqlite_path), exist_ok=True)
        if not os.path.exists(self.sqlite_path):
            with sqlite3.connect(self.sqlite_path) as conn:
                pass
        
        # Initialize DuckDB and attach the SQLite database for high-speed analytical queries
        self.duck_conn = duckdb.connect(':memory:')
        self.duck_conn.execute("INSTALL sqlite;")
        self.duck_conn.execute("LOAD sqlite;")
        abs_sqlite_path = os.path.abspath(self.sqlite_path).replace("\\", "/")
        self.duck_conn.execute(f"ATTACH '{abs_sqlite_path}' AS sqlite_db (TYPE SQLITE);")

    def fetch_execution_history(self, limit: int = 15) -> List[Dict[str, Any]]:
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
        minutes = int(time_window_minutes)
        query = f"""
            SELECT 
                time_bucket(INTERVAL '10 seconds', timestamp::TIMESTAMP) AS time_interval,
                ROUND(AVG(ram_allocated_gb), 2) AS avg_ram_gb,
                MAX(vram_peak_gb) AS peak_vram_gb,
                mode(training_state) AS dominant_state
            FROM sqlite_db.performance_telemetry
            WHERE timestamp::TIMESTAMP >= (now() AT TIME ZONE 'UTC') - INTERVAL '{minutes} minutes'
            GROUP BY time_interval
            ORDER BY time_interval ASC;
        """
        
        result = self.duck_conn.execute(query).fetchdf()
        return result.to_dict(orient="records")

    def fetch_pending_security_approvals(self) -> List[Dict[str, Any]]:

        with sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT audit_id, timestamp, requested_path, operation_type 
                FROM security_audit_trails 
                WHERE approval_status = 'PENDING'
                ORDER BY timestamp ASC
            """)
            
            return [dict(row) for row in cursor.fetchall()]