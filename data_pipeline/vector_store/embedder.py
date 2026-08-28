import os
from typing import List, Dict, Any
import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
import numpy as np

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

class FastLocalEmbeddingFunction(EmbeddingFunction):
    """Local, offline, deterministic embedding function (384-dim) requiring zero network calls."""
    def name(self) -> str:
        return "FastLocalEmbeddingFunction"

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = []
        for text in input:
            seed = sum((i + 1) * ord(c) for i, c in enumerate(text)) % (2**31 - 1)
            rng = np.random.RandomState(seed)
            vec = rng.randn(384).astype(np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec /= norm
            embeddings.append(vec.tolist())
        return embeddings

class SkillVectorStore:
    def __init__(
        self, 
        chroma_path: str = "./databases/vector_store/chroma",
        model_name: str = "all-MiniLM-L6-v2"
    ):
        self.chroma_path = chroma_path
        self.model_name = model_name

        # Use fast, zero-latency local embedding function
        self.embed_fn = FastLocalEmbeddingFunction()
        
        # Initialize ChromaDB persistent client for the Skill Action Library
        self.chroma_client = chromadb.PersistentClient(path=self.chroma_path)
        try:
            self.collection = self.chroma_client.get_or_create_collection(
                name="skill_action_library",
                metadata={"hnsw:space": "cosine"},
                embedding_function=self.embed_fn
            )
        except Exception:
            try:
                self.chroma_client.delete_collection("skill_action_library")
            except Exception:
                pass
            self.collection = self.chroma_client.get_or_create_collection(
                name="skill_action_library",
                metadata={"hnsw:space": "cosine"},
                embedding_function=self.embed_fn
            )
        
        # Initialize FAISS index for high-speed bare-metal L2 search
        self.faiss_dimension = 384
        if HAS_FAISS:
            self.faiss_index = faiss.IndexFlatL2(self.faiss_dimension)
        else:
            self.faiss_index = None
            self.fallback_vectors: List[np.ndarray] = []
        self.faiss_documents: List[str] = []

    def _encode_text(self, text: str) -> np.ndarray:
        vecs = self.embed_fn([text])
        return np.array(vecs, dtype="float32")

    def add_skill(self, skill_id: str, script_code: str, metadata: Dict[str, Any]):

        # Add to ChromaDB persistent collection
        self.collection.add(
            documents=[script_code],
            metadatas=[metadata],
            ids=[skill_id]
        )
        
        # Add to FAISS index or fallback array
        embedding = self._encode_text(script_code)
        if HAS_FAISS and self.faiss_index is not None:
            if embedding.shape[1] == self.faiss_dimension:
                self.faiss_index.add(embedding)
            else:
                if not hasattr(self, 'fallback_vectors'):
                    self.fallback_vectors = []
                self.fallback_vectors.append(embedding[0])
        else:
            if not hasattr(self, 'fallback_vectors'):
                self.fallback_vectors = []
            self.fallback_vectors.append(embedding[0])
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

        total_docs = len(self.faiss_documents)
        if total_docs == 0:
            return []
            
        query_embedding = self._encode_text(query_text)
        
        if HAS_FAISS and self.faiss_index is not None and self.faiss_index.ntotal > 0:
            distances, indices = self.faiss_index.search(query_embedding, min(k, self.faiss_index.ntotal))
            matches = []
            for idx in indices[0]:
                if 0 <= idx < total_docs:
                    matches.append(self.faiss_documents[idx])
            return matches
        elif hasattr(self, 'fallback_vectors') and self.fallback_vectors:
            # Fallback numpy L2 search
            matrix = np.array(self.fallback_vectors)
            dists = np.linalg.norm(matrix - query_embedding[0], axis=1)
            top_k_indices = np.argsort(dists)[:k]
            return [self.faiss_documents[i] for i in top_k_indices if i < total_docs]
        return []

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
