"""pipeline.py — Output/Packaging (PRD §10, agent #3): the v1 one-shot pipeline.

Composes the frozen seam crawl -> extract_page -> chunk_page and renders the
llms.txt / llms-full.txt outputs (PRD §5). Pure Python over the already-built
modules, so it is trivially testable offline (inject a mock httpx client).
"""

from __future__ import annotations

from urllib.parse import urlparse

from .chunk import chunk_page
from .crawler import crawl
from .extract import extract_page
from .schema import ChunkRecord, PageRecord


def run_pipeline(
    start_url: str,
    *,
    max_pages: int = 100,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    respect_robots_txt: bool = True,
    _client=None,
) -> tuple[list[PageRecord], list[ChunkRecord]]:
    """Crawl ``start_url`` and return ``(pages, chunks)``.

    Skips non-200 responses and pages whose extracted markdown is empty
    (PRD §8: only non-empty clean markdown counts). ``_client`` is forwarded
    to the crawler for offline testing.
    """
    raw_pages = crawl(
        start_url,
        max_pages=max_pages,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        respect_robots_txt=respect_robots_txt,
        _client=_client,
    )
    pages: list[PageRecord] = []
    chunks: list[ChunkRecord] = []
    for raw in raw_pages:
        if raw.status != 200:
            continue
        page = extract_page(raw)
        if not page.markdown.strip():
            continue
        pages.append(page)
        chunks.extend(chunk_page(page))
    return pages, chunks


def build_llms_txt(pages: list[PageRecord], start_url: str) -> str:
    """Curated index per the llms.txt convention: H1 + summary blockquote + links."""
    host = urlparse(start_url).netloc or start_url
    lines = [
        f"# {host}",
        "",
        f"> LLM-ready index of documentation crawled from {start_url}.",
        "",
        "## Pages",
    ]
    for p in sorted(pages, key=lambda p: p.url):
        lines.append(f"- [{p.title.strip() or p.url}]({p.url})")
    return "\n".join(lines) + "\n"


def build_llms_full_txt(pages: list[PageRecord]) -> str:
    """Full concatenated content (llms-full.txt convention)."""
    blocks = []
    for p in sorted(pages, key=lambda p: p.url):
        blocks.append(f"# {p.title.strip() or p.url}\n<{p.url}>\n\n{p.markdown.strip()}\n")
    return "\n---\n\n".join(blocks) + ("\n" if blocks else "")
