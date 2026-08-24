import os
from typing import List, Dict, Any
import chromadb
from chromadb.utils import embedding_functions
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

class SkillVectorStore:
    def __init__(
        self, 
        chroma_path: str = "./databases/vector_store/chroma",
        model_name: str = "all-MiniLM-L6-v2"
    ):
        self.chroma_path = chroma_path
        self.model_name = model_name
        
        # 1. Initialize local embedding function (Offline execution)
        self.embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=self.model_name
        )
        self.st_model = SentenceTransformer(self.model_name)
        
        # 2. Initialize ChromaDB persistent client for the Skill Action Library
        self.chroma_client = chromadb.PersistentClient(path=self.chroma_path)
        self.collection = self.chroma_client.get_or_create_collection(
            name="skill_action_library",
            metadata={"hnsw:space": "cosine"}, # Cosine distance for text semantics
            embedding_function=self.embed_fn
        )
        
        # 3. Initialize FAISS index for high-speed bare-metal L2 search
        self.faiss_dimension = 384  # Dimensionality of all-MiniLM-L6-v2
        self.faiss_index = faiss.IndexFlatL2(self.faiss_dimension)
        self.faiss_documents: List[str] = []

    def add_skill(self, skill_id: str, script_code: str, metadata: Dict[str, Any]):

        # Add to ChromaDB persistent collection
        self.collection.add(
            documents=[script_code],
            metadatas=[metadata],
            ids=[skill_id]
        )
        
        # Add to FAISS index for ultra-fast lookup
        embedding = self.st_model.encode([script_code]).astype("float32")
        self.faiss_index.add(embedding)
        self.faiss_documents.append(script_code)

    def query_semantic_skills(self, query_text: str, n_results: int = 3) -> List[Dict[str, Any]]:
        """
        Queries ChromaDB for semantic skill retrieval, returning scripts and metadata.
        """
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        
        formatted_results = []
        if results and results["documents"]:
            for i in range(len(results["documents"][0])):
                formatted_results.append({
                    "id": results["ids"][0][i],
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if "distances" in results and results["distances"] else None
                })
        return formatted_results

    def query_faiss_fast(self, query_text: str, k: int = 1) -> List[str]:

        if self.faiss_index.ntotal == 0:
            return []
            
        query_embedding = self.st_model.encode([query_text]).astype("float32")
        distances, indices = self.faiss_index.search(query_embedding, min(k, self.faiss_index.ntotal))
        
        matches = []
        for idx in indices[0]:
            if 0 <= idx < len(self.faiss_documents):
                matches.append(self.faiss_documents[idx])
        return matches

# --- Local Verification ---
if __name__ == "__main__":
    store = SkillVectorStore()
    
    # 1. Index a sample parameterized script
    store.add_skill(
        skill_id="skill_dev_server",
        script_code="cd ${PROJECT_PATH_1} && npm run dev --port=${PORT_NUMBER_2}",
        metadata={"action_type": "TERMINAL_EXEC", "author": "Saad"}
    )
    
    # 2. Perform semantic search
    matches = store.query_semantic_skills("Start dynamic node development server")
    print("Retrieved Skill:", matches)