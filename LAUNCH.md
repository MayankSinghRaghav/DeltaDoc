# DeltaDocs — launch post (draft)

**One-liner:** Turn any documentation site into clean, chunked, hash-stamped, LLM-ready output — the foundation for keeping a RAG index fresh by re-embedding only what changed.

If you run a RAG chatbot over someone else's docs, you've hit the trade-off: re-embed the whole site nightly (you pay for embeddings that scale with total pages, even though almost nothing changed) or let the index go stale (your bot confidently returns a deprecated API signature). Great one-shot tools already turn a URL into clean markdown — but none of them does cheap, scheduled **diffing**.

DeltaDocs v1 is the groundwork: crawl a docs site, extract main content to markdown, split into heading-aware chunks, and stamp each chunk with a SHA-256 over *normalized* text. Because the hash ignores trivial reformatting (whitespace, blank lines), an unchanged page hashes identically across runs — which is exactly what the v2 delta engine will use to emit only the chunks that actually changed.

Ships today as an OSS Python CLI and an Apify Actor, with `llms.txt` / `llms-full.txt` output.

Honest note: the "re-embed 100 chunks instead of 5,000" framing is illustrative — actual savings depend on your site's churn. v1 ships the hashes that make it measurable; v2 ships the deltas.

Feedback welcome, especially on chunk-boundary rules and normalization edge cases.
