"""run_real_sites.py — PRD §8 v1 acceptance harness (the 10-real-sites run).

Crawls each named public docs site and reports the share of fetched pages that
produce non-empty clean markdown. Exits non-zero if the overall rate < 90%.

It also flags sites whose yield is low (default < 50%): a near-empty result on
a real docs site is the concrete signal that the page is JavaScript-rendered,
which is exactly when the deferred Playwright fallback (PRD §11) becomes worth
building.

Run OUTSIDE a network-restricted sandbox:

    python scripts/run_real_sites.py                 # default site list
    python scripts/run_real_sites.py --max-pages 30
    python scripts/run_real_sites.py --json          # machine-readable output

Not a pytest: it hits the live network and is not deterministic.
"""

from __future__ import annotations

import argparse
import json
import sys

# Add src/ for direct `python scripts/...` execution without install.
sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0] + "/src")

from deltadocs.crawler import crawl  # noqa: E402
from deltadocs.extract import extract_page  # noqa: E402

SITES = [
    "https://fastapi.tiangolo.com/",
    "https://docs.stripe.com/",
    "https://tailwindcss.com/docs/installation",
    "https://docs.apify.com/",
    "https://react.dev/learn",
    "https://docs.pydantic.dev/latest/",
    "https://docs.python.org/3/",
    "https://flask.palletsprojects.com/en/stable/",
    "https://docs.djangoproject.com/en/stable/",
    "https://docs.github.com/en",
]

JS_YIELD_THRESHOLD = 0.50   # below this (with pages fetched) => likely JS-rendered
PASS_THRESHOLD = 0.90       # overall non-empty rate required to "pass"


def assess(url: str, max_pages: int) -> dict:
    try:
        raws = [r for r in crawl(url, max_pages=max_pages) if r.status == 200]
        nonempty = sum(1 for r in raws if extract_page(r).markdown.strip())
        rate = (nonempty / len(raws)) if raws else 0.0
        return {"site": url, "nonempty": nonempty, "fetched": len(raws), "rate": rate,
                "likely_js": bool(raws) and rate < JS_YIELD_THRESHOLD, "error": None}
    except Exception as e:  # one site failing shouldn't abort the whole run
        return {"site": url, "nonempty": 0, "fetched": 0, "rate": 0.0,
                "likely_js": False, "error": type(e).__name__}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("sites", nargs="*", default=SITES)
    args = ap.parse_args()

    results = [assess(u, args.max_pages) for u in args.sites]
    total_ok = sum(r["nonempty"] for r in results)
    total = sum(r["fetched"] for r in results)
    overall = (total_ok / total) if total else 0.0
    js_candidates = [r["site"] for r in results if r["likely_js"]]
    passed = overall >= PASS_THRESHOLD

    if args.json:
        print(json.dumps({"results": results, "overall_rate": overall,
                          "passed": passed, "js_candidates": js_candidates}, indent=2))
        return 0 if passed else 1

    print(f"{'site':45} {'non-empty/fetched':>18} {'rate':>7}  flag")
    for r in results:
        flag = "ERROR:" + r["error"] if r["error"] else ("JS?" if r["likely_js"] else "")
        cell = f"{r['nonempty']}/{r['fetched']}"
        print(f"{r['site']:45} {cell:>18} {r['rate']*100:6.1f}%  {flag}")
    print(f"\nOVERALL: {total_ok}/{total} = {overall*100:.1f}%  "
          f"({'PASS' if passed else 'FAIL'} @ {PASS_THRESHOLD*100:.0f}%)")
    if js_candidates:
        print("Likely JS-rendered (static fetch insufficient -> Playwright candidates):")
        for s in js_candidates:
            print(f"  - {s}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
