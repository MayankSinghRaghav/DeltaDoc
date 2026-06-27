# Publishing & Testing DeltaDocs

Three things you'll do: **(A) test on your laptop**, **(B) publish to GitHub**, **(C) publish to Apify**. Commands shown for **Windows PowerShell** (macOS/Linux notes inline).

> ### Step 0 — clean up sandbox artifacts first
> The build environment left a few files it couldn't delete (its mount blocks deletion). On your laptop, normal permissions apply — remove them before anything else:
> ```powershell
> cd C:\Users\mayan\Desktop\Projects\DeltaDocs
> rmdir /s /q .git           # broken repo created in the sandbox; you'll re-init below
> rmdir /s /q storage        # local Apify run artifacts
> del _probe*.txt
> ```
> (macOS/Linux: `rm -rf .git storage _probe*.txt`)

---

## A. Test on your laptop

**Prerequisites:** Python 3.10+ (`python --version`).

```powershell
cd C:\Users\mayan\Desktop\Projects\DeltaDocs
python -m venv .venv
.venv\Scripts\activate                # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"               # installs deltadocs + pytest + jsonschema
```

**1. Run the test suite** (deterministic, offline — should be 30 passed):
```powershell
pytest -q
```

**2. Run it for real (OSS CLI)** against a live docs site:
```powershell
deltadocs https://docs.python.org/3/ --max-pages 20 -o out
```
Look in `out\`: `pages.jsonl`, `chunks.jsonl`, `llms.txt`, `llms-full.txt`.

**3. See the v2 delta engine** — run twice with a state dir; the 2nd run writes `out\changeset.json`:
```powershell
deltadocs https://docs.python.org/3/ --max-pages 20 --state-dir .state -o out   # run 1: all added
deltadocs https://docs.python.org/3/ --max-pages 20 --state-dir .state -o out   # run 2: only changes
```

---

## B. Publish to GitHub

```powershell
cd C:\Users\mayan\Desktop\Projects\DeltaDocs
git init
git add .
git commit -m "DeltaDocs v0.2.0 — one-shot extractor + delta engine"
```

Then create the remote. Easiest with the GitHub CLI (`winget install GitHub.cli`, then `gh auth login`):
```powershell
gh repo create deltadocs --public --source=. --remote=origin --push
```
Or via the website: create an empty repo at github.com → then:
```powershell
git remote add origin https://github.com/<your-username>/deltadocs.git
git branch -M main
git push -u origin main
```
`.gitignore` already excludes `.venv/`, `storage/`, caches, etc. **Add a `LICENSE`** before sharing (MIT is conventional — GitHub's "Add file → Create new file → LICENSE" offers a template).

---

## C. Publish to Apify

The repo is already Actor-ready: `.actor/actor.json`, `.actor/input_schema.json`, `Dockerfile`, and the entry `python -m deltadocs`.

**1. Install the Apify CLI** (needs Node.js):
```powershell
npm install -g apify-cli
```
(macOS/Linux alternative: `curl -fsSL https://apify.com/install-cli.sh | bash`)

**2. Log in** (grab your token from Apify Console → Settings → Integrations):
```powershell
apify login
```

**3. Test the Actor locally.** Provide input, then run — `apify run` reads input from `storage\key_value_stores\default\INPUT.json`:
```powershell
mkdir storage\key_value_stores\default
'{ "start_url": "https://docs.python.org/3/", "max_pages": 20 }' | Out-File -Encoding utf8 storage\key_value_stores\default\INPUT.json
pip install -e .          # so `python -m deltadocs` resolves in the venv
apify run
```
Output lands in `storage\datasets\default\` (the changed chunks) and `storage\key_value_stores\default\` (`changeset`, `llms.txt`, etc.).

**4. Deploy to the cloud:**
```powershell
apify push
```
This uploads the source, builds the Docker image, and creates the Actor in your Apify Console.

**5. Publish to the Store + monetize.** In the Apify Console on your Actor:
- Set it **Public**, add the README (this repo's `README.md`) and the SEO title/description (drafts are in `llms.txt`).
- Under **Monetization**, choose **Pay-per-event** and price the events the code already emits: `actor-start` and `changed-chunk`. (PPE is the model that matches "charge for what changed" — and gets priority Store placement.)
- Click **Publish**.

> The full official flow (Development → Publication/monetization → Testing → Promotion) is at docs.apify.com/platform/actors/publishing.

---

## Quick reference

| Goal | Command |
|---|---|
| Run tests | `pytest -q` |
| One-shot crawl | `deltadocs <url> -o out` |
| Crawl + diff | `deltadocs <url> --state-dir .state -o out` |
| Test Actor locally | `apify run` |
| Deploy Actor | `apify push` |
| 10-site acceptance | `python scripts/run_real_sites.py --max-pages 30` |
