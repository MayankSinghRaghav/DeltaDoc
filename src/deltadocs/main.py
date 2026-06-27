"""main.py — Apify Actor entry (PRD §10, agent #3 + #6 wiring).

v2 flow: load the prior run's chunks from the key-value store (keyed by
start_url), run the pipeline, diff to a ChangeSet, push the changed chunks to
the dataset (the delta — the v2 product value), and persist the new baseline +
artifacts. Pay-per-event is priced on changed chunks (PRD §6).
"""

from __future__ import annotations

import hashlib

from apify import Actor

from .diff import diff_chunks, utc_now
from .pipeline import build_llms_full_txt, build_llms_txt, run_pipeline
from .schema import ChunkRecord


def _state_key(start_url: str) -> str:
    return "state-" + hashlib.sha256(start_url.encode("utf-8")).hexdigest()[:16]


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        start_url = actor_input.get("start_url")
        if not start_url:
            raise ValueError("Input 'start_url' is required.")

        await Actor.charge("actor-start")

        store = await Actor.open_key_value_store()
        key = _state_key(start_url)
        prev_state = await store.get_value(key)
        prev_chunks = [ChunkRecord(**d) for d in prev_state["chunks"]] if prev_state else None
        prev_run_at = prev_state.get("run_at") if prev_state else None

        pages, chunks = run_pipeline(
            start_url,
            max_pages=actor_input.get("max_pages", 100),
            include_globs=actor_input.get("include_globs") or None,
            exclude_globs=actor_input.get("exclude_globs") or None,
            respect_robots_txt=actor_input.get("respect_robots_txt", True),
        )

        run_at = utc_now()
        changeset = diff_chunks(prev_chunks, chunks, start_url=start_url,
                                run_at=run_at, prev_run_at=prev_run_at)

        # The delta is the product: one dataset item per changed chunk; charge on it.
        if changeset.changed_chunks:
            await Actor.push_data([c.model_dump() for c in changeset.changed_chunks])
            await Actor.charge("changed-chunk", count=len(changeset.changed_chunks))

        # Persist artifacts + the new baseline for the next run.
        await store.set_value("changeset", changeset.model_dump())
        await store.set_value("pages", [p.model_dump() for p in pages])
        await store.set_value("llms.txt", build_llms_txt(pages, start_url),
                              content_type="text/plain; charset=utf-8")
        await store.set_value("llms-full.txt", build_llms_full_txt(pages),
                              content_type="text/plain; charset=utf-8")
        await store.set_value(key, {"start_url": start_url, "run_at": run_at,
                                    "chunks": [c.model_dump() for c in chunks]})

        s = changeset.summary
        Actor.log.info(f"ChangeSet +{s.added} ~{s.modified} -{s.removed} over {len(pages)} pages.")
