---
name: lolipop-admin-ops
description: Execute LoLipop admin UI operations as repeatable UI playbooks. Includes dry-run first, and apply mode for real changes.
---
# lolipop admin ops

This skill executes LoLipop admin tasks through JSON playbooks so the same steps are reproducible.

## Safe-guard rules
- `--dry-run` is default and should be used before any write operations.
- `--apply` triggers `run-playbook` and executes mutating steps.
- `--allow-production` is required for write operations on production environment.
- `--action validate` runs read-only checks.

## Requirements
- Prepare AX dirs
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets init
```
- Install Playwright browser
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 playwright install --browser chromium
```
- Save login session (recommended)
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 playwright login --name lolipop --url "https://secure.lolipop.jp/"
```
  - Default session path: `C:\Users\<user>\.ax\sessions\lolipop.storage.json`
- If session file is unavailable, the command can fall back to `LOLIPOP_USERNAME` and `LOLIPOP_PASSWORD` secrets, but this is secondary to session-based execution.

## Run
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service lolipop -- `
  python skills/lolipop-admin-ops/scripts/run.py --domain example.lolipop.jp --playbook .\skills\lolipop-admin-ops\playbooks\ssl_renewal.json --dry-run
```
- Check dry-run output and screenshots.
- Then run with `--apply`.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service lolipop -- `
  python skills/lolipop-admin-ops/scripts/run.py --domain example.lolipop.jp --playbook .\skills\lolipop-admin-ops\playbooks\ssl_renewal.json --apply --allow-production
```

## Parameters
- `--domain` target domain (required)
- `--base-url` admin base URL (default: `https://secure.lolipop.jp`)
- `--environment` `production` or `staging`
- `--playbook` path to playbook JSON
- `--action` `validate` or `run-playbook`
- `--dry-run` read-only plan mode
- `--apply` execute writes (requires allow-production on production)
- `--allow-production` explicit approval for production
- `--session-name` storage_state name (default `lolipop`)
- `--storage-state` explicit storage_state path

## Playbook files
- `playbooks/ssl_renewal.json`
- `playbooks/php_version_change.json`
- `playbooks/cron_check.json`

### SSL renewal
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service lolipop -- `
  python skills/lolipop-admin-ops/scripts/run.py --environment staging --domain example.lolipop.jp --playbook .\skills\lolipop-admin-ops\playbooks\ssl_renewal.json --dry-run
```

### PHP version
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service lolipop -- `
  python skills/lolipop-admin-ops/scripts/run.py --environment staging --domain example.lolipop.jp --playbook .\skills\lolipop-admin-ops\playbooks\php_version_change.json --dry-run
```

### Cron check
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service lolipop -- `
  python skills/lolipop-admin-ops/scripts/run.py --environment production --domain example.lolipop.jp --playbook .\skills\lolipop-admin-ops\playbooks\cron_check.json --dry-run
```

## Result JSON
- `status`: `success` or `error`
- `data`: execution context and step results
- `error`: type/message if failed

No credentials are emitted in output.
