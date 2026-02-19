---
name: playwright
description: Run real-browser automation from this repository via Playwright CLI. Use when chat needs to open pages, click/type in browser UIs, capture snapshots/screenshots, or debug UI flows from the dashboard by executing `/skill run playwright ...`.
---

# Playwright (Repo Wrapper)

Use `scripts/run.py` as a thin wrapper around Playwright CLI.

## Quick Start

```powershell
# 1) Environment check
python skills/playwright/scripts/run.py --self-check

# 2) Open dashboard in a real browser
python skills/playwright/scripts/run.py open http://127.0.0.1:8765 --headed

# 3) Take a snapshot
python skills/playwright/scripts/run.py snapshot
```

## Chat Usage

```text
/skill run playwright --self-check
/skill run playwright open http://127.0.0.1:8765/errors?tab=ai-skills --headed
/skill run playwright snapshot
```

## Notes

- Requires `npx` on PATH.
- If `PLAYWRIGHT_CLI_SESSION` is set, the wrapper injects `--session` automatically unless already provided.
- Wrapper options: `--self-check`, `--timeout-seconds`, `--session`, `--cwd`.
