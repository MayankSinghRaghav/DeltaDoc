"""enrich.py — Enrichment Agent (PRD §10, agent #7): per-change LLM summary + tags.

``enrich_changeset(changeset, summarizer)`` -> list[EnrichedChange]. The
summarizer is INJECTED, so the LLM provider is pluggable and tests run with a
fake (no key, no network). Two default summarizers are provided:
``make_openai_summarizer`` (any OpenAI-compatible /chat/completions endpoint)
and ``make_anthropic_summarizer`` (Claude Messages API). Auth is sent per
request, so you can pass your own httpx client (e.g. an ``httpx.MockTransport``)
without losing authentication.
"""

from __future__ import annotations

import json
import os
from typing import Callable

import httpx

from .schema import ChangedChunk, ChangeSet, EnrichedChange

# A summarizer maps a changed chunk -> (summary, tags).
Summarizer = Callable[[ChangedChunk], "tuple[str, list[str]]"]


def enrich_changeset(changeset: ChangeSet, summarizer: Summarizer) -> list[EnrichedChange]:
    """Attach a one-line summary + tags to each change.

    ``removed`` chunks no longer have meaningful content to summarize, so they
    get a deterministic label and skip the LLM (saves tokens).
    """
    out: list[EnrichedChange] = []
    for c in changeset.changed_chunks:
        if c.change_type == "removed":
            summary = f"Removed: {' > '.join(c.heading_path) or c.chunk_id}"
            tags = ["removed"]
        else:
            summary, tags = summarizer(c)
        out.append(EnrichedChange(chunk_id=c.chunk_id, change_type=c.change_type,
                                  summary=summary, tags=tags))
    return out


_SYSTEM_PROMPT = (
    "You summarize documentation changes for a RAG changelog. Given a doc chunk, "
    'reply with strict JSON: {"summary": "one sentence", "tags": ["kebab-case", ...]}. '
    "Tags name the topic/kind of change, e.g. api, deprecation, config."
)


def _user_content(chunk: ChangedChunk) -> str:
    return f"[{chunk.change_type}] {' > '.join(chunk.heading_path)}\n\n{chunk.text}"


def make_openai_summarizer(
    *,
    model: str = "gpt-4o-mini",
    api_key: str | None = None,
    base_url: str = "https://api.openai.com/v1",
    client: httpx.Client | None = None,
) -> Summarizer:
    """Summarizer over an OpenAI-compatible chat API (OpenAI, OpenRouter, local).

    Reads ``OPENAI_API_KEY`` when ``api_key`` is None. Point ``base_url``/``model``
    elsewhere to use a different provider. Pass ``client`` to test offline.
    """
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    _client = client or httpx.Client(base_url=base_url, timeout=30)

    def summarize(chunk: ChangedChunk) -> tuple[str, list[str]]:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _user_content(chunk)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        resp = _client.post("/chat/completions", json=body,
                            headers={"Authorization": f"Bearer {key}"})
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        return data.get("summary", ""), list(data.get("tags", []))

    return summarize


def make_anthropic_summarizer(
    *,
    model: str = "claude-3-5-haiku-latest",
    api_key: str | None = None,
    base_url: str = "https://api.anthropic.com",
    client: httpx.Client | None = None,
) -> Summarizer:
    """Summarizer over Anthropic's Messages API (Claude).

    Reads ``ANTHROPIC_API_KEY`` when ``api_key`` is None. Override ``model`` to
    use a different Claude model. Pass ``client`` to test offline.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    _client = client or httpx.Client(base_url=base_url, timeout=30)

    def summarize(chunk: ChangedChunk) -> tuple[str, list[str]]:
        body = {
            "model": model,
            "max_tokens": 200,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": _user_content(chunk)}],
        }
        resp = _client.post("/v1/messages", json=body,
                            headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"]
        data = json.loads(text)
        return data.get("summary", ""), list(data.get("tags", []))

    return summarize
