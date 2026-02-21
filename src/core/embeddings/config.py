"""
EmbeddingConfig - Configuration and versioning for embeddings.

Handles:
- Model version tracking
- Rebuild detection when model changes
- Config persistence in index directory

IMPORTANT: When model changes, existing index must be rebuilt.
This config tracks that automatically.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
import json


@dataclass
class EmbeddingConfig:
    """
    Configuration for an embedding index.
    Stored in {project}.embeddings/config.json
    """
    model_id: str
    dimension: int
    version: str
    provider_type: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_rebuild: Optional[str] = None
    document_count: int = 0
    index_type: str = "flat"  # "flat", "faiss", "annoy"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "model_id": self.model_id,
            "dimension": self.dimension,
            "version": self.version,
            "provider_type": self.provider_type,
            "created_at": self.created_at,
            "last_rebuild": self.last_rebuild,
            "document_count": self.document_count,
            "index_type": self.index_type
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EmbeddingConfig":
        """Create from dictionary."""
        return cls(
            model_id=data.get("model_id", ""),
            dimension=data.get("dimension", 0),
            version=data.get("version", "1.0"),
            provider_type=data.get("provider_type", "unknown"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            last_rebuild=data.get("last_rebuild"),
            document_count=data.get("document_count", 0),
            index_type=data.get("index_type", "flat")
        )

    def save(self, index_dir: Path):
        """Save config to index directory."""
        index_dir.mkdir(parents=True, exist_ok=True)
        config_file = index_dir / "config.json"
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, index_dir: Path) -> Optional["EmbeddingConfig"]:
        """Load config from index directory."""
        config_file = index_dir / "config.json"
        if not config_file.exists():
            return None
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return cls.from_dict(json.load(f))
        except Exception:
            return None

    def needs_rebuild(self, provider) -> bool:
        """
        Check if index needs rebuild because model changed.

        Args:
            provider: EmbeddingProvider to compare against

        Returns:
            True if rebuild needed
        """
        if self.model_id != provider.model_id:
            return True
        if self.dimension != provider.dimension:
            return True
        if self.version != provider.version:
            return True
        return False

    def mark_rebuilt(self, document_count: int):
        """Mark index as rebuilt now."""
        self.last_rebuild = datetime.now().isoformat()
        self.document_count = document_count


# Default configuration
DEFAULT_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_DIMENSION = 384
DEFAULT_VERSION = "1.0"


def get_default_config() -> EmbeddingConfig:
    """Get default embedding configuration."""
    return EmbeddingConfig(
        model_id=DEFAULT_MODEL_ID,
        dimension=DEFAULT_DIMENSION,
        version=DEFAULT_VERSION,
        provider_type="LocalProvider"
    )


def check_index_compatibility(index_dir: Path, provider) -> tuple:
    """
    Check if existing index is compatible with provider.

    Args:
        index_dir: Path to index directory
        provider: EmbeddingProvider to check against

    Returns:
        (is_compatible, reason)
    """
    config = EmbeddingConfig.load(index_dir)

    if config is None:
        return (True, "no_existing_index")

    if config.needs_rebuild(provider):
        return (False, f"model_changed:{config.model_id}->{provider.model_id}")

    return (True, "compatible")
