# LUNA Security Model & Hardening Specifications

## 1. Zero-Network Air-Gapped Perimeter
- LUNA operates completely on-device without outbound HTTP, WebSocket, or RPC connections.
- All intra-process communication between Rust and Python occurs through shared memory (`Arc<AtomicBool>`, `Arc<AtomicU8>`) and PyO3 C-ABI bindings.

## 2. Scoped Permissions & Action Categories
Autonomous capabilities are strictly partitioned into scoped action categories:
- `FILE_READ`: Sandboxed reading within `allowed_project_paths`.
- `FILE_WRITE`: Sandboxed writing within `allowed_project_paths`.
- `FILE_DELETE`: **Destructive** — Requires explicit user Trust Token authorization.
- `SHELL_EXEC`: Sandboxed PTY execution (`cmd.exe /C` with `CREATE_NO_WINDOW`). High-risk commands (`rm`, `del`, `format`, `drop table`, `shutdown`) require Trust Token confirmation.
- `CHECKPOINT_RESTORE`: **High Impact** — Requires Trust Token authorization.
- `LOCAL_SEARCH`: Web-free local vector and filesystem retrieval.

## 3. Secret Scrubbing & Privacy Redaction
Before any terminal output or user interaction is persisted into `execution_logs` or used in continuous training datasets, `security.secret_scrubber` passes the stream through regex and Shannon entropy analyzers:
- Redacts OpenAI API keys (`sk-...`), GitHub tokens (`ghp_...`), AWS keys (`AKIA...`), Slack tokens (`xoxb-...`), and JWTs.
- Strips private keys (`-----BEGIN RSA PRIVATE KEY-----`).
- Redacts password parameters (`password=...`, `pwd=...`, `api_key=...`).
- Identifies isolated high-entropy base64/hex strings exceeding Shannon entropy $\ge 4.3$.

## 4. Encryption at Rest (AES-256-GCM)
- Model checkpoints, adapter weights, and optimizer states are encrypted at rest using AES-256-GCM.
- Master keys are derived from local machine-anchored entropy via PBKDF2 (100,000 iterations).

## 5. Append-Only Audit Trail
- The SQLite table `security_audit_trails` records every sandbox query and Trust Token decision.
- Immutability is enforced at the database layer via `BEFORE UPDATE` and `BEFORE DELETE` triggers that abort unauthorized tampering.
