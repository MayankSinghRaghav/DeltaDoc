"""cli.py — OSS command-line entry (PRD §2 goal: OSS package/CLI).

Runs the v1 pipeline against a docs URL and writes the dataset + llms files.
With ``--state-dir`` it also runs the v2 delta engine: diff against the prior
run, write ``changeset.json``, and update the stored baseline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .diff import diff_chunks, load_prev_state, save_state, utc_now
from .pipeline import build_llms_full_txt, build_llms_txt, run_pipeline


def _to_jsonl(records) -> str:
    return "".join(json.dumps(r.model_dump()) + "\n" for r in records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deltadocs",
        description="Crawl a docs site into LLM-ready chunks + llms.txt (v1); diff with --state-dir (v2).",
    )
    parser.add_argument("start_url")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--include", action="append", dest="include_globs",
                        help="URL-path glob to include (repeatable), e.g. /docs/*")
    parser.add_argument("--exclude", action="append", dest="exclude_globs",
                        help="URL-path glob to exclude (repeatable), e.g. /blog/*")
    parser.add_argument("--no-robots", action="store_true", help="Do not enforce robots.txt")
    parser.add_argument("--state-dir", help="Enable change tracking: directory holding prior-run "
                                            "state keyed by start_url. Writes changeset.json.")
    parser.add_argument("-o", "--out", default="deltadocs_out")
    args = parser.parse_args(argv)

    pages, chunks = run_pipeline(
        args.start_url,
        max_pages=args.max_pages,
        include_globs=args.include_globs,
        exclude_globs=args.exclude_globs,
        respect_robots_txt=not args.no_robots,
    )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pages.jsonl").write_text(_to_jsonl(pages), encoding="utf-8")
    (out / "chunks.jsonl").write_text(_to_jsonl(chunks), encoding="utf-8")
    (out / "llms.txt").write_text(build_llms_txt(pages, args.start_url), encoding="utf-8")
    (out / "llms-full.txt").write_text(build_llms_full_txt(pages), encoding="utf-8")
    print(f"Wrote {len(pages)} pages, {len(chunks)} chunks to {out}/", file=sys.stderr)

    if args.state_dir:
        prev_chunks, prev_run_at = load_prev_state(args.start_url, args.state_dir)
        run_at = utc_now()
        changeset = diff_chunks(prev_chunks, chunks, start_url=args.start_url,
                                run_at=run_at, prev_run_at=prev_run_at)
        (out / "changeset.json").write_text(
            json.dumps(changeset.model_dump(), indent=2), encoding="utf-8")
        save_state(args.start_url, chunks, args.state_dir, run_at)
        s = changeset.summary
        print(f"ChangeSet: +{s.added} ~{s.modified} -{s.removed} "
              f"({'first run' if prev_run_at is None else 'vs ' + prev_run_at})", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
