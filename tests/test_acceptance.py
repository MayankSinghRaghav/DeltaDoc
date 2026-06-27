"""test_acceptance.py — QA (PRD §10 step 4): the §8 v1 acceptance criteria
that can run deterministically offline.

Covered here:
  * Every PageRecord / ChunkRecord validates against its emitted JSON schema.
  * Fixture mini-site: deterministic chunk COUNT and stable hashes across two
    identical runs => re-running on unchanged input yields ZERO spurious
    changes (this is what proves normalization works, PRD §7/§8/§11).

NOT here (needs open network): the "10 named public docs sites, >=90% pages
non-empty markdown" run — see scripts/run_real_sites.py.
"""

from __future__ import annotations

import httpx
import jsonschema

from deltadocs.pipeline import run_pipeline
from deltadocs.schema import ChunkRecord, PageRecord

_SITE = {
    "/": (
        "<html><head><title>Home</title></head><body><nav>nav</nav><article>"
        "<h1>Home</h1><p>Welcome to the fixture documentation site with enough "
        "words for the extractor to retain this introductory paragraph.</p>"
        "<p>See the <a href='/guide'>guide</a> and <a href='/api'>API</a>.</p>"
        "</article><footer>foot</footer></body></html>"
    ),
    "/guide": (
        "<html><head><title>Guide</title></head><body><article><h1>Guide</h1>"
        "<p>This guide explains setup in enough detail to be extracted.</p>"
        "<h2>Install</h2><p>Install steps with descriptive prose retained.</p>"
        "</article></body></html>"
    ),
    "/api": (
        "<html><head><title>API</title></head><body><article><h1>API</h1>"
        "<p>API reference prose long enough to survive extraction cleanly.</p>"
        "</article></body></html>"
    ),
}


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path in ("/robots.txt", "/sitemap.xml"):
        return httpx.Response(404, text="")
    html = _SITE.get(request.url.path)
    return httpx.Response(200, text=html) if html else httpx.Response(404, text="")


def _client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_handler), follow_redirects=True)


def test_all_output_validates_against_json_schema():
    pages, chunks = run_pipeline("https://docs.example.com/", _client=_client())
    page_schema = PageRecord.model_json_schema()
    chunk_schema = ChunkRecord.model_json_schema()
    for p in pages:
        jsonschema.validate(instance=p.model_dump(mode="json"), schema=page_schema)
    for c in chunks:
        jsonschema.validate(instance=c.model_dump(mode="json"), schema=chunk_schema)
    assert pages and chunks


def test_unchanged_run_yields_zero_spurious_changes():
    _, c1 = run_pipeline("https://docs.example.com/", _client=_client())
    _, c2 = run_pipeline("https://docs.example.com/", _client=_client())
    # deterministic count
    assert len(c1) == len(c2)
    # identical chunk_id -> chunk_hash map on both runs => zero diff
    m1 = {c.chunk_id: c.chunk_hash for c in c1}
    m2 = {c.chunk_id: c.chunk_hash for c in c2}
    assert m1 == m2
    added = set(m2) - set(m1)
    removed = set(m1) - set(m2)
    modified = {k for k in m1.keys() & m2.keys() if m1[k] != m2[k]}
    assert not (added or removed or modified), (added, removed, modified)
