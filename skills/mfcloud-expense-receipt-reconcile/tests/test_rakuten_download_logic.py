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
        encoding="utf-8",
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
  books_receipt_print: mod.isDirectRakutenDownloadUrl("https://books.rakuten.co.jp/mypage/delivery/receiptPrint?order_number=1&back_number=abc"),
  non_direct: mod.isDirectRakutenDownloadUrl("https://order.my.rakuten.co.jp/purchase-history/?act=detail_page_view")
})"""
    )
    assert data["direct"] is True
    assert data["books_receipt_print"] is True
    assert data["non_direct"] is False


def test_extract_rakuten_books_item_name_from_receipt_text() -> None:
    data = _node_json(
        """mod.extractRakutenBooksItemNameFromText([
  "領収書（再発行） 発行日 ： 2026年02月08日",
  "利用明細",
  "注文番号 ： 213310-20260125-0555903016 注文日 ： 2026/01/25 発送日 ： 2026/01/26",
  "商品明細",
  "商品コード 商品名 数量 単価(税込) 金額(税込)",
  "9784473046963 こころが軽くなる 大人のなぞり書き 1 1,320 1,320",
  "合計金額(税込・10%) 1,320",
  "支払額 1,320"
].join("\\n"))"""
    )
    assert data == "こころが軽くなる 大人のなぞり書き"


def test_should_downgrade_books_only_for_whitelisted_non_fatal_reasons() -> None:
    data = _node_json(
        """({
  books_invalid: mod.shouldDowngradeRakutenReceiptError(
    "rakuten_receipt_invalid_page:豕ｨ譁・膚蜩√・繧ｭ繝｣繝ｳ繧ｻ繝ｫ縲∵焚驥上・螟画峩縺ｯ縺ｧ縺阪∪縺吶°",
    "https://books.rakuten.co.jp/mypage/delivery/status?order_number=213310-20260125-0555903016"
  ),
  books_status: mod.shouldDowngradeRakutenReceiptError(
    "rakuten_receipt_invalid_page:books_status_page",
    "https://books.rakuten.co.jp/mypage/delivery/status?order_number=213310-20260125-0555903016"
  ),
  books_faq: mod.shouldDowngradeRakutenReceiptError(
    "rakuten_receipt_invalid_page:books_faq_page",
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
    assert data["books_invalid"] is False
    assert data["books_status"] is True
    assert data["books_faq"] is False
    assert data["books_missing_signal"] is True
    assert data["regular_invalid"] is False


def test_assess_rakuten_receipt_page_text_handles_books_receipt_with_faq_footer() -> None:
    data = _node_json(
        """mod.assessRakutenReceiptPageText([
  "receiptInputForm",
  "receiptPrint",
  "books.faq.rakuten.net"
].join("\\n"))"""
    )
    assert data["ok"] is True


def test_assess_rakuten_receipt_context_rejects_books_status_page() -> None:
    data = _node_json(
        """mod.assessRakutenReceiptContext({
  url: "https://books.rakuten.co.jp/mypage/delivery/status?order_number=213310-20260125-0555903016",
  title: "讌ｽ螟ｩ繝悶ャ繧ｯ繧ｹ: My繝壹・繧ｸ | 鬆伜庶譖ｸ",
  pageAction: "",
  messageCode: ""
})"""
    )
    assert data["ok"] is False
    assert data["reason"] == "rakuten_receipt_invalid_page:books_status_page"


def test_assess_rakuten_receipt_context_accepts_books_receipt_input_and_print_page() -> None:
    data = _node_json(
        """({
  receipt_input: mod.assessRakutenReceiptContext({
    url: "https://books.rakuten.co.jp/mypage/delivery/receiptInput?order_number=213310-20260125-0555903016&back_number=abc",
    title: "讌ｽ螟ｩ繝悶ャ繧ｯ繧ｹ: My繝壹・繧ｸ | 鬆伜庶譖ｸ",
    pageAction: "",
    messageCode: ""
  }),
  receipt_print: mod.assessRakutenReceiptContext({
    url: "https://books.rakuten.co.jp/mypage/delivery/receiptPrint?order_number=213310-20260125-0555903016&back_number=abc",
    title: "讌ｽ螟ｩ繝悶ャ繧ｯ繧ｹ: My繝壹・繧ｸ | 鬆伜庶譖ｸ",
    pageAction: "",
    messageCode: ""
  })
})"""
    )
    assert data["receipt_input"]["ok"] is True
    assert data["receipt_print"]["ok"] is True


def test_assess_rakuten_receipt_context_can_require_books_receipt_print_page() -> None:
    data = _node_json(
        """({
  receipt_input: mod.assessRakutenReceiptContext({
    url: "https://books.rakuten.co.jp/mypage/delivery/receiptInput?order_number=213310-20260125-0555903016&back_number=abc",
    title: "領収書発行",
    pageAction: "",
    messageCode: "",
    requireBooksPrint: true
  }),
  receipt_print: mod.assessRakutenReceiptContext({
    url: "https://books.rakuten.co.jp/mypage/delivery/receiptPrint?order_number=213310-20260125-0555903016&back_number=abc",
    title: "領収書発行",
    pageAction: "",
    messageCode: "",
    requireBooksPrint: true
  })
})"""
    )
    assert data["receipt_input"]["ok"] is False
    assert data["receipt_input"]["reason"] == "rakuten_receipt_invalid_page:books_receipt_input_page"
    assert data["receipt_print"]["ok"] is True


def test_books_receipt_url_helpers() -> None:
    data = _node_json(
        """({
  input_true: mod.isRakutenBooksReceiptInputUrl("https://books.rakuten.co.jp/mypage/delivery/receiptInput?order_number=1"),
  input_false: mod.isRakutenBooksReceiptInputUrl("https://books.rakuten.co.jp/mypage/delivery/status?order_number=1"),
  print_true: mod.isRakutenBooksReceiptPrintUrl("https://books.rakuten.co.jp/mypage/delivery/receiptPrint?order_number=1"),
  print_false: mod.isRakutenBooksReceiptPrintUrl("https://order.my.rakuten.co.jp/purchase-history/?act=detail_page_view")
})"""
    )
    assert data["input_true"] is True
    assert data["input_false"] is False
    assert data["print_true"] is True
    assert data["print_false"] is False


def test_assess_books_receipt_print_transition_prefers_receipt_print_url() -> None:
    data = _node_json(
        """mod.assessRakutenBooksReceiptPrintTransition({
  url: "https://books.rakuten.co.jp/mypage/delivery/receiptPrint?order_number=1",
  pathnameHint: "/mypage/delivery/receiptPrint",
  title: "讌ｽ螟ｩ繝悶ャ繧ｯ繧ｹ: My繝壹・繧ｸ | 鬆伜庶譖ｸ"
})"""
    )
    assert data["ok"] is True
    assert data["reason"] == "books_receipt_print_url"


def test_assess_books_receipt_print_transition_keeps_waiting_on_receipt_input() -> None:
    data = _node_json(
        """mod.assessRakutenBooksReceiptPrintTransition({
  url: "https://books.rakuten.co.jp/mypage/delivery/receiptInput?order_number=1",
  pathnameHint: "/mypage/delivery/receiptInput",
  title: "讌ｽ螟ｩ繝悶ャ繧ｯ繧ｹ: My繝壹・繧ｸ | 鬆伜庶譖ｸ"
})"""
    )
    assert data["ok"] is False
    assert data["reason"] == "books_receipt_print_not_ready"

