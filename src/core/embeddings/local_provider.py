"""
LocalProvider - Local embedding using sentence-transformers.

Model: all-MiniLM-L6-v2
- 22MB download
- 384 dimensions
- Fast inference
- Works offline
- Free

Usage:
    provider = LocalProvider()
    result = provider.embed("some code or text")
    vector = result.vector  # np.array of shape (384,)
"""

from typing import List, Optional
import numpy as np

from .provider import EmbeddingProvider, EmbeddingResult


# Lazy loading - don't import until needed
_model = None
_model_name = "all-MiniLM-L6-v2"


def _get_model():
    """
    Lazy load the model.
    Only imports sentence-transformers when first embedding is requested.
    """
    global _model

    if _model is not None:
        return _model

    try:
        from sentence_transformers import SentenceTransformer
        print(f"[Embeddings] Loading model: {_model_name}")
        _model = SentenceTransformer(_model_name)
        print(f"[Embeddings] Model loaded successfully")
        return _model
    except ImportError:
        raise ImportError(
            "sentence-transformers not installed. "
            "Run: pip install sentence-transformers"
        )


class LocalProvider(EmbeddingProvider):
    """
    Local embedding provider using sentence-transformers.

    Features:
    - Lazy model loading (only loads when needed)
    - Batch processing for efficiency
    - Works completely offline
    - No API keys needed

    Model: all-MiniLM-L6-v2
    Dimension: 384
    """

    MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
    DIMENSION = 384
    VERSION = "1.0"

    def __init__(self, preload: bool = False):
        """
        Initialize LocalProvider.

        Args:
            preload: If True, load model immediately. Otherwise lazy load.
        """
        if preload:
            _get_model()

    @property
    def model_id(self) -> str:
        return self.MODEL_ID

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    @property
    def version(self) -> str:
        return self.VERSION

    def embed(self, text: str) -> EmbeddingResult:
        """
        Embed a single text.

        Args:
            text: Text to embed

        Returns:
            EmbeddingResult with vector and metadata
        """
        model = _get_model()
        vector = model.encode(text, convert_to_numpy=True)

        return EmbeddingResult(
            vector=vector,
            text=text,
            model_id=self.model_id,
            dimension=self.dimension
        )

    def embed_batch(self, texts: List[str]) -> List[EmbeddingResult]:
        """
        Embed multiple texts efficiently.

        Uses batch processing for better performance.

        Args:
            texts: List of texts to embed

        Returns:
            List of EmbeddingResults
        """
        if not texts:
            return []

        model = _get_model()
        vectors = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

        return [
            EmbeddingResult(
                vector=vec,
                text=text,
                model_id=self.model_id,
                dimension=self.dimension
            )
            for vec, text in zip(vectors, texts)
        ]


class MockProvider(EmbeddingProvider):
    """
    Mock provider for testing.
    Returns random vectors without loading any model.
    """

    MODEL_ID = "mock/random-384"
    DIMENSION = 384
    VERSION = "test"

    @property
    def model_id(self) -> str:
        return self.MODEL_ID

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    @property
    def version(self) -> str:
        return self.VERSION

    def embed(self, text: str) -> EmbeddingResult:
        """Generate random embedding for testing."""
        # Use text hash as seed for reproducibility
        seed = hash(text) % (2**32)
        rng = np.random.RandomState(seed)
        vector = rng.randn(self.DIMENSION).astype(np.float32)
        # Normalize
        vector = vector / np.linalg.norm(vector)

        return EmbeddingResult(
            vector=vector,
            text=text,
            model_id=self.model_id,
            dimension=self.dimension
        )

    def embed_batch(self, texts: List[str]) -> List[EmbeddingResult]:
        """Generate random embeddings for testing."""
        return [self.embed(text) for text in texts]


def get_provider(provider_type: str = "local", **kwargs) -> EmbeddingProvider:
    """
    Factory function to get embedding provider.

    Args:
        provider_type: "local" or "mock"
        **kwargs: Additional arguments for provider

    Returns:
        EmbeddingProvider instance
    """
    if provider_type == "local":
        return LocalProvider(**kwargs)
    elif provider_type == "mock":
        return MockProvider()
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")
