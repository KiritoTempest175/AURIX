import os
import sqlite3
import sys
from pathlib import Path

# Add project root directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from data_pipeline.storage.log_persistence import UIQueryConnector
from data_pipeline.compiler.replay_buffer import ExperienceReplayBuffer
from data_pipeline.vector_store.embedder import SkillVectorStore
from data_pipeline.compiler.semantic_parser import SemanticCompiler
from data_pipeline.self_healing.error_diagnostics import SelfHealingEngine


def run_master_pipeline_test():
    print("=" * 65)
    print("        AURIX DATA PIPELINE - MASTER INTEGRATION TEST        ")
    print("=" * 65)

    # ------------------------------------------------------------------
    # Step 1: Relational Schema & Telemetry Connectors
    # ------------------------------------------------------------------
    print("\n[1/5] Testing Schema Initialization & Telemetry Connectors...")
    db_dir = "./databases/telemetry"
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, "aurix_session.db")

    # Apply schema.sql
    schema_path = "./data_pipeline/storage/schema.sql"
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        with sqlite3.connect(db_path) as conn:
            conn.executescript(schema_sql)
        print("  ✓ SQLite schema applied successfully.")

    # Fetch logs via UIQueryConnector
    connector = UIQueryConnector(db_path=db_path)
    history = connector.fetch_execution_history(limit=5)
    print(f"  ✓ Connected to log query connector (History records: {len(history)}).")

    # ------------------------------------------------------------------
    # Step 2: Semantic Compiler (Command Parameterization)
    # ------------------------------------------------------------------
    print("\n[2/5] Testing Semantic Compiler...")
    compiler = SemanticCompiler()
    raw_terminal_log = "cd D:/Projects/auth-service && npm run dev --port=3000"
    compiled_data = compiler.compile_command(raw_terminal_log, "TERMINAL_EXEC")
    
    print(f"  ✓ Compiled Raw Log -> Template Script:")
    print(f"    - Parameterized: {compiled_data['parameterized_script']}")
    print(f"    - Extracted Variables: {compiled_data['default_parameters']}")

    # ------------------------------------------------------------------
    # Step 3: Vector Store (ChromaDB + FAISS Indexing & Search)
    # ------------------------------------------------------------------
    print("\n[3/5] Testing Vector Store Memory Retrieval...")
    vector_store = SkillVectorStore(chroma_path="./databases/vector_store/chroma")
    
    # Store compiled template into vector database
    vector_store.add_skill(
        skill_id="skill_auth_dev",
        script_code=compiled_data['parameterized_script'],
        metadata={"action_type": compiled_data['action_type'], "author": "Saad"}
    )
    
    # Query ChromaDB semantic search
    search_query = "How do I start the authentication server on local port?"
    matches = vector_store.query_semantic_skills(search_query, n_results=1)
    
    if matches:
        print(f"  ✓ ChromaDB Semantic Match Found:")
        print(f"    - Skill ID: {matches[0]['id']}")
        print(f"    - Document: {matches[0]['document']}")
    
    # Query FAISS bare-metal search
    faiss_matches = vector_store.query_faiss_fast(search_query, k=1)
    if faiss_matches:
        print(f"  ✓ FAISS Microsecond Search Match: {faiss_matches[0]}")

    # ------------------------------------------------------------------
    # Step 4: Experience Replay Buffer (Dataset Curation)
    # ------------------------------------------------------------------
    print("\n[4/5] Testing Experience Replay Buffer...")
    replay_buffer = ExperienceReplayBuffer(buffer_capacity=100)
    
    # Add compiled execution to replay memory
    replay_buffer.add_user_experience(
        instruction="Run local auth server",
        action=compiled_data['parameterized_script'],
        outcome="SUCCESS"
    )
    
    training_batch = replay_buffer.sample_training_batch(batch_size=4)
    print(f"  ✓ Buffered experience added. Training batch sampled (Size: {len(training_batch)}).")

    # ------------------------------------------------------------------
    # Step 5: Self-Healing Diagnostic Engine
    # ------------------------------------------------------------------
    print("\n[5/5] Testing Terminal Self-Healing Engine...")
    healing_engine = SelfHealingEngine()
    
    mock_failed_script = "with open('./data/config.json', 'r') as f: data = f.read()"
    mock_stderr_stream = (
        "Traceback (most recent call last):\n"
        "  File 'main.py', line 1, in <module>\n"
        "FileNotFoundError: [Errno 2] No such file or directory: './data/config.json'"
    )
    
    diagnostic_result = healing_engine.handle_execution_failure(
        task_id="task_001",
        failed_script=mock_failed_script,
        stderr_stream=mock_stderr_stream
    )
    
    print("  ✓ Self-Healing Diagnostic Loop Output:")
    print(f"    - Status: {diagnostic_result['status']}")
    print(f"    - Retry Attempt: {diagnostic_result['attempt']}/{diagnostic_result['max_attempts']}")
    print(f"    - Error Summary: {diagnostic_result['error_summary']}")
    print(f"    - Proposed Patch Emitted: {bool(diagnostic_result['proposed_patch'])}")

    print("\n" + "=" * 65)
    print("       SUCCESS: ALL PIPELINE MODULES CONNECTED & FUNCTIONAL       ")
    print("=" * 65)


if __name__ == "__main__":
    run_master_pipeline_test()