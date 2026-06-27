"""test_deliver.py — v3 delivery (PRD §10 agent #8).

Offline: an in-memory VectorStore stands in for Chroma; MockTransport stands
in for the webhook endpoint. No chromadb / network required.
"""

from __future__ import annotations

import httpx

from deltadocs.deliver import apply_changeset, post_webhook
from deltadocs.schema import ChangedChunk, ChangeSet, ChangeSummary


class _MemStore:
    def __init__(self):
        self.docs: dict[str, tuple[str, dict]] = {}

    def upsert(self, ids, documents, metadatas):
        for i, d, m in zip(ids, documents, metadatas):
            self.docs[i] = (d, m)

    def delete(self, ids):
        for i in ids:
            self.docs.pop(i, None)


def _cc(change_type, cid, text="t"):
    return ChangedChunk(change_type=change_type, chunk_id=cid, url=f"https://x/{cid}",
                        heading_path=["H", "Sub"], text=text, chunk_hash="sha256:" + "0" * 64)


def _changeset():
    chunks = [_cc("added", "new"), _cc("modified", "upd"), _cc("removed", "gone")]
    return ChangeSet(run_at="t1", prev_run_at="t0", start_url="https://x",
                     summary=ChangeSummary(added=1, modified=1, removed=1), changed_chunks=chunks)


def test_apply_changeset_upserts_and_deletes():
    store = _MemStore()
    store.docs["gone"] = ("old", {})   # exists before; should be deleted
    store.docs["upd"] = ("old", {})    # exists before; should be overwritten
    counts = apply_changeset(_changeset(), store)
    assert counts == {"upserted": 2, "deleted": 1}
    assert set(store.docs) == {"new", "upd"}          # gone deleted, new added
    assert store.docs["upd"][0] == "t"                # modified overwrote old
    # metadata flattened to scalars (Chroma-safe)
    assert store.docs["new"][1]["heading_path"] == "H > Sub"
    assert isinstance(store.docs["new"][1]["chunk_hash"], str)


def test_apply_changeset_empty_is_noop():
    store = _MemStore()
    empty = ChangeSet(run_at="t1", prev_run_at="t0", start_url="https://x",
                      summary=ChangeSummary(added=0, modified=0, removed=0), changed_chunks=[])
    assert apply_changeset(empty, store) == {"upserted": 0, "deleted": 0}
    assert store.docs == {}


def test_post_webhook_sends_slack_compatible_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    code = post_webhook(_changeset(), "https://hooks.example.com/abc", client=client)
    assert code == 200
    assert captured["url"] == "https://hooks.example.com/abc"
    assert "text" in captured["body"]
    assert "+1" in captured["body"]["text"] and "-1" in captured["body"]["text"]


from deltadocs.deliver import PgVectorStore, PineconeVectorStore  # noqa: E402


def _embed(texts):
    return [[float(len(t)), 0.0, 1.0] for t in texts]


class _FakeCursor:
    def __init__(self, log):
        self._log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._log.append((sql, params))


class _FakeConn:
    def __init__(self):
        self.log = []
        self.commits = 0

    def cursor(self):
        return _FakeCursor(self.log)

    def commit(self):
        self.commits += 1


def test_pgvector_adapter_upsert_and_delete():
    conn = _FakeConn()
    apply_changeset(_changeset(), PgVectorStore(conn, _embed))
    sqls = [s for s, _ in conn.log]
    assert any("INSERT INTO deltadocs" in s and "ON CONFLICT" in s for s in sqls)
    assert any("DELETE FROM deltadocs" in s for s in sqls)
    inserts = [p for s, p in conn.log if "INSERT" in s]
    assert len(inserts) == 2  # added + modified
    assert conn.commits >= 1


class _FakeIndex:
    def __init__(self):
        self.upserts = []
        self.deletes = []

    def upsert(self, vectors, namespace=None):
        self.upserts.append((vectors, namespace))

    def delete(self, ids, namespace=None):
        self.deletes.append((ids, namespace))


def test_pinecone_adapter_upsert_and_delete():
    index = _FakeIndex()
    apply_changeset(_changeset(), PineconeVectorStore(index, _embed, namespace="ns"))
    assert len(index.upserts) == 1
    vectors, ns = index.upserts[0]
    assert ns == "ns" and len(vectors) == 2
    assert all("values" in v and v["metadata"]["document"] for v in vectors)
    assert index.deletes and index.deletes[0][0] == ["gone"]
