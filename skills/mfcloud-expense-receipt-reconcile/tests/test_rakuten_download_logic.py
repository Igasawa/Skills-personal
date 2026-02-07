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


def test_should_downgrade_books_invalid_page_error_to_no_receipt() -> None:
    data = _node_json(
        """({
  books_invalid: mod.shouldDowngradeRakutenReceiptError(
    "rakuten_receipt_invalid_page:注文商品のキャンセル、数量の変更はできますか",
    "https://books.rakuten.co.jp/mypage/delivery/status?order_number=213310-20260125-0555903016"
  ),
  books_missing_signal: mod.shouldDowngradeRakutenReceiptError(
    "rakuten_receipt_page_missing_signal",
    "https://books.rakuten.co.jp/mypage/delivery/receiptInput?order_number=213310-20260125-0555903016"
  ),
  regular_invalid: mod.shouldDowngradeRakutenReceiptError(
    "rakuten_receipt_invalid_page:detail_page_view_url",
    "https://order.my.rakuten.co.jp/purchase-history/?order_number=427784-20260125-0822503103&act=detail_page_view"
  )
})"""
    )
    assert data["books_invalid"] is True
    assert data["books_missing_signal"] is True
    assert data["regular_invalid"] is False


def test_assess_rakuten_receipt_page_text_handles_books_receipt_with_faq_footer() -> None:
    data = _node_json(
        """mod.assessRakutenReceiptPageText([
  "楽天ブックス 領収書発行",
  "領収書発行",
  "注文商品のキャンセル、数量の変更はできますか"
].join("\\n"))"""
    )
    assert data["ok"] is True


def test_assess_rakuten_receipt_context_rejects_books_status_page() -> None:
    data = _node_json(
        """mod.assessRakutenReceiptContext({
  url: "https://books.rakuten.co.jp/mypage/delivery/status?order_number=213310-20260125-0555903016",
  title: "楽天ブックス: Myページ | 領収書",
  pageAction: "",
  messageCode: ""
})"""
    )
    assert data["ok"] is False
    assert data["reason"] == "rakuten_receipt_invalid_page:books_status_page"
