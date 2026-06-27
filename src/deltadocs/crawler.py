"""crawler.py — Crawler Agent (PRD §10, agent #1).

v1 scope (PRD §7): static/SSG docs only — no headless browser. Discovery is
BFS from ``start_url`` using sitemap.xml (if present) plus in-domain links
parsed out of fetched HTML. Politeness: small inter-request delay + tiny
retry/backoff on timeouts and 5xx. robots.txt is honored via stdlib
``urllib.robotparser`` unless explicitly disabled.
"""

from __future__ import annotations

import fnmatch
import time
import urllib.robotparser
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse
from xml.etree import ElementTree

import httpx

from .schema import RawPage

USER_AGENT = "DeltaDocs/0.1 (+https://github.com/deltadocs)"
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.5
_REQUEST_DELAY_SECONDS = 0.1


class _LinkParser(HTMLParser):
    """Minimal <a href> collector — no need for a full DOM parser here."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.append(value)


def _extract_links(html: str) -> list[str]:
    parser = _LinkParser()
    try:
        parser.feed(html)
    except Exception:
        # Malformed HTML shouldn't abort the crawl — just yield what we got.
        pass
    return parser.hrefs


def _fetch_sitemap_urls(client: httpx.Client, base: str) -> list[str]:
    """Best-effort sitemap.xml fetch; any failure just means no extra seeds."""
    sitemap_url = urljoin(base, "/sitemap.xml")
    try:
        resp = client.get(sitemap_url, timeout=10, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return []
        root = ElementTree.fromstring(resp.text)
    except Exception:
        return []
    urls = []
    for elem in root.iter():
        if elem.tag.endswith("loc") and elem.text:
            urls.append(elem.text.strip())
    return urls


def _get_with_retry(client: httpx.Client, url: str) -> httpx.Response | None:
    """A couple of attempts with backoff on timeouts / 5xx; else give up."""
    last_exc = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            resp = client.get(url, timeout=10, headers={"User-Agent": USER_AGENT})
            if resp.status_code >= 500 and attempt < _RETRY_ATTEMPTS - 1:
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            return resp
        except httpx.TimeoutException as exc:
            last_exc = exc
            if attempt < _RETRY_ATTEMPTS - 1:
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
    if last_exc is not None:
        return None
    return None


def _path_allowed(
    path: str,
    include_globs: list[str] | None,
    exclude_globs: list[str] | None,
) -> bool:
    if exclude_globs and any(fnmatch.fnmatch(path, pat) for pat in exclude_globs):
        return False
    if include_globs and not any(fnmatch.fnmatch(path, pat) for pat in include_globs):
        return False
    return True


def crawl(
    start_url: str,
    *,
    max_pages: int = 100,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    respect_robots_txt: bool = True,
    _client: httpx.Client | None = None,
) -> list[RawPage]:
    """Crawl a docs site and return raw pages (PRD §5 inputs, §8 acceptance).

    ``_client`` is a private, keyword-only test seam: pass an
    ``httpx.Client(transport=httpx.MockTransport(handler))`` in tests to keep
    them offline/deterministic; production callers never set it and get a
    real ``httpx.Client``.
    """
    owns_client = _client is None
    client = _client if _client is not None else httpx.Client(follow_redirects=True)

    try:
        parsed_start = urlparse(start_url)
        host = parsed_start.netloc

        robots = urllib.robotparser.RobotFileParser()
        if respect_robots_txt:
            robots_url = urljoin(start_url, "/robots.txt")
            try:
                resp = client.get(robots_url, timeout=10, headers={"User-Agent": USER_AGENT})
                if resp.status_code == 200:
                    robots.parse(resp.text.splitlines())
                else:
                    robots.parse([])
            except Exception:
                robots.parse([])

        def robots_ok(url: str) -> bool:
            if not respect_robots_txt:
                return True
            return robots.can_fetch(USER_AGENT, url)

        start_url_clean, _ = urldefrag(start_url)

        # Seed the BFS queue with start_url (depth 0). Sitemap entries are
        # collected separately and only appended to the queue (always at
        # depth 0) after the link-following BFS drains — that way pages also
        # reachable by links get their proper link-derived depth, and the
        # sitemap is purely a fallback for orphan pages link-crawling misses.
        seen: set[str] = {start_url_clean}
        queue: deque[tuple[str, int]] = deque([(start_url_clean, 0)])

        sitemap_urls: list[str] = []
        for sm_url in _fetch_sitemap_urls(client, start_url):
            sm_url, _ = urldefrag(sm_url)
            if urlparse(sm_url).netloc != host:
                continue
            if not _path_allowed(urlparse(sm_url).path, include_globs, exclude_globs):
                continue
            sitemap_urls.append(sm_url)

        pages: list[RawPage] = []

        while queue and len(pages) < max_pages:
            url, depth = queue.popleft()
            path = urlparse(url).path or "/"

            is_start = url == start_url_clean
            if not is_start and not _path_allowed(path, include_globs, exclude_globs):
                continue
            if not robots_ok(url):
                continue

            resp = _get_with_retry(client, url)
            time.sleep(_REQUEST_DELAY_SECONDS)
            if resp is None:
                continue

            pages.append(
                RawPage(
                    url=str(resp.url) if hasattr(resp, "url") and resp.url else url,
                    raw_html=resp.text,
                    status=resp.status_code,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    depth=depth,
                )
            )

            if resp.status_code != 200:
                continue

            for href in _extract_links(resp.text):
                next_url = urljoin(url, href)
                next_url, _ = urldefrag(next_url)
                if urlparse(next_url).netloc != host:
                    continue
                if next_url in seen:
                    continue
                seen.add(next_url)
                queue.append((next_url, depth + 1))

            if not queue:
                # Link BFS exhausted — top up with any sitemap-only orphans.
                for sm_url in sitemap_urls:
                    if sm_url not in seen:
                        seen.add(sm_url)
                        queue.append((sm_url, 0))

        return pages
    finally:
        if owns_client:
            client.close()
