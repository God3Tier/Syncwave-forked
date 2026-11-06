# Browser end-to-end tests

`test_app.py` uses Python Playwright against a running full stack. It covers:

1. Discover, Search, song details, media playback and processed assets.
2. A real browser upload followed through to Catalogue `READY`.
3. Account gates for upload and Jam hosting, plus sign-up, login/logout, and playlist creation.
4. A signed-in host and account-free guest joining the same Jam by invite link and 8-digit code.
5. A guest leaving active playback, rejoining, enabling audio and catching up again.
6. Desktop, tablet, and mobile layouts, screenshots, overflow and browser errors.

Run locally after `docker compose up -d --build --wait`:

```powershell
python -m pip install playwright
python -m playwright install chromium
python tests/e2e/test_app.py
```

Screenshots are written to `tests/e2e/artifacts/`. On staging, `run.sh` launches
a pinned Playwright container on the Compose network, installs the matching
Python binding inside it, and runs the same journey against the gateway without
installing a browser into the Docker CLI runner.
