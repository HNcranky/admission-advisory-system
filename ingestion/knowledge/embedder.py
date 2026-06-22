"""Re-export shim. GeminiEmbedder moved to services.inference.embedder (audit §4.8)."""
from services.inference.embedder import GeminiEmbedder, l2_normalize

__all__ = ["GeminiEmbedder", "l2_normalize"]
