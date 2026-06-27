"""test_mcp.py — v3 MCP tool logic (PRD §10 agent #8). Offline via a
monkeypatched pipeline; the FastMCP transport wrapper isn't unit-tested."""

from __future__ import annotations

import deltadocs.mcp_server as mcp_server
from deltadocs.schema import ChunkRecord, PageRecord


def _fake_run(start_url, **kw):
    page = PageRecord(url=start_url, title="T", markdown="# T",
                      content_hash="sha256:" + "0" * 64, fetched_at="t", status=200, depth=0)
    chunk = ChunkRecord(chunk_id="c1", url=start_url, heading_path=["T"], text="body",
                        token_estimate=1, chunk_hash="sha256:" + "1" * 64, order=0)
    return [page], [chunk]


def test_crawl_docs_returns_chunks(monkeypatch):
    monkeypatch.setattr(mcp_server, "run_pipeline", _fake_run)
    out = mcp_server.crawl_docs("https://docs.x/")
    assert out["pages"] == 1
    assert out["chunks"][0]["chunk_id"] == "c1"


def test_diff_docs_persists_state_across_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_server, "run_pipeline", _fake_run)
    first = mcp_server.diff_docs("https://docs.x/", str(tmp_path))
    assert first["summary"] == {"added": 1, "modified": 0, "removed": 0}
    assert first["prev_run_at"] is None
    second = mcp_server.diff_docs("https://docs.x/", str(tmp_path))
    assert second["summary"] == {"added": 0, "modified": 0, "removed": 0}
    assert second["prev_run_at"] is not None
