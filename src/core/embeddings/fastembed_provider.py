"""
FastEmbedProvider - Local embedding using fastembed (ONNX-based).

Model: BAAI/bge-small-en-v1.5
- ~50MB download
- 384 dimensions
- Fast inference (ONNX runtime)
- Works offline
- Free
- No PyTorch dependency!

Usage:
    provider = FastEmbedProvider()
    result = provider.embed("some code or text")
    vector = result.vector  # np.array of shape (384,)
"""

from typing import List, Optional
import numpy as np

from .provider import EmbeddingProvider, EmbeddingResult


# Lazy loading - don't import until needed
_model = None
_model_name = "BAAI/bge-small-en-v1.5"


def _get_model():
    """
    Lazy load the model.
    Only imports fastembed when first embedding is requested.
    """
    global _model

    if _model is not None:
        return _model

    try:
        from fastembed import TextEmbedding
        print(f"[Embeddings] Loading model: {_model_name}")
        _model = TextEmbedding(model_name=_model_name)
        print(f"[Embeddings] Model loaded successfully")
        return _model
    except ImportError:
        raise ImportError(
            "fastembed not installed. "
            "Run: pip install fastembed"
        )


class FastEmbedProvider(EmbeddingProvider):
    """
    Local embedding provider using fastembed (ONNX-based).

    Features:
    - Lazy model loading (only loads when needed)
    - Batch processing for efficiency
    - Works completely offline
    - No API keys needed
    - No PyTorch dependency (uses ONNX runtime)

    Model: BAAI/bge-small-en-v1.5
    Dimension: 384
    """

    MODEL_ID = "fastembed/bge-small-en-v1.5"
    DIMENSION = 384
    VERSION = "1.0"

    def __init__(self, preload: bool = False):
        """
        Initialize FastEmbedProvider.

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
        # fastembed returns a generator, need to convert to list
        vectors = list(model.embed([text]))
        vector = np.array(vectors[0])

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
        vectors = list(model.embed(texts))

        return [
            EmbeddingResult(
                vector=np.array(vec),
                text=text,
                model_id=self.model_id,
                dimension=self.dimension
            )
            for vec, text in zip(vectors, texts)
        ]
