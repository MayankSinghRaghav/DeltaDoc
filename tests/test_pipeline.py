"""test_pipeline.py — Packaging (PRD §10, step 3) offline acceptance.

Exercises the full crawl -> extract -> chunk pipeline + llms.txt rendering
against a mocked site (no network), and asserts the §8 determinism property
at the pipeline level (re-run on unchanged input = identical hashes).
"""

from __future__ import annotations

import httpx

from deltadocs.pipeline import build_llms_full_txt, build_llms_txt, run_pipeline
from deltadocs.schema import ChunkRecord, PageRecord

_SITE = {
    "/": (
        "<html><head><title>Home</title></head><body><nav>nav junk</nav>"
        "<article><h1>Home</h1>"
        "<p>Welcome to the DeltaDocs example documentation site. This intro has "
        "plenty of words so the main-content extractor keeps it in the output.</p>"
        "<p>Read the <a href='/guide'>guide</a> and the <a href='/api'>API reference</a>.</p>"
        "</article><footer>footer junk</footer></body></html>"
    ),
    "/guide": (
        "<html><head><title>Guide</title></head><body><article><h1>Guide</h1>"
        "<p>This guide explains how to get started with the product in enough "
        "detail that the extractor retains the paragraph cleanly.</p>"
        "<h2>Install</h2><p>Installation instructions live here with several "
        "descriptive words so this section survives extraction too.</p>"
        "</article></body></html>"
    ),
    "/api": (
        "<html><head><title>API</title></head><body><article><h1>API</h1>"
        "<p>The API reference describes endpoints and parameters with sufficient "
        "prose to be extracted as a real content block by trafilatura.</p>"
        "</article></body></html>"
    ),
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path in ("/robots.txt", "/sitemap.xml"):
        return httpx.Response(404, text="")
    html = _SITE.get(path)
    if html is None:
        return httpx.Response(404, text="not found")
    return httpx.Response(200, text=html, headers={"content-type": "text/html"})


def _client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_handler), follow_redirects=True)


def test_pipeline_produces_valid_pages_and_chunks():
    pages, chunks = run_pipeline("https://docs.example.com/", _client=_client())
    assert pages, "expected at least one non-empty page"
    assert chunks, "expected at least one chunk"
    assert all(isinstance(p, PageRecord) for p in pages)
    assert all(isinstance(c, ChunkRecord) for c in chunks)
    assert all(c.chunk_hash.startswith("sha256:") for c in chunks)


def test_llms_outputs_non_empty():
    pages, _ = run_pipeline("https://docs.example.com/", _client=_client())
    llms = build_llms_txt(pages, "https://docs.example.com/")
    full = build_llms_full_txt(pages)
    assert llms.strip() and full.strip()
    assert "# docs.example.com" in llms
    assert all(p.url in llms for p in pages)


def test_pipeline_is_deterministic():
    p1, c1 = run_pipeline("https://docs.example.com/", _client=_client())
    p2, c2 = run_pipeline("https://docs.example.com/", _client=_client())
    assert [p.content_hash for p in p1] == [p.content_hash for p in p2]
    assert [c.chunk_hash for c in c1] == [c.chunk_hash for c in c2]
