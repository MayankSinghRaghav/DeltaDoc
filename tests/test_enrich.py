"""test_enrich.py — v3 enrichment (PRD §10 agent #7). Fully offline: a fake
summarizer + a MockTransport-backed OpenAI-compatible client (no API key)."""

from __future__ import annotations

import json

import httpx

from deltadocs.enrich import enrich_changeset, make_openai_summarizer
from deltadocs.schema import ChangedChunk, ChangeSet, ChangeSummary, EnrichedChange


def _cc(ct, cid, text="Body text long enough."):
    return ChangedChunk(change_type=ct, chunk_id=cid, url=f"https://x/{cid}",
                        heading_path=["API", cid], text=text, chunk_hash="sha256:" + "0" * 64)


def _cs(chunks, a, m, r):
    return ChangeSet(run_at="t1", prev_run_at="t0", start_url="https://x",
                     summary=ChangeSummary(added=a, modified=m, removed=r), changed_chunks=chunks)


def test_enrich_calls_summarizer_for_added_modified_skips_removed():
    calls = []

    def fake(chunk):
        calls.append(chunk.chunk_id)
        return f"summary of {chunk.chunk_id}", ["api"]

    cs = _cs([_cc("added", "a"), _cc("modified", "b"), _cc("removed", "c")], 1, 1, 1)
    out = enrich_changeset(cs, fake)
    assert len(out) == 3 and all(isinstance(e, EnrichedChange) for e in out)
    assert calls == ["a", "b"]  # removed never hits the LLM
    removed = next(e for e in out if e.chunk_id == "c")
    assert removed.tags == ["removed"]
    assert next(e for e in out if e.chunk_id == "a").summary == "summary of a"


def test_openai_summarizer_parses_completion_via_mock_client():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        content = json.dumps({"summary": "X deprecated", "tags": ["deprecation", "api"]})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = httpx.Client(base_url="https://api.openai.com/v1",
                          transport=httpx.MockTransport(handler))
    summarize = make_openai_summarizer(api_key="test", client=client)
    summary, tags = summarize(_cc("modified", "b"))
    assert summary == "X deprecated"
    assert tags == ["deprecation", "api"]


def test_anthropic_summarizer_parses_messages_api_via_mock_client():
    from deltadocs.enrich import make_anthropic_summarizer

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/messages")
        assert request.headers.get("anthropic-version")
        text = json.dumps({"summary": "Auth section rewritten", "tags": ["api", "auth"]})
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})

    client = httpx.Client(base_url="https://api.anthropic.com",
                          transport=httpx.MockTransport(handler))
    summarize = make_anthropic_summarizer(api_key="test", client=client)
    summary, tags = summarize(_cc("modified", "b"))
    assert summary == "Auth section rewritten"
    assert tags == ["api", "auth"]
