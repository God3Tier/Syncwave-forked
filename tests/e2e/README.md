# Browser end-to-end tests

`test_app.py` uses Python Playwright against a running full stack. It covers:

1. Discover, Search, song details, media playback and processed assets.
2. A real browser upload followed through to Catalogue `READY`.
3. Account gates for upload and Jam hosting, plus sign-up, login/logout, and playlist creation.
4. A signed-in host and account-free guest joining the same Jam.
5. Desktop, tablet, and mobile layouts, screenshots, overflow and browser errors.

Run locally after `docker compose up -d --build --wait`:

```powershell
python -m pip install playwright
python -m playwright install chromium
python tests/e2e/test_app.py
```

Screenshots are written to `tests/e2e/artifacts/`. The test is intentionally
not wired into `run.sh` yet: the current `docker:29-cli` integration runner has
no browser runtime. CI should use a pinned Playwright image or a separate
browser job instead of downloading Chromium during every integration job.
