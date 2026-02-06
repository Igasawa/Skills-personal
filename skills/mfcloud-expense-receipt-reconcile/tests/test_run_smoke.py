from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_run_py_dry_run_generates_core_outputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts" / "2026-01"
    _write_jsonl(
        output_dir / "amazon" / "orders.jsonl",
        [
            {
                "order_id": "AMZ-SMOKE",
                "order_date": "2026-01-12",
                "total_yen": 980,
                "pdf_path": "amazon/pdfs/AMZ-SMOKE.pdf",
                "source": "amazon",
            }
        ],
    )
    _write_jsonl(
        output_dir / "mfcloud" / "expenses.jsonl",
        [
            {
                "expense_id": "MF-SMOKE",
                "use_date": "2026-01-12",
                "amount_yen": 980,
                "vendor": "Amazon",
                "memo": "テスト",
                "has_evidence": False,
            }
        ],
    )

    cmd = [
        sys.executable,
        "scripts/run.py",
        "--year",
        "2026",
        "--month",
        "1",
        "--dry-run",
        "--skip-amazon",
        "--skip-rakuten",
        "--skip-mfcloud",
        "--output-dir",
        str(output_dir),
    ]
    result = subprocess.run(cmd, cwd=str(SKILL_ROOT), capture_output=True, text=True, check=False)

    assert result.returncode == 0, f"run.py failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    report_json = output_dir / "reports" / "missing_evidence_candidates.json"
    report_csv = output_dir / "reports" / "missing_evidence_candidates.csv"
    quality_gate_json = output_dir / "reports" / "quality_gate.json"
    monthly_thread_md = output_dir / "reports" / "monthly_thread.md"
    resolved_config_json = output_dir / "run_config.resolved.json"

    for path in (report_json, report_csv, quality_gate_json, monthly_thread_md, resolved_config_json):
        assert path.exists(), f"missing output: {path}"

    quality_gate = json.loads(quality_gate_json.read_text(encoding="utf-8"))
    assert quality_gate["status"] == "pass"
    assert quality_gate["ready_for_submission"] is True

    resolved_config = json.loads(resolved_config_json.read_text(encoding="utf-8"))
    tenant = resolved_config.get("tenant") if isinstance(resolved_config.get("tenant"), dict) else {}
    resolved_sources = (
        resolved_config.get("resolved_sources") if isinstance(resolved_config.get("resolved_sources"), dict) else {}
    )
    assert isinstance(tenant.get("urls"), dict)
    assert tenant.get("name")
    assert resolved_sources.get("receipt_name")
    assert resolved_sources.get("amazon_orders_url")
