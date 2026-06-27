"""extract.py — Extractor Agent (PRD §10, agent #2).

Owns main-content extraction to markdown + normalization + content hashing.
Normalization quality is the single most important v2-diff correctness factor
(PRD §7).
"""

from __future__ import annotations

import hashlib
import re

import trafilatura
from markdownify import markdownify

from .schema import HASH_PREFIX, PageRecord, RawPage

_BLANK_RUN_RE = re.compile(r"\n{3,}")
_SPACE_RUN_RE = re.compile(r"[ \t]+")
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _normalize(text: str) -> str:
    """Single source of truth for normalization (imported by chunk.py too).

    Rules (PRD §7/§8 — must be stable across runs and immune to trivial
    reformatting): normalize line endings to \\n, collapse runs of
    spaces/tabs to one, strip trailing whitespace per line, collapse 3+
    consecutive blank lines to a single blank line, strip leading/trailing
    whitespace of the whole document.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACE_RUN_RE.sub(" ", line).rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text.strip()


def _hash_text(text: str) -> str:
    return HASH_PREFIX + hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


def _extract_title(raw_html: str, markdown: str) -> str:
    """title precedence: trafilatura metadata -> first H1 -> <title> -> ""."""
    try:
        meta = trafilatura.extract_metadata(raw_html)
        if meta and meta.title:
            return meta.title.strip()
    except Exception:
        pass

    h1_match = _H1_RE.search(markdown)
    if h1_match:
        return h1_match.group(1).strip()

    title_match = _TITLE_TAG_RE.search(raw_html)
    if title_match:
        return re.sub(r"\s+", " ", title_match.group(1)).strip()

    return ""


def extract_page(raw: RawPage) -> PageRecord:
    """Raw HTML -> clean-markdown PageRecord with a normalized content_hash."""
    markdown = trafilatura.extract(
        raw.raw_html,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        favor_precision=True,  # prioritize stripping nav/header/footer/sidebar
    )
    if not markdown:
        # Fallback: convert the whole document with markdownify (PRD §7).
        markdown = markdownify(raw.raw_html) or ""

    title = _extract_title(raw.raw_html, markdown)
    content_hash = _hash_text(markdown)

    return PageRecord(
        url=raw.url,
        title=title,
        markdown=markdown,
        content_hash=content_hash,
        fetched_at=raw.fetched_at,
        status=raw.status,
        depth=raw.depth,
    )
