# Dependency Management

This project uses a simple layered `requirements/` structure.

## Daily Development

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements/dev.txt
```

## Production / CI

```bash
pip install -r requirements/base.txt
```

## How to (Re)generate Pinned Requirements

After you have a clean virtualenv and have installed everything you need:

```bash
pip freeze > requirements/base.txt
# Then manually move dev-only packages (debug-toolbar, ruff, pytest, etc.)
# into requirements/dev.txt and remove them from base.txt.
```

## Current Policy (2026)

- We pin major versions in `base.txt` for stability.
- Full pins (`pip freeze`) are regenerated when dependencies are intentionally updated.
- We prefer `psycopg[binary]` for painless PostgreSQL on all platforms (including Windows).

## Adding a New Package

1. Add it to the appropriate file (`base.txt` or `dev.txt`).
2. Run `pip install -r requirements/dev.txt`.
3. Test that the app still runs and relevant tests pass.
4. (Optional) Regenerate the full freeze if you want exact pins for CI reproducibility.
