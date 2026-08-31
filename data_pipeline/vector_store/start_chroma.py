import os
import sys
import uvicorn
import chromadb
from chromadb.config import Settings

def run_chroma_server(host: str = "127.0.0.1", port: int = 8000, persist_directory: str = "./databases/vector_store/chroma"):
    """
    Startup automation script for local ChromaDB vector store instance at http://localhost:8000.
    """
    abs_path = os.path.abspath(persist_directory)
    os.makedirs(abs_path, exist_ok=True)
    print(f"🚀 [ChromaDB Startup] Initializing local Chroma server on http://{host}:{port}")
    print(f"📁 [ChromaDB Startup] Persistence directory: {abs_path}")

    # Launch ChromaDB FastAPI server via uvicorn
    from chromadb.app import app
    app.state.settings = Settings(
        is_persistent=True,
        persist_directory=abs_path,
        anonymized_telemetry=False
    )
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    run_chroma_server()
