"""mcp_server.py — Delivery Agent (PRD §10, agent #8): MCP server.

Exposes DeltaDocs to AI agents (e.g. Claude) as callable tools. The tool LOGIC
(``crawl_docs`` / ``diff_docs``) is plain functions wrapping the pipeline + diff
engine, so it is unit-tested directly; the MCP transport (FastMCP) is a thin
wrapper with a lazy import (optional dep: ``pip install mcp``).
"""

from __future__ import annotations

from .diff import diff_chunks, load_prev_state, save_state, utc_now
from .pipeline import run_pipeline


def crawl_docs(start_url: str, max_pages: int = 50) -> dict:
    """Crawl a documentation site and return its LLM-ready chunks."""
    pages, chunks = run_pipeline(start_url, max_pages=max_pages)
    return {"start_url": start_url, "pages": len(pages),
            "chunks": [c.model_dump() for c in chunks]}


def diff_docs(start_url: str, state_dir: str, max_pages: int = 50) -> dict:
    """Crawl a docs site and return the ChangeSet vs the previous run (updates state)."""
    prev, prev_run_at = load_prev_state(start_url, state_dir)
    pages, chunks = run_pipeline(start_url, max_pages=max_pages)
    run_at = utc_now()
    changeset = diff_chunks(prev, chunks, start_url=start_url, run_at=run_at, prev_run_at=prev_run_at)
    save_state(start_url, chunks, state_dir, run_at)
    return changeset.model_dump()


def build_server():
    """Build the FastMCP server exposing the tools (lazy import; needs ``mcp``)."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("deltadocs")
    server.tool()(crawl_docs)
    server.tool()(diff_docs)
    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
