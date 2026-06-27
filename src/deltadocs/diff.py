"""diff.py — Diff/State Agent (PRD §10, agent #6): the v2 delta engine.

Compares two runs of ChunkRecords by ``chunk_id`` + ``chunk_hash`` and emits a
ChangeSet of added / modified / removed chunks (PRD §5). Also persists a run's
chunks (keyed by ``start_url``) so the next run has a baseline to diff against
(PRD §6/§7). This module implements the local-filesystem state variant; the
Apify key-value-store variant lives in main.py.

State note: we persist full ChunkRecords (a superset of the "prior-run chunk
hashes" §6 calls for) so that *removed* chunks can be reported with their
content, not just an id.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .schema import ChangedChunk, ChangeSet, ChangeSummary, ChunkRecord


def utc_now() -> str:
    """ISO 8601 UTC timestamp for run_at."""
    return datetime.now(timezone.utc).isoformat()


def diff_chunks(
    prev_chunks: list[ChunkRecord] | None,
    current_chunks: list[ChunkRecord],
    *,
    start_url: str,
    run_at: str,
    prev_run_at: str | None = None,
) -> ChangeSet:
    """Return the ChangeSet between a previous and current run.

    Keyed on ``chunk_id``; a chunk is *modified* when its id persists but the
    ``chunk_hash`` differs. First run (``prev_chunks`` None/empty) => all added.
    """
    prev = {c.chunk_id: c for c in (prev_chunks or [])}
    cur = {c.chunk_id: c for c in current_chunks}

    changed: list[ChangedChunk] = []
    added = modified = removed = 0

    # Current order is deterministic (page order, then chunk order within page).
    for cid, c in cur.items():
        if cid not in prev:
            changed.append(_as_change("added", c))
            added += 1
        elif prev[cid].chunk_hash != c.chunk_hash:
            changed.append(_as_change("modified", c))
            modified += 1

    for cid, c in prev.items():
        if cid not in cur:
            changed.append(_as_change("removed", c))
            removed += 1

    return ChangeSet(
        run_at=run_at,
        prev_run_at=prev_run_at,
        start_url=start_url,
        summary=ChangeSummary(added=added, modified=modified, removed=removed),
        changed_chunks=changed,
    )


def _as_change(change_type: str, c: ChunkRecord) -> ChangedChunk:
    return ChangedChunk(
        change_type=change_type,
        chunk_id=c.chunk_id,
        url=c.url,
        heading_path=c.heading_path,
        text=c.text,
        chunk_hash=c.chunk_hash,
    )


# --- local-filesystem state (the OSS/CLI variant; Apify uses its KV store) ---

def _state_file(start_url: str, state_dir: str | Path) -> Path:
    key = hashlib.sha256(start_url.encode("utf-8")).hexdigest()[:16]
    return Path(state_dir) / f"{key}.json"


def load_prev_state(
    start_url: str, state_dir: str | Path
) -> tuple[list[ChunkRecord] | None, str | None]:
    """Return ``(prev_chunks, prev_run_at)`` for start_url, or ``(None, None)``."""
    path = _state_file(start_url, state_dir)
    if not path.exists():
        return None, None
    data = json.loads(path.read_text(encoding="utf-8"))
    chunks = [ChunkRecord(**d) for d in data.get("chunks", [])]
    return chunks, data.get("run_at")


def save_state(
    start_url: str, chunks: list[ChunkRecord], state_dir: str | Path, run_at: str
) -> None:
    """Persist this run's chunks as the baseline for the next diff."""
    path = _state_file(start_url, state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "start_url": start_url,
        "run_at": run_at,
        "chunks": [c.model_dump() for c in chunks],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
