-- 1. Execution Telemetry Logs
-- Stores the history of terminal commands, UI actions, and their outcomes.
-- Used by the Self-Healing Engine to diagnose errors and propose patches.
CREATE TABLE IF NOT EXISTS execution_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    action_type TEXT NOT NULL, -- 'TERMINAL', 'UI_AUTOMATION', 'BACKGROUND_TASK'
    target_command TEXT NOT NULL,
    status TEXT NOT NULL, -- 'SUCCESS', 'FAILED', 'THROTTLED'
    return_code INTEGER,
    error_traceback TEXT
);

-- 2. Performance Time-Series Data
-- Tracks hardware utilization over time.
-- The Rust Governor polls sysinfo and nvml-wrapper and writes here to ensure 
-- the system stays under the 12.0 GB RAM and 6.0 GB VRAM hard ceilings.
CREATE TABLE IF NOT EXISTS performance_telemetry (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    ram_allocated_gb REAL NOT NULL,
    vram_peak_gb REAL NOT NULL,
    training_state TEXT NOT NULL -- 'TRAINING', 'THROTTLED', 'GRACEFUL_CHECKPOINT'
);

-- 3. Security Audit Trails
-- Logs every action interacting with the Rust Path-Canonicalization Sandbox ("File Jail").
-- High-risk operations require a valid Trust Token validated via the UI Review Card.
CREATE TABLE IF NOT EXISTS security_audit_trails (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    requested_path TEXT NOT NULL,
    operation_type TEXT NOT NULL, -- 'READ', 'WRITE', 'DELETE', 'EXECUTE'
    trust_token_id TEXT,
    approval_status TEXT NOT NULL, -- 'APPROVED_BY_USER', 'REJECTED', 'AUTO_BLOCKED', 'PENDING'
    sandbox_enforced BOOLEAN NOT NULL DEFAULT 1
);