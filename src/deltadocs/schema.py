"""schema.py — the frozen data contract for DeltaDocs.

This module is THE SEAM between subagents (PRD §10). The Crawler and the
Extractor both build against these types in parallel, so the contract is
defined and frozen *first*. Changing a field name or its meaning means
updating both sides plus the schema-validation tests (PRD §8).

v1 scope (PRD §5):
  - PageRecord  : one per crawled page.
  - ChunkRecord : one per chunk — the core artifact; ``chunk_hash`` is the diff key.
  - RawPage     : the Crawler -> Extractor hand-off. PRD §10 lists the crawler
                  output as ``[(url, raw_html, status, fetched_at, depth)]``;
                  it is typed here so both agents agree on the shape.

v2 additions (PRD §5 "v2 addition", §6) — appended below; the v1 types are
unchanged:
  - ChangedChunk / ChangeSummary / ChangeSet : the delta artifact emitted per run.

Design choices (noted per Engineering Principles §9):
  - pydantic v2 over stdlib dataclasses. §8 requires that all output validate
    against a JSON schema; pydantic provides validation + ``model_json_schema()``
    for free, which is less code than dataclasses + hand-written jsonschema.
    The Apify Python SDK is also pydantic-based.
  - ``extra="forbid"`` keeps the seam strict: an unexpected field is a contract
    violation rather than silently-carried data. ``frozen`` is intentionally
    left off so the parallel agents can build records incrementally.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Hashes are SHA-256 over *normalized* text (PRD §7) and stored prefixed,
# e.g. "sha256:ab12...". Normalization quality is the make-or-break factor for
# v2 diffing — owned by the Extractor (extract.py / chunk.py), not here.
HASH_PREFIX = "sha256:"


class RawPage(BaseModel):
    """Crawler -> Extractor hand-off (PRD §10, agent #1 output)."""

    model_config = ConfigDict(extra="forbid")

    url: str
    raw_html: str
    status: int
    fetched_at: str = Field(description="ISO 8601 UTC timestamp, e.g. 2026-06-21T10:00:00Z")
    depth: int = Field(ge=0, description="Link depth from start_url; start_url is depth 0")


class PageRecord(BaseModel):
    """One per crawled page (PRD §5)."""

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    markdown: str
    content_hash: str = Field(description=f"{HASH_PREFIX}-prefixed SHA-256 of normalized markdown")
    fetched_at: str = Field(description="ISO 8601 UTC timestamp, e.g. 2026-06-21T10:00:00Z")
    status: int
    depth: int = Field(ge=0, description="Link depth from start_url; start_url is depth 0")


class ChunkRecord(BaseModel):
    """One per chunk — the core artifact (PRD §5).

    ``chunk_hash`` is the diff key the v2 delta engine compares across runs.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(description="Stable id, e.g. host/path#heading.subheading")
    url: str
    heading_path: list[str] = Field(description="H1->Hn heading breadcrumb for this chunk")
    text: str
    token_estimate: int = Field(ge=0, description="Approximate token count of text")
    chunk_hash: str = Field(
        description=f"{HASH_PREFIX}-prefixed SHA-256 of normalized text — the diff key"
    )
    order: int = Field(ge=0, description="0-based position of the chunk within its page")


# ---------------------------------------------------------------------------
# v2 — delta-engine artifacts (PRD §5 "v2 addition", §6). Additive only.
# ---------------------------------------------------------------------------

ChangeType = Literal["added", "modified", "removed"]


class ChangedChunk(BaseModel):
    """A single chunk-level change between two runs (PRD §5 ChangeSet item).

    For ``added`` / ``modified`` the fields reflect the CURRENT run; for
    ``removed`` they reflect the PREVIOUS run (the chunk no longer exists).
    """

    model_config = ConfigDict(extra="forbid")

    change_type: ChangeType
    chunk_id: str
    url: str
    heading_path: list[str]
    text: str
    chunk_hash: str = Field(description=f"{HASH_PREFIX}-prefixed SHA-256 of normalized text")


class ChangeSummary(BaseModel):
    """Counts per change type (PRD §5)."""

    model_config = ConfigDict(extra="forbid")

    added: int = Field(ge=0)
    modified: int = Field(ge=0)
    removed: int = Field(ge=0)


class ChangeSet(BaseModel):
    """The v2 delta artifact — what changed since the previous run (PRD §5).

    ``prev_run_at`` is None on the first run (no prior state), in which case
    every chunk is reported as ``added``.
    """

    model_config = ConfigDict(extra="forbid")

    run_at: str = Field(description="ISO 8601 UTC timestamp of this run")
    prev_run_at: str | None = Field(default=None, description="Prior run timestamp, or None on first run")
    start_url: str
    summary: ChangeSummary
    changed_chunks: list[ChangedChunk]


class EnrichedChange(BaseModel):
    """v3 enrichment of a single change (PRD §10, agent #7): LLM summary + tags."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    change_type: ChangeType
    summary: str
    tags: list[str]
