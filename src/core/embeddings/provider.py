"""
EmbeddingProvider - Abstract interface for embedding models.

This abstraction allows:
- Swapping models without changing index code
- Testing with mock providers
- Future support for remote APIs (OpenAI, etc.)

NEVER import specific models here. This is the interface only.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional
import numpy as np


@dataclass
class EmbeddingResult:
    """
    Result of embedding operation.
    Includes metadata for debugging and caching.
    """
    vector: np.ndarray
    text: str
    model_id: str
    dimension: int

    def __post_init__(self):
        """Validate embedding dimension matches vector."""
        if len(self.vector) != self.dimension:
            raise ValueError(
                f"Vector dimension {len(self.vector)} doesn't match "
                f"declared dimension {self.dimension}"
            )


class EmbeddingProvider(ABC):
    """
    Abstract base class for embedding providers.

    Implementations:
    - LocalProvider: sentence-transformers (offline, free)
    - OpenAIProvider: OpenAI embeddings (paid, high quality)
    - MockProvider: For testing

    Usage:
        provider = LocalProvider()
        result = provider.embed("some text")
        vector = result.vector
    """

    @property
    @abstractmethod
    def model_id(self) -> str:
        """
        Unique identifier for this model.
        Used for cache invalidation when model changes.

        Example: "sentence-transformers/all-MiniLM-L6-v2"
        """
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """
        Dimension of output vectors.

        Example: 384 for all-MiniLM-L6-v2
        """
        pass

    @property
    def version(self) -> str:
        """
        Version string for config tracking.
        Override if model has versions.
        """
        return "1.0"

    @abstractmethod
    def embed(self, text: str) -> EmbeddingResult:
        """
        Embed a single text.

        Args:
            text: Text to embed

        Returns:
            EmbeddingResult with vector and metadata
        """
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[EmbeddingResult]:
        """
        Embed multiple texts efficiently.

        Args:
            texts: List of texts to embed

        Returns:
            List of EmbeddingResults
        """
        pass

    def similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        Compute cosine similarity between two vectors.

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Similarity score between -1 and 1
        """
        dot = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot / (norm1 * norm2))

    def is_compatible_with(self, other_model_id: str, other_dimension: int) -> bool:
        """
        Check if this provider is compatible with existing index.

        Args:
            other_model_id: Model ID of existing index
            other_dimension: Dimension of existing index

        Returns:
            True if compatible (same model and dimension)
        """
        return self.model_id == other_model_id and self.dimension == other_dimension

    def get_config_dict(self) -> dict:
        """
        Get configuration dictionary for persistence.
        Used in index config.json.
        """
        return {
            "model_id": self.model_id,
            "dimension": self.dimension,
            "version": self.version,
            "provider_type": self.__class__.__name__
        }
