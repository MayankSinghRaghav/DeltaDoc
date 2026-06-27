"""test_diff.py — QA for the v2 delta engine (PRD §8 v2 acceptance).

Covers:
  * Golden-file diff: exactly N changes, zero false positives / negatives.
  * First run (no prior state) => every chunk is "added".
  * Local state round-trip (save -> load), the OSS analog of the KV read/write.
  * End-to-end: two fixture sites differing by known edits map to the right
    added / modified / removed sets; an unchanged page contributes nothing.
"""

from __future__ import annotations

import httpx

from deltadocs.diff import diff_chunks, load_prev_state, save_state
from deltadocs.pipeline import run_pipeline
from deltadocs.schema import ChunkRecord


def _chunk(cid: str, h: str, text: str) -> ChunkRecord:
    return ChunkRecord(chunk_id=cid, url=f"https://x/{cid}", heading_path=["D"],
                       text=text, token_estimate=1, chunk_hash="sha256:" + (h * 64)[:64], order=0)


def test_golden_diff_exactly_n_zero_false_pos_neg():
    prev = [_chunk("a", "1", "A"), _chunk("b", "2", "B"), _chunk("c", "3", "C")]
    # known edits: b modified, c removed, d added; a unchanged
    cur = [_chunk("a", "1", "A"), _chunk("b", "9", "B2"), _chunk("d", "4", "D")]
    cs = diff_chunks(prev, cur, start_url="https://x", run_at="t1", prev_run_at="t0")
    assert cs.summary.model_dump() == {"added": 1, "modified": 1, "removed": 1}
    assert {(c.change_type, c.chunk_id) for c in cs.changed_chunks} == {
        ("added", "d"), ("modified", "b"), ("removed", "c")}
    # zero false positives: unchanged "a" never appears
    assert all(c.chunk_id != "a" for c in cs.changed_chunks)
    assert len(cs.changed_chunks) == 3


def test_first_run_all_added():
    cur = [_chunk("a", "1", "A"), _chunk("b", "2", "B")]
    cs = diff_chunks(None, cur, start_url="https://x", run_at="t1")
    assert cs.prev_run_at is None
    assert cs.summary.model_dump() == {"added": 2, "modified": 0, "removed": 0}
    assert {c.change_type for c in cs.changed_chunks} == {"added"}


def test_state_round_trip(tmp_path):
    chunks = [_chunk("a", "1", "A"), _chunk("b", "2", "B")]
    save_state("https://docs.example.com", chunks, tmp_path, "t0")
    prev, prev_run_at = load_prev_state("https://docs.example.com", tmp_path)
    assert prev_run_at == "t0"
    assert [c.model_dump() for c in prev] == [c.model_dump() for c in chunks]
    # unknown url => no state
    none, ts = load_prev_state("https://other", tmp_path)
    assert none is None and ts is None


# --- end-to-end: two fixture sites differing by known edits ---
# Discovery links live in <nav> (stripped from extracted markdown), so changing
# the nav between runs does NOT alter a page's content hash — only real body
# edits do. The home page body is identical across runs => no spurious change.

_HOME = (
    "<article><h1>Home</h1><p>This is the stable home page of the fixture "
    "documentation site. Its body text is intentionally identical across both "
    "runs so that it produces no change at all in the diff.</p></article>"
)
_V1 = {
    "/": f"<html><head><title>Home</title></head><body><nav><a href='/guide'>Guide</a> <a href='/api'>API</a></nav>{_HOME}<footer>foot</footer></body></html>",
    "/guide": "<html><head><title>Guide</title></head><body><article><h1>Guide</h1><p>Original guide body paragraph with enough descriptive words for clean extraction.</p></article></body></html>",
    "/api": "<html><head><title>API</title></head><body><article><h1>API</h1><p>This API page exists only in the first run and is removed in the second run.</p></article></body></html>",
}
_V2 = {
    "/": f"<html><head><title>Home</title></head><body><nav><a href='/guide'>Guide</a> <a href='/faq'>FAQ</a></nav>{_HOME}<footer>foot</footer></body></html>",
    "/guide": "<html><head><title>Guide</title></head><body><article><h1>Guide</h1><p>REWRITTEN guide body paragraph with substantially different words so the hash changes.</p></article></body></html>",
    "/faq": "<html><head><title>FAQ</title></head><body><article><h1>FAQ</h1><p>A brand new FAQ page added in the second run with sufficient prose to be kept.</p></article></body></html>",
}


def _client_for(site: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/robots.txt", "/sitemap.xml"):
            return httpx.Response(404, text="")
        html = site.get(request.url.path)
        return httpx.Response(200, text=html) if html else httpx.Response(404, text="")
    return lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_end_to_end_diff_reflects_real_edits():
    base = "https://docs.example.com/"
    _, c1 = run_pipeline(base, _client=_client_for(_V1)())
    _, c2 = run_pipeline(base, _client=_client_for(_V2)())
    cs = diff_chunks(c1, c2, start_url=base, run_at="t1", prev_run_at="t0")

    def urls(t):
        return {c.url for c in cs.changed_chunks if c.change_type == t}

    assert urls("added") == {"https://docs.example.com/faq"}
    assert urls("removed") == {"https://docs.example.com/api"}
    assert urls("modified") == {"https://docs.example.com/guide"}
    # unchanged home appears in no bucket (zero false positive)
    assert all(c.url != "https://docs.example.com/" for c in cs.changed_chunks)
    # every reported change is real
    h1 = {c.chunk_id: c.chunk_hash for c in c1}
    h2 = {c.chunk_id: c.chunk_hash for c in c2}
    for c in cs.changed_chunks:
        if c.change_type == "modified":
            assert h1[c.chunk_id] != h2[c.chunk_id]
        elif c.change_type == "added":
            assert c.chunk_id not in h1 and c.chunk_id in h2
        elif c.change_type == "removed":
            assert c.chunk_id in h1 and c.chunk_id not in h2


def test_unchanged_rerun_zero_changes_end_to_end():
    base = "https://docs.example.com/"
    _, c1 = run_pipeline(base, _client=_client_for(_V1)())
    _, c2 = run_pipeline(base, _client=_client_for(_V1)())
    cs = diff_chunks(c1, c2, start_url=base, run_at="t1", prev_run_at="t0")
    assert cs.summary.model_dump() == {"added": 0, "modified": 0, "removed": 0}
    assert cs.changed_chunks == []
