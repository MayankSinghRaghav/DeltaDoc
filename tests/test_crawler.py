"""test_crawler.py — Crawler Agent tests (PRD §10, agent #1).

Fully offline: a tiny in-memory site is served via httpx.MockTransport, with
no real network access. Site map:

    /                -> links to /docs/a, /docs/b, /docs/secret
    /sitemap.xml     -> lists /, /docs/a, /docs/b
    /robots.txt      -> Disallow: /docs/secret
    /docs/a          -> links to /docs/c (depth 2 from /)
    /docs/b          -> no outgoing links
    /docs/c          -> no outgoing links
    /docs/secret     -> disallowed by robots.txt
"""

from __future__ import annotations

import httpx

from deltadocs.crawler import crawl
from deltadocs.schema import RawPage

BASE = "https://docs.example.com"

PAGES_HTML = {
    "/": """<html><body>
        <a href="/docs/a">A</a>
        <a href="/docs/b">B</a>
        <a href="/docs/secret">Secret</a>
    </body></html>""",
    "/docs/a": """<html><body><a href="/docs/c">C</a></body></html>""",
    "/docs/b": """<html><body>no links here</body></html>""",
    "/docs/c": """<html><body>leaf page</body></html>""",
    "/docs/secret": """<html><body>shh</body></html>""",
}

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.example.com/</loc></url>
  <url><loc>https://docs.example.com/docs/a</loc></url>
  <url><loc>https://docs.example.com/docs/b</loc></url>
</urlset>"""

ROBOTS_TXT = """User-agent: *
Disallow: /docs/secret
"""


def make_handler():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/sitemap.xml":
            return httpx.Response(200, text=SITEMAP_XML)
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_TXT)
        if path in PAGES_HTML:
            return httpx.Response(200, text=PAGES_HTML[path])
        return httpx.Response(404, text="not found")

    return handler


def make_client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(make_handler()))


def test_returns_valid_raw_pages():
    pages = crawl(f"{BASE}/", _client=make_client())
    assert len(pages) > 0
    for page in pages:
        assert isinstance(page, RawPage)


def test_discovers_expected_pages():
    pages = crawl(f"{BASE}/", _client=make_client())
    paths = {httpx.URL(p.url).path for p in pages}
    assert paths == {"/", "/docs/a", "/docs/b", "/docs/c"}
    # /docs/secret is disallowed by robots.txt by default.
    assert "/docs/secret" not in paths


def test_max_pages_caps_results():
    pages = crawl(f"{BASE}/", max_pages=2, _client=make_client())
    assert len(pages) == 2


def test_exclude_globs_removes_matching_paths():
    pages = crawl(f"{BASE}/", exclude_globs=["/docs/b"], _client=make_client())
    paths = {httpx.URL(p.url).path for p in pages}
    assert "/docs/b" not in paths
    assert "/" in paths


def test_robots_txt_respected_by_default():
    pages = crawl(f"{BASE}/", _client=make_client())
    paths = {httpx.URL(p.url).path for p in pages}
    assert "/docs/secret" not in paths


def test_robots_txt_ignored_when_disabled():
    pages = crawl(f"{BASE}/", respect_robots_txt=False, _client=make_client())
    paths = {httpx.URL(p.url).path for p in pages}
    assert "/docs/secret" in paths


def test_depth_assigned_correctly():
    pages = crawl(f"{BASE}/", _client=make_client())
    by_path = {httpx.URL(p.url).path: p for p in pages}
    assert by_path["/"].depth == 0
    assert by_path["/docs/a"].depth == 1
    assert by_path["/docs/b"].depth == 1
    assert by_path["/docs/c"].depth == 2
