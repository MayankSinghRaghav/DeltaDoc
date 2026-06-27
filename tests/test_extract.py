"""Tests for extract.py — Extractor Agent (PRD §10, agent #2)."""

from __future__ import annotations

from deltadocs.extract import extract_page
from deltadocs.schema import PageRecord, RawPage

HTML = """\
<html>
<head><title>My Doc Title</title></head>
<body>
<nav><a href="/">Home</a><a href="/about">About</a></nav>
<header>Site Header</header>
<main>
<h1>Main Heading</h1>
<p>This is the first paragraph of real content.</p>
<h2>Sub Heading</h2>
<p>More real content goes here, with details.</p>
</main>
<footer>Copyright 2026 Example Corp</footer>
<aside>Sidebar link list</aside>
</body>
</html>
"""

# Same semantic content, but reformatted with extra spaces, blank lines, and
# CRLF line endings — must hash identically after normalization (PRD §8).
HTML_REFORMATTED = HTML.replace("\n", "\r\n").replace(
    "<p>This is the first paragraph of real content.</p>",
    "<p>This   is the first  paragraph   of real content.</p>\r\n\r\n\r\n\r\n",
)


def _raw(html: str) -> RawPage:
    return RawPage(
        url="https://example.com/doc",
        raw_html=html,
        status=200,
        fetched_at="2026-06-21T10:00:00Z",
        depth=0,
    )


def test_extract_page_returns_valid_record_with_stripped_boilerplate():
    record = extract_page(_raw(HTML))

    assert isinstance(record, PageRecord)
    assert record.markdown.strip() != ""
    assert record.content_hash.startswith("sha256:")
    assert record.url == "https://example.com/doc"
    assert record.status == 200
    assert record.depth == 0
    assert record.fetched_at == "2026-06-21T10:00:00Z"

    # nav/footer/sidebar boilerplate should not leak into the main content
    assert "Site Header" not in record.markdown
    assert "Copyright 2026" not in record.markdown
    assert "Sidebar link list" not in record.markdown
    assert "real content" in record.markdown


def test_extract_page_is_deterministic_across_runs():
    record1 = extract_page(_raw(HTML))
    record2 = extract_page(_raw(HTML))
    assert record1.content_hash == record2.content_hash


def test_extract_page_hash_ignores_trivial_reformatting():
    base = extract_page(_raw(HTML))
    reformatted = extract_page(_raw(HTML_REFORMATTED))
    assert base.content_hash == reformatted.content_hash
