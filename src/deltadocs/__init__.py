"""DeltaDocs — change-tracked, LLM-ready chunks from documentation sites."""

from .schema import (
    ChangedChunk,
    ChangeSet,
    ChangeSummary,
    ChunkRecord,
    EnrichedChange,
    PageRecord,
    RawPage,
)

__all__ = [
    "PageRecord",
    "ChunkRecord",
    "RawPage",
    "ChangeSet",
    "ChangedChunk",
    "ChangeSummary",
    "EnrichedChange",
]
__version__ = "0.4.0"
