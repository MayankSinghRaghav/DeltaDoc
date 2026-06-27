"""Integration tests — Orchestrator seam (PRD §10) + full v1->v2 path.

Asserts the frozen data contract (schema.py) and that the whole pipeline
composes end-to-end: crawl -> extract -> chunk -> diff, with all records
validating and an unchanged re-run producing zero changes.
"""

from __future__ import annotations

import httpx

from deltadocs.diff import diff_chunks
from deltadocs.pipeline import run_pipeline
from deltadocs.schema import ChunkRecord, PageRecord, RawPage

# PRD §5 sample payloads — the exact shapes these types must accept.
SAMPLE_PAGE = {
    "url": "https://docs.example.com/api/auth",
    "title": "Authentication",
    "markdown": "# Authentication\n...",
    "content_hash": "sha256:" + "0" * 64,
    "fetched_at": "2026-06-21T10:00:00Z",
    "status": 200,
    "depth": 2,
}
SAMPLE_CHUNK = {
    "chunk_id": "docs.example.com/api/auth#authentication.api-keys",
    "url": "https://docs.example.com/api/auth",
    "heading_path": ["Authentication", "API keys"],
    "text": "API keys are passed in the Authorization header.",
    "token_estimate": 142,
    "chunk_hash": "sha256:" + "0" * 64,
    "order": 3,
}


def test_types_import():
    assert PageRecord and ChunkRecord and RawPage


def test_pagerecord_validates_prd_sample():
    assert PageRecord(**SAMPLE_PAGE).model_dump() == SAMPLE_PAGE


def test_chunkrecord_validates_prd_sample():
    assert ChunkRecord(**SAMPLE_CHUNK).model_dump() == SAMPLE_CHUNK


def test_strict_contract_rejects_unknown_field():
    import pytest
    with pytest.raises(Exception):
        PageRecord(**{**SAMPLE_PAGE, "surprise": "nope"})


def test_records_emit_json_schema():
    assert PageRecord.model_json_schema()["title"] == "PageRecord"
    assert ChunkRecord.model_json_schema()["title"] == "ChunkRecord"


_SITE = {
    "/": "<html><head><title>Home</title></head><body><nav>n</nav><article><h1>Home</h1>"
         "<p>Intro paragraph with enough words to be extracted as a content chunk.</p>"
         "<p>See the <a href='/guide'>guide</a>.</p></article><footer>f</footer></body></html>",
    "/guide": "<html><head><title>Guide</title></head><body><article><h1>Guide</h1>"
              "<p>Guide body paragraph long enough to survive main-content extraction.</p>"
              "</article></body></html>",
}


def _client():
    def handler(request):
        if request.url.path in ("/robots.txt", "/sitemap.xml"):
            return httpx.Response(404, text="")
        html = _SITE.get(request.url.path)
        return httpx.Response(200, text=html) if html else httpx.Response(404, text="")
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_end_to_end_pipeline_and_diff():
    """crawl -> extract -> chunk -> diff, all records valid, re-run = zero changes."""
    pages, chunks = run_pipeline("https://docs.example.com/", _client=_client())
    assert pages and chunks
    assert all(isinstance(p, PageRecord) for p in pages)
    assert all(isinstance(c, ChunkRecord) for c in chunks)
    # Diffing a run against itself yields zero changes (the core v2 guarantee).
    cs = diff_chunks(chunks, chunks, start_url="https://docs.example.com/", run_at="t1")
    assert cs.summary.model_dump() == {"added": 0, "modified": 0, "removed": 0}
