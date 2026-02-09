from __future__ import annotations

from pathlib import Path

import pytest

import provider_download_orchestrator as orchestrator


def test_run_provider_downloads_initializes_missing_storage_states(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []

    def _fake_node_runner(*, script_path: Path, cwd: Path, args: list[str]) -> dict[str, object]:
        calls.append({"script_path": script_path, "cwd": cwd, "args": list(args)})
        return {
            "status": "success",
            "data": {
                "downloaded_count": 0,
                "candidates_found": 0,
                "downloaded_files": [],
                "visited_urls": [],
                "final_url": "https://example.invalid/billing",
            },
        }

    def _fake_import(
        output_root: Path,
        year: int,
        month: int,
        *,
        provider_filter: set[str] | None = None,
        ingestion_channel: str = "",
    ) -> dict[str, object]:
        return {
            "found_files": 0,
            "found_pdfs": 0,
            "imported": 0,
            "imported_missing_amount": 0,
            "skipped_duplicates": 0,
            "failed": 0,
            "provider_counts": {},
            "orders_jsonl": str(output_root / "manual" / "orders.jsonl"),
            "provider_report_json": str(output_root / "manual" / "reports" / "provider_import_last.json"),
            "report_json": str(output_root / "manual" / "reports" / "manual_import_last.json"),
        }

    monkeypatch.setattr(orchestrator, "run_node_playwright_script", _fake_node_runner)
    monkeypatch.setattr(orchestrator, "import_manual_receipts_for_month", _fake_import)

    output_root = tmp_path / "artifacts" / "2026-01"
    out_json = output_root / "reports" / "provider_download_result.json"
    storage_states = {
        provider: tmp_path / "sessions" / f"{provider}.storage.json"
        for provider in orchestrator.PROVIDER_ORDER
    }

    payload = orchestrator.run_provider_downloads(
        year=2026,
        month=1,
        output_root=output_root,
        out_json=out_json,
        storage_states=storage_states,
        auth_handoff=True,
        headed=True,
        slow_mo_ms=0,
    )

    assert payload["status"] == "success"
    assert out_json.exists()
    assert len(calls) == len(orchestrator.PROVIDER_ORDER)

    for provider in orchestrator.PROVIDER_ORDER:
        state_path = storage_states[provider]
        assert state_path.exists()
        entry = payload["data"]["providers"][provider]
        assert entry["status"] == "success"
        assert entry["storage_state_initialized"] is True

