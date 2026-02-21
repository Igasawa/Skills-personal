# Shared Config Runbook

更新日: 2026-02-20  
対象: `AX_HOME/configs/org-profile.json` の展開と運用

## 0. Prerequisites

- Python 3.11+
- `jsonschema` package (required by `scripts/validate_org_profile.py`)

Install example:

```bash
python -m pip install jsonschema
```

## 1. Purpose

Use one shared config profile for common organization values (company name, receipt display name, common URLs) across multiple skills.

## 2. Rules

- Do not store secrets (passwords, tokens, API keys) in `org-profile.json`.
- Keep skill-specific values in each skill config when they are not shared.
- Resolution priority must stay: `CLI > skill config > org-profile > defaults`.

## 3. Initial Setup

### Step A: Prepare file

PowerShell:

```powershell
$env:AX_HOME = "$env:USERPROFILE\.ax"
New-Item -ItemType Directory -Force -Path "$env:AX_HOME\configs" | Out-Null
Copy-Item docs/org-profile.template.json "$env:AX_HOME\configs\org-profile.json" -Force
```

Bash:

```bash
export AX_HOME="${AX_HOME:-$HOME/.ax}"
mkdir -p "$AX_HOME/configs"
cp docs/org-profile.template.json "$AX_HOME/configs/org-profile.json"
```

### Step B: Edit required values

Edit:

- `profile_key`
- `organization.name`
- `organization.receipt.name`
- `organization.receipt.name_fallback`
- `urls.*` values used by your team

### Step C: Validate schema and policy

```bash
python scripts/validate_org_profile.py \
  --schema docs/shared-config-schema.json \
  --file "$AX_HOME/configs/org-profile.json"
```

Expected result: `"status": "success"`

## 4. Migration From Existing Skill Config

### Step D1: Dry-run migration

```bash
python scripts/config_migrate.py
```

### Step D2: Apply migration

```bash
python scripts/config_migrate.py --apply
```

### Step D3: Overwrite mode (only when needed)

```bash
python scripts/config_migrate.py --apply --overwrite
```

## 5. Pilot Verification (mfcloud skill)

### Step E1: Unit tests

```bash
python -m pytest -q \
  skills/mfcloud-expense-receipt-reconcile/tests/test_run_core_config.py \
  skills/mfcloud-expense-receipt-reconcile/tests/test_collect_print.py
```

### Step E2: Encoding checks for changed files

```bash
python scripts/check_text_encoding.py --path skills/mfcloud-expense-receipt-reconcile/scripts/run_core.py
python scripts/check_text_encoding.py --path skills/mfcloud-expense-receipt-reconcile/scripts/collect_print.py
```

## 6. Rollout Checklist

- `org-profile.json` exists on each operator machine under `AX_HOME/configs/`.
- Schema validation passes.
- No secrets are in key names or values.
- Pilot skill commands run without relying on placeholder values.
- Deprecation warnings are monitored during transition period.

## 7. Rollback Procedure

### Step F1: Backup before changes

```bash
cp "$AX_HOME/configs/org-profile.json" "$AX_HOME/configs/org-profile.backup.json"
```

### Step F2: Restore if needed

```bash
cp "$AX_HOME/configs/org-profile.backup.json" "$AX_HOME/configs/org-profile.json"
```

### Step F3: Temporary fallback

If rollout issues occur, keep running with existing skill config values while fixing `org-profile.json`.  
Because priority is `skill config > org-profile`, this fallback is non-disruptive.

## 8. Ownership

- Config schema and policy: repository maintainers
- Per-environment `org-profile.json`: management/admin operators
- Migration execution record: team lead or release owner
