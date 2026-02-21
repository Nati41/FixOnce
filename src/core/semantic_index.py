"""
SemanticIndex - Per-project semantic search index.

Architecture:
- Uses EmbeddingProvider abstraction (not hardcoded model)
- Config file tracks model version for rebuild detection
- Lazy index creation (only builds when needed)
- Simple flat index first, FAISS optional upgrade

Storage:
    data/projects_v2/{project_id}.embeddings/
    ├── config.json      # Model version, dimension, metadata
    ├── vectors.npy      # Numpy array of vectors
    └── metadata.json    # Document metadata (text, timestamps, etc.)
"""

from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import json
import numpy as np

from .project_context import ProjectContext
from .embeddings.provider import EmbeddingProvider
from .embeddings.config import EmbeddingConfig, check_index_compatibility


@dataclass
class SearchResult:
    """Result from semantic search."""
    text: str
    score: float  # Similarity score (0-1)
    metadata: Dict[str, Any]
    rank: int


@dataclass
class Document:
    """Document stored in the index."""
    id: str
    text: str
    doc_type: str  # "insight", "decision", "error", "code"
    metadata: Dict[str, Any]
    created_at: str
    vector: Optional[np.ndarray] = None


class SemanticIndex:
    """
    Per-project semantic search index.

    Features:
    - Provider-agnostic (uses EmbeddingProvider abstraction)
    - Automatic rebuild detection when model changes
    - Lazy loading (doesn't load until search/add)
    - Incremental updates (add without full rebuild)

    Usage:
        from core.embeddings.local_provider import LocalProvider

        provider = LocalProvider()
        index = SemanticIndex(project_id, provider)

        # Add documents
        index.add("insight", "Always validate user input", {"source": "debug"})

        # Search
        results = index.search("input validation", k=5)
    """

    def __init__(self, project_id: str, provider: EmbeddingProvider):
        """
        Initialize SemanticIndex.

        Args:
            project_id: Project identifier
            provider: EmbeddingProvider instance
        """
        self.project_id = project_id
        self.provider = provider
        self.index_dir = ProjectContext.get_embeddings_dir(project_id)

        # Lazy loaded
        self._vectors: Optional[np.ndarray] = None
        self._documents: Optional[List[Document]] = None
        self._config: Optional[EmbeddingConfig] = None
        self._loaded = False

    @property
    def config(self) -> Optional[EmbeddingConfig]:
        """Get current config (loads if needed)."""
        if self._config is None:
            self._config = EmbeddingConfig.load(self.index_dir)
        return self._config

    def _ensure_loaded(self):
        """Load index from disk if not already loaded."""
        if self._loaded:
            return

        self._load_index()
        self._loaded = True

    def _load_index(self):
        """Load vectors and documents from disk."""
        vectors_file = self.index_dir / "vectors.npy"
        metadata_file = self.index_dir / "metadata.json"

        if not vectors_file.exists() or not metadata_file.exists():
            # No existing index
            self._vectors = np.array([]).reshape(0, self.provider.dimension)
            self._documents = []
            return

        # Check compatibility
        is_compatible, reason = check_index_compatibility(self.index_dir, self.provider)
        if not is_compatible:
            print(f"[SemanticIndex] Index incompatible ({reason}), needs rebuild")
            self._vectors = np.array([]).reshape(0, self.provider.dimension)
            self._documents = []
            return

        # Load vectors
        self._vectors = np.load(vectors_file)

        # Load documents
        with open(metadata_file, 'r', encoding='utf-8') as f:
            docs_data = json.load(f)

        self._documents = [
            Document(
                id=d['id'],
                text=d['text'],
                doc_type=d['doc_type'],
                metadata=d.get('metadata', {}),
                created_at=d.get('created_at', ''),
                vector=None  # Don't store vectors in Document objects
            )
            for d in docs_data
        ]

        print(f"[SemanticIndex] Loaded {len(self._documents)} documents")

    def _save_index(self):
        """Save vectors and documents to disk."""
        self.index_dir.mkdir(parents=True, exist_ok=True)

        # Save vectors
        vectors_file = self.index_dir / "vectors.npy"
        np.save(vectors_file, self._vectors)

        # Save documents
        metadata_file = self.index_dir / "metadata.json"
        docs_data = [
            {
                'id': d.id,
                'text': d.text,
                'doc_type': d.doc_type,
                'metadata': d.metadata,
                'created_at': d.created_at
            }
            for d in self._documents
        ]
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(docs_data, f, ensure_ascii=False, indent=2)

        # Save/update config
        if self._config is None:
            self._config = EmbeddingConfig(
                model_id=self.provider.model_id,
                dimension=self.provider.dimension,
                version=self.provider.version,
                provider_type=self.provider.__class__.__name__
            )
        self._config.document_count = len(self._documents)
        self._config.save(self.index_dir)

        print(f"[SemanticIndex] Saved {len(self._documents)} documents")

    def add(
        self,
        doc_type: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None
    ) -> str:
        """
        Add a document to the index.

        Args:
            doc_type: Type of document ("insight", "decision", "error", "code")
            text: Text content to index
            metadata: Additional metadata
            doc_id: Optional custom ID (auto-generated if not provided)

        Returns:
            Document ID
        """
        self._ensure_loaded()

        # Generate ID if not provided
        if doc_id is None:
            import hashlib
            doc_id = hashlib.md5(f"{doc_type}:{text}".encode()).hexdigest()[:12]

        # Check for duplicates
        for doc in self._documents:
            if doc.id == doc_id:
                print(f"[SemanticIndex] Document {doc_id} already exists, skipping")
                return doc_id

        # Embed text
        result = self.provider.embed(text)

        # Create document
        doc = Document(
            id=doc_id,
            text=text,
            doc_type=doc_type,
            metadata=metadata or {},
            created_at=datetime.now().isoformat()
        )

        # Add to index
        self._documents.append(doc)

        if len(self._vectors) == 0:
            self._vectors = result.vector.reshape(1, -1)
        else:
            self._vectors = np.vstack([self._vectors, result.vector])

        # Save incrementally
        self._save_index()

        return doc_id

    def add_batch(
        self,
        documents: List[Tuple[str, str, Optional[Dict[str, Any]]]]
    ) -> List[str]:
        """
        Add multiple documents efficiently.

        Args:
            documents: List of (doc_type, text, metadata) tuples

        Returns:
            List of document IDs
        """
        self._ensure_loaded()

        if not documents:
            return []

        # Filter out duplicates
        new_docs = []
        existing_ids = {d.id for d in self._documents}

        for doc_type, text, metadata in documents:
            import hashlib
            doc_id = hashlib.md5(f"{doc_type}:{text}".encode()).hexdigest()[:12]
            if doc_id not in existing_ids:
                new_docs.append((doc_id, doc_type, text, metadata or {}))
                existing_ids.add(doc_id)

        if not new_docs:
            return []

        # Batch embed
        texts = [text for _, _, text, _ in new_docs]
        results = self.provider.embed_batch(texts)

        # Add to index
        doc_ids = []
        new_vectors = []

        for (doc_id, doc_type, text, metadata), result in zip(new_docs, results):
            doc = Document(
                id=doc_id,
                text=text,
                doc_type=doc_type,
                metadata=metadata,
                created_at=datetime.now().isoformat()
            )
            self._documents.append(doc)
            new_vectors.append(result.vector)
            doc_ids.append(doc_id)

        # Update vectors
        if new_vectors:
            new_vectors_arr = np.array(new_vectors)
            if len(self._vectors) == 0:
                self._vectors = new_vectors_arr
            else:
                self._vectors = np.vstack([self._vectors, new_vectors_arr])

        # Save
        self._save_index()

        print(f"[SemanticIndex] Added {len(doc_ids)} documents")
        return doc_ids

    def search(
        self,
        query: str,
        k: int = 5,
        doc_type: Optional[str] = None,
        min_score: float = 0.0
    ) -> List[SearchResult]:
        """
        Search for similar documents.

        Args:
            query: Search query
            k: Number of results to return
            doc_type: Filter by document type (optional)
            min_score: Minimum similarity score (0-1)

        Returns:
            List of SearchResults sorted by score (highest first)
        """
        self._ensure_loaded()

        if len(self._documents) == 0:
            return []

        # Embed query
        query_result = self.provider.embed(query)
        query_vector = query_result.vector

        # Compute similarities
        # Normalize vectors for cosine similarity
        norms = np.linalg.norm(self._vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1  # Avoid division by zero
        normalized_vectors = self._vectors / norms

        query_norm = np.linalg.norm(query_vector)
        if query_norm > 0:
            normalized_query = query_vector / query_norm
        else:
            normalized_query = query_vector

        similarities = np.dot(normalized_vectors, normalized_query)

        # Get top-k indices
        if doc_type:
            # Filter by doc_type
            valid_indices = [
                i for i, d in enumerate(self._documents)
                if d.doc_type == doc_type
            ]
            if not valid_indices:
                return []
            filtered_sims = [(i, similarities[i]) for i in valid_indices]
            filtered_sims.sort(key=lambda x: x[1], reverse=True)
            top_indices = [i for i, _ in filtered_sims[:k]]
        else:
            top_indices = np.argsort(similarities)[-k:][::-1]

        # Build results
        results = []
        for rank, idx in enumerate(top_indices):
            score = float(similarities[idx])
            if score < min_score:
                continue

            doc = self._documents[idx]
            results.append(SearchResult(
                text=doc.text,
                score=score,
                metadata={
                    "doc_type": doc.doc_type,
                    "doc_id": doc.id,
                    "created_at": doc.created_at,
                    **doc.metadata
                },
                rank=rank + 1
            ))

        return results

    def delete(self, doc_id: str) -> bool:
        """
        Delete a document from the index.

        Args:
            doc_id: Document ID to delete

        Returns:
            True if deleted, False if not found
        """
        self._ensure_loaded()

        # Find document index
        idx = None
        for i, doc in enumerate(self._documents):
            if doc.id == doc_id:
                idx = i
                break

        if idx is None:
            return False

        # Remove from documents and vectors
        self._documents.pop(idx)
        self._vectors = np.delete(self._vectors, idx, axis=0)

        # Save
        self._save_index()

        return True

    def rebuild(self) -> int:
        """
        Rebuild entire index from documents.
        Use when model changes or index is corrupted.

        Returns:
            Number of documents indexed
        """
        self._ensure_loaded()

        if not self._documents:
            return 0

        print(f"[SemanticIndex] Rebuilding index with {len(self._documents)} documents...")

        # Re-embed all documents
        texts = [d.text for d in self._documents]
        results = self.provider.embed_batch(texts)

        # Update vectors
        self._vectors = np.array([r.vector for r in results])

        # Update config
        if self._config is None:
            self._config = EmbeddingConfig(
                model_id=self.provider.model_id,
                dimension=self.provider.dimension,
                version=self.provider.version,
                provider_type=self.provider.__class__.__name__
            )
        self._config.model_id = self.provider.model_id
        self._config.dimension = self.provider.dimension
        self._config.version = self.provider.version
        self._config.mark_rebuilt(len(self._documents))

        # Save
        self._save_index()

        print(f"[SemanticIndex] Rebuild complete")
        return len(self._documents)

    def stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        self._ensure_loaded()

        doc_types = {}
        for doc in self._documents:
            doc_types[doc.doc_type] = doc_types.get(doc.doc_type, 0) + 1

        return {
            "project_id": self.project_id,
            "document_count": len(self._documents),
            "doc_types": doc_types,
            "vector_dimension": self.provider.dimension,
            "model_id": self.provider.model_id,
            "index_dir": str(self.index_dir),
            "config": self.config.to_dict() if self.config else None
        }

    def clear(self):
        """Clear the entire index."""
        self._vectors = np.array([]).reshape(0, self.provider.dimension)
        self._documents = []
        self._save_index()
        print(f"[SemanticIndex] Index cleared")


def get_project_index(project_id: str, provider: Optional[EmbeddingProvider] = None) -> SemanticIndex:
    """
    Get SemanticIndex for a project.

    Args:
        project_id: Project identifier
        provider: Optional provider (uses LocalProvider if not specified)

    Returns:
        SemanticIndex instance
    """
    if provider is None:
        from .embeddings.local_provider import LocalProvider
        provider = LocalProvider()

    return SemanticIndex(project_id, provider)
