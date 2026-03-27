# Lily Daily Newsletter

Daily newsletter generation scripts for LilyBot.

## Scripts

- `lily-daily-newsletter.py` — Main newsletter generator (v2)
- `run-newsletter.sh` — Wrapper to run with the newsletter venv
- `test_bart_integration.py` — BART real-time departure tester

## Running

```bash
./run-newsletter.sh
```

Requires the virtualenv at `~/.openclaw/workspace/newsletter-venv/` and API keys in `~/.openclaw/workspace/.env`.
