---
name: kintone
description: "Guidance for Cybozu Kintone automation: application/record model design, REST API integration, and reliable operational workflows."
category: crm, low-code platform, api
dependencies:
  - Kintone app permissions
  - Kintone API token or user auth
  - HTTPS + JSON-capable client
updated: 2026-02-16
---

# Kintone

## What this skill is for

Use this skill when automating data operations in Kintone:

- Managing app schema and field definitions
- Registering/updating records safely
- Querying and exporting records
- Integrating Kintone with external systems
- Implementing operational dashboards and sync jobs with retries/observability

## Core concepts

- **App**: Unit that owns fields, records, views, forms, permissions.
- **Record**: Structured JSON object keyed by field code and record ID.
- **Field code**: Most critical integration key; code mismatches are the highest source of write errors.
- **REST API request scope**: Keep token permissions minimal and scoped to required apps/operations.

## Setup checklist

1. Confirm tenant URL, app ID, and target field codes.
2. Create API token with least privilege.
3. Store secrets in environment variables or secret store (never inline).
4. Define one source-of-truth for:
   - app id
   - field mapping
   - sync cursor / last processed timestamp
5. Dry-run read-only validation before writes.

## API patterns to follow

- Use consistent request timeout and retry policy.
- Log request ID / response status / error payloads.
- For write operations:
  - validate payload before call
  - avoid blind overwrites
  - make runs idempotent when possible
- Paginate reads and checkpoint progress.

## Example (Python)

```python
import requests

BASE = "https://example.cybozu.com"
APP_ID = "123"
TOKEN = "kintone_api_token_here"

headers = {
    "X-Cybozu-API-Token": TOKEN,
    "Content-Type": "application/json",
}

resp = requests.get(
    f"{BASE}/k/v1/records.json",
    headers=headers,
    params={"app": APP_ID, "query": "created_time > \"2026-02-01T00:00:00Z\"", "limit": 100},
    timeout=30,
)
resp.raise_for_status()
payload = resp.json()
```

## Troubleshooting

| Symptom | Likely cause | Remediation |
|---|---|---|
| 401 unauthorized | Invalid/expired token | Rotate token and verify token scope |
| 403 forbidden | Permissions mismatch | Re-check app roles and token restrictions |
| 400 bad request | Schema mismatch | Verify field codes and expected value shapes |
| 429 rate limit | Too many concurrent calls | Add backoff + jitter and reduce parallelism |
| 500-level API error | transient service issue | retry with bounded attempts |

## Operational validation

- Read one known record and one filtered query before running writes.
- Validate all required fields exist in destination app.
- Check response counts against expected `limit`/`offset`.
- Keep an audit log with:
  - run start/end time
  - app id
  - affected record count
  - request errors and retry count

## References

- `references/official_sources.md` for official Kintone documentation and API references.
- Use this skill when writing any integration script that touches kintone data.
