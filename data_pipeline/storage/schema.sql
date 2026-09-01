-- LUNA Persistent Telemetry & Security Audit Schema

-- 1. Execution Telemetry Logs (Secrets scrubbed before ingestion)
CREATE TABLE IF NOT EXISTS execution_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    action_type TEXT NOT NULL, -- 'TERMINAL', 'UI_AUTOMATION', 'BACKGROUND_TASK', 'WAKEWORD'
    target_command TEXT NOT NULL,
    status TEXT NOT NULL, -- 'SUCCESS', 'FAILED', 'THROTTLED', 'DRY_RUN'
    return_code INTEGER,
    error_traceback TEXT,
    dataset_version_hash TEXT
);

-- 2. Performance & Power Governor Time-Series Data
CREATE TABLE IF NOT EXISTS performance_telemetry (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    ram_allocated_gb REAL NOT NULL,
    vram_peak_gb REAL NOT NULL,
    power_state TEXT NOT NULL DEFAULT 'ACTIVE', -- 'ACTIVE', 'IDLE', 'LOCKED', 'SUSPENDING'
    training_state TEXT NOT NULL -- 'RUNNING', 'IDLE_BOOSTED', 'THROTTLED', 'HIBERNATED', 'STOPPED'
);

-- 3. Security Audit Trails (Append-Only Log)
CREATE TABLE IF NOT EXISTS security_audit_trails (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    requested_path TEXT NOT NULL,
    operation_type TEXT NOT NULL, -- 'READ', 'WRITE', 'DELETE', 'EXECUTE', 'CHECKPOINT_RESTORE'
    trust_token_id TEXT,
    approval_status TEXT NOT NULL, -- 'APPROVED_BY_USER', 'REJECTED', 'AUTO_BLOCKED', 'PENDING'
    sandbox_enforced BOOLEAN NOT NULL DEFAULT 1
);

-- Append-only trigger enforcing audit immutability
CREATE TRIGGER IF NOT EXISTS prevent_audit_update
BEFORE UPDATE ON security_audit_trails
BEGIN
    SELECT RAISE(ABORT, 'Security Invariant Violation: security_audit_trails is an append-only table.');
END;

CREATE TRIGGER IF NOT EXISTS prevent_audit_delete
BEFORE DELETE ON security_audit_trails
BEGIN
    SELECT RAISE(ABORT, 'Security Invariant Violation: security_audit_trails is an append-only table.');
END;