"""
FixOnce Embeddings Module

Abstraction layer for embedding providers.
Allows swapping models without changing index code.

Available Providers:
- FastEmbedProvider: ONNX-based, no PyTorch needed (recommended)
- LocalProvider: sentence-transformers (requires PyTorch)
- MockProvider: For testing
"""

from .provider import EmbeddingProvider, EmbeddingResult
from .config import EmbeddingConfig, get_default_config


def get_best_provider(preload: bool = False) -> EmbeddingProvider:
    """
    Get the best available embedding provider.

    Priority:
    1. FastEmbedProvider (ONNX-based, no PyTorch)
    2. LocalProvider (sentence-transformers, requires PyTorch)
    3. MockProvider (fallback for testing)

    Args:
        preload: If True, load model immediately

    Returns:
        Best available EmbeddingProvider
    """
    # Try FastEmbed first (ONNX-based, lighter)
    try:
        from .fastembed_provider import FastEmbedProvider
        return FastEmbedProvider(preload=preload)
    except ImportError:
        pass

    # Try sentence-transformers (requires PyTorch)
    try:
        from .local_provider import LocalProvider
        return LocalProvider(preload=preload)
    except ImportError:
        pass

    # Fallback to mock
    print("[Embeddings] WARNING: No real provider available, using MockProvider")
    from .local_provider import MockProvider
    return MockProvider()


__all__ = [
    'EmbeddingProvider',
    'EmbeddingResult',
    'EmbeddingConfig',
    'get_default_config',
    'get_best_provider',
]
