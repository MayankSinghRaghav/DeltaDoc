"""Tests for chunk.py — Extractor Agent (PRD §10, agent #2)."""

from __future__ import annotations

from deltadocs.chunk import chunk_page
from deltadocs.schema import PageRecord

MARKDOWN = """\
# Getting Started

Welcome to the docs. This is the intro section.

## Installation

Run pip install to get started.

## Configuration

### Advanced Options

Set the ADVANCED_FLAG env var for advanced mode.

# Reference

See the API reference below.
"""


def _page(markdown: str = MARKDOWN) -> PageRecord:
    return PageRecord(
        url="https://example.com/docs/guide",
        title="Guide",
        markdown=markdown,
        content_hash="sha256:" + "0" * 64,
        fetched_at="2026-06-21T10:00:00Z",
        status=200,
        depth=1,
    )


def test_chunk_page_counts_and_heading_paths():
    chunks = chunk_page(_page())

    # Sections with non-empty bodies: Getting Started, Installation,
    # Configuration>Advanced Options, Reference. "Configuration" itself has
    # no body text of its own (its only content is the Advanced Options
    # subsection), so it produces no standalone chunk.
    assert len(chunks) == 4

    paths = [c.heading_path for c in chunks]
    assert paths == [
        ["Getting Started"],
        ["Getting Started", "Installation"],
        ["Getting Started", "Configuration", "Advanced Options"],
        ["Reference"],
    ]


def test_chunk_page_orders_are_zero_based_sequential():
    chunks = chunk_page(_page())
    assert [c.order for c in chunks] == list(range(len(chunks)))


def test_chunk_id_and_hash_stable_across_runs():
    chunks1 = chunk_page(_page())
    chunks2 = chunk_page(_page())

    ids1 = [c.chunk_id for c in chunks1]
    ids2 = [c.chunk_id for c in chunks2]
    assert ids1 == ids2
    assert len(set(ids1)) == len(ids1)  # unique within the page

    hashes1 = [c.chunk_hash for c in chunks1]
    hashes2 = [c.chunk_hash for c in chunks2]
    assert hashes1 == hashes2
    for h in hashes1:
        assert h.startswith("sha256:")


def test_chunk_hash_ignores_whitespace_only_changes():
    base_chunks = chunk_page(_page())

    reformatted_markdown = MARKDOWN.replace(
        "Run pip install to get started.",
        "Run   pip install   to get started.\n\n\n\n",
    )
    reformatted_chunks = chunk_page(_page(reformatted_markdown))

    base_install = next(c for c in base_chunks if c.heading_path == ["Getting Started", "Installation"])
    reformatted_install = next(
        c for c in reformatted_chunks if c.heading_path == ["Getting Started", "Installation"]
    )
    assert base_install.chunk_hash == reformatted_install.chunk_hash
