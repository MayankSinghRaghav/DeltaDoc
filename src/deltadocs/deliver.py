"""deliver.py — Delivery Agent (PRD §10, agent #8): push deltas downstream.

Two thin, dependency-light delivery paths over a ChangeSet:
  * ``apply_changeset`` — upsert added/modified chunks and delete removed ones
    from any vector store implementing the small ``VectorStore`` protocol. A
    Chroma adapter is provided (chromadb is an OPTIONAL dependency, imported
    lazily so tests and non-Chroma users don't need it).
  * ``post_webhook`` — POST a compact change summary to a webhook URL
    (Slack-compatible via the ``text`` field).

This is the v2->RAG loop payoff: re-embed/index ONLY what changed.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from .schema import ChangeSet


class VectorStore(Protocol):
    """Minimal sink: upsert documents by id, delete by id."""

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict]) -> None: ...
    def delete(self, ids: list[str]) -> None: ...


def apply_changeset(changeset: ChangeSet, store: VectorStore) -> dict[str, int]:
    """Apply a ChangeSet to a vector store.

    added/modified -> upsert (so only changed chunks get re-embedded);
    removed -> delete. Returns ``{"upserted": n, "deleted": m}``.
    """
    up_ids: list[str] = []
    up_docs: list[str] = []
    up_meta: list[dict] = []
    del_ids: list[str] = []

    for c in changeset.changed_chunks:
        if c.change_type in ("added", "modified"):
            up_ids.append(c.chunk_id)
            up_docs.append(c.text)
            # Chroma metadata values must be scalars -> flatten heading_path.
            up_meta.append({
                "url": c.url,
                "heading_path": " > ".join(c.heading_path),
                "chunk_hash": c.chunk_hash,
            })
        elif c.change_type == "removed":
            del_ids.append(c.chunk_id)

    if up_ids:
        store.upsert(up_ids, up_docs, up_meta)
    if del_ids:
        store.delete(del_ids)
    return {"upserted": len(up_ids), "deleted": len(del_ids)}


class ChromaVectorStore:
    """Adapter wrapping a Chroma collection. Optional dep: ``pip install chromadb``."""

    def __init__(self, collection) -> None:
        self._c = collection

    def upsert(self, ids, documents, metadatas) -> None:
        self._c.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def delete(self, ids) -> None:
        self._c.delete(ids=ids)


def open_chroma_collection(path: str, name: str = "deltadocs", embedding_function=None) -> ChromaVectorStore:
    """Open/create a persistent Chroma collection and wrap it (lazy chromadb import)."""
    import chromadb

    client = chromadb.PersistentClient(path=path)
    collection = client.get_or_create_collection(name=name, embedding_function=embedding_function)
    return ChromaVectorStore(collection)


def post_webhook(changeset: ChangeSet, webhook_url: str, *, client: httpx.Client | None = None) -> int:
    """POST a compact summary to a webhook (Slack-compatible ``text`` payload).

    ``client`` is injectable for offline testing. Returns the HTTP status code.
    """
    _client = client or httpx.Client(timeout=15)
    s = changeset.summary
    text = (f"DeltaDocs — {changeset.start_url}: "
            f"+{s.added} added, ~{s.modified} modified, -{s.removed} removed")
    resp = _client.post(webhook_url, json={"text": text})
    return resp.status_code


class PgVectorStore:
    """pgvector adapter (optional: ``pip install ".[pgvector]"``).

    Needs an open psycopg connection with pgvector registered and a table::

        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE TABLE deltadocs (chunk_id text PRIMARY KEY, document text,
                                metadata jsonb, embedding vector(<dim>));
        # after connecting: pgvector.psycopg.register_vector(conn)

    ``embed`` maps a list of texts -> list of vectors (you choose the model).
    """

    def __init__(self, conn, embed, table: str = "deltadocs") -> None:
        self._conn = conn
        self._embed = embed
        self._table = table

    def upsert(self, ids, documents, metadatas) -> None:
        import json

        vectors = self._embed(documents)
        sql = (
            f"INSERT INTO {self._table} (chunk_id, document, metadata, embedding) "
            "VALUES (%s, %s, %s::jsonb, %s) "
            "ON CONFLICT (chunk_id) DO UPDATE SET "
            "document = EXCLUDED.document, metadata = EXCLUDED.metadata, "
            "embedding = EXCLUDED.embedding"
        )
        with self._conn.cursor() as cur:
            for cid, doc, meta, vec in zip(ids, documents, metadatas, vectors):
                cur.execute(sql, (cid, doc, json.dumps(meta), vec))
        self._conn.commit()

    def delete(self, ids) -> None:
        with self._conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self._table} WHERE chunk_id = ANY(%s)", (list(ids),))
        self._conn.commit()


class PineconeVectorStore:
    """Pinecone adapter (optional: ``pip install ".[pinecone]"``).

    Wrap an existing Pinecone index. ``embed`` maps texts -> vectors; the chunk
    text is kept in metadata under ``document``.
    """

    def __init__(self, index, embed, namespace: str | None = None) -> None:
        self._index = index
        self._embed = embed
        self._ns = namespace

    def upsert(self, ids, documents, metadatas) -> None:
        vectors = self._embed(documents)
        items = [
            {"id": cid, "values": vec, "metadata": {**meta, "document": doc}}
            for cid, doc, meta, vec in zip(ids, documents, metadatas, vectors)
        ]
        self._index.upsert(vectors=items, namespace=self._ns)

    def delete(self, ids) -> None:
        self._index.delete(ids=list(ids), namespace=self._ns)
