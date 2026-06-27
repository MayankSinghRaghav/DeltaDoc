"""chunk.py — Extractor Agent (PRD §10, agent #2).

Heading-aware chunking + per-chunk normalized hashing (PRD §5 ChunkRecord, §7).
``heading_path`` carries the H1->Hn breadcrumb.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

# Single source of truth for normalization lives in extract.py — see its
# docstring. Imported here rather than duplicated.
from .extract import _normalize
from .schema import HASH_PREFIX, ChunkRecord, PageRecord

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_SLUG_NONWORD_RE = re.compile(r"[^a-z0-9]+")


def _slug(heading: str) -> str:
    slug = _SLUG_NONWORD_RE.sub("-", heading.strip().lower()).strip("-")
    return slug or "section"


def _token_estimate(text: str) -> int:
    """Simple heuristic: whitespace word count (no tiktoken dependency)."""
    return len(text.split())


def _hash_text(text: str) -> str:
    return HASH_PREFIX + hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


def chunk_page(page: PageRecord) -> list[ChunkRecord]:
    """Split a PageRecord into heading-aware ChunkRecords with stable chunk_hash.

    Boundary rule: a new chunk starts at each ATX heading line; the chunk's
    ``text`` is the section body only (the heading line itself is excluded —
    it is already captured via ``heading_path``). Content appearing before
    the first heading (if any) forms an initial chunk with an empty
    ``heading_path``. Empty-body sections (heading immediately followed by
    another heading, or trailing) are skipped — nothing to chunk.
    """
    lines = page.markdown.split("\n")

    parsed = urlparse(page.url)
    id_base = f"{parsed.netloc}{parsed.path}"

    # Each entry: (heading_path_tuple, list_of_body_lines)
    sections: list[tuple[list[str], list[str]]] = []
    stack: list[tuple[int, str]] = []  # (level, heading_text)
    current_body: list[str] = []

    def flush():
        path = [h for _, h in stack]
        sections.append((path, current_body[:]))

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            flush()
            current_body.clear()
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading_text))
        else:
            current_body.append(line)
    flush()

    chunks: list[ChunkRecord] = []
    seen_ids: dict[str, int] = {}
    order = 0
    for heading_path, body_lines in sections:
        text = _normalize("\n".join(body_lines))
        if not text:
            continue

        slug_parts = [_slug(h) for h in heading_path]
        base_id = id_base + "#" + (".".join(slug_parts) if slug_parts else "root")
        chunk_id = base_id
        if base_id in seen_ids:
            seen_ids[base_id] += 1
            chunk_id = f"{base_id}-{seen_ids[base_id]}"
        else:
            seen_ids[base_id] = 0

        chunks.append(
            ChunkRecord(
                chunk_id=chunk_id,
                url=page.url,
                heading_path=heading_path,
                text=text,
                token_estimate=_token_estimate(text),
                chunk_hash=_hash_text(text),
                order=order,
            )
        )
        order += 1

    return chunks
