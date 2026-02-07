from __future__ import annotations

import json
from pathlib import Path
import subprocess


SKILL_ROOT = Path(__file__).resolve().parents[1]
RAKUTEN_MODULE_URL = (SKILL_ROOT / "scripts" / "rakuten_download.mjs").resolve().as_uri()


def _node_json(expr: str) -> dict:
    script = f"""
import * as mod from {json.dumps(RAKUTEN_MODULE_URL)};
const out = {expr};
console.log(JSON.stringify(out));
"""
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=str(SKILL_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"node eval failed\\nstdout:\\n{res.stdout}\\nstderr:\\n{res.stderr}"
    return json.loads(res.stdout.strip())


def test_normalize_receipt_url_candidate_skips_detail_page_view() -> None:
    data = _node_json(
        """({
  keep: mod.normalizeReceiptUrlCandidate("https://order.my.rakuten.co.jp/?act=order_invoice&page=myorder", "https://order.my.rakuten.co.jp/"),
  drop: mod.normalizeReceiptUrlCandidate("https://order.my.rakuten.co.jp/purchase-history/?act=detail_page_view", "https://order.my.rakuten.co.jp/")
})"""
    )
    assert data["keep"] is not None
    assert data["drop"] is None


def test_is_direct_rakuten_download_url_detects_invoice_endpoint() -> None:
    data = _node_json(
        """({
  direct: mod.isDirectRakutenDownloadUrl("https://order.my.rakuten.co.jp/?lang=ja&shop_id=1&order_number=1&act=order_invoice&page=myorder"),
  non_direct: mod.isDirectRakutenDownloadUrl("https://order.my.rakuten.co.jp/purchase-history/?act=detail_page_view")
})"""
    )
    assert data["direct"] is True
    assert data["non_direct"] is False
