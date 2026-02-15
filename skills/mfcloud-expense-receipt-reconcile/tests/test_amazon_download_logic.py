from __future__ import annotations

import json
from pathlib import Path
import subprocess


SKILL_ROOT = Path(__file__).resolve().parents[1]
AMAZON_MODULE_URL = (SKILL_ROOT / "scripts" / "amazon_download.mjs").resolve().as_uri()


def _node_json(expr: str) -> dict:
    script = f"""
import * as mod from {json.dumps(AMAZON_MODULE_URL)};
const outMaybe = {expr};
const out = outMaybe && typeof outMaybe.then === "function" ? await outMaybe : outMaybe;
console.log(JSON.stringify(out));
"""
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=str(SKILL_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"node eval failed\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    lines = [line for line in res.stdout.splitlines() if line.strip()]
    assert lines, f"node eval produced no stdout\nstderr:\n{res.stderr}"
    return json.loads(lines[-1])


def test_classify_amazon_document_candidate_prefers_tax_invoice() -> None:
    data = _node_json(
        """{
  tax: mod.classifyAmazonDocumentCandidate("https://www.amazon.co.jp/tax-invoice?order=1", "明細書/適格請求書"),
  summary: mod.classifyAmazonDocumentCandidate("https://www.amazon.co.jp/order-summary/print?order=1", "印刷可能な注文概要")
}"""
    )
    assert data["tax"]["kind"] == "tax_invoice"
    assert data["summary"]["kind"] == "order_summary"
    assert data["tax"]["score"] > data["summary"]["score"]


def test_extract_order_id_from_url_works_for_order_details_query() -> None:
    data = _node_json(
        """({
  id: mod.extractOrderIdFromUrl("https://www.amazon.co.jp/gp/your-account/order-details?orderID=503-6793934-9131038")
})"""
    )
    assert data["id"] == "503-6793934-9131038"


def test_extract_order_id_from_url_supports_subscription_order_id() -> None:
    data = _node_json(
        """({
  id: mod.extractOrderIdFromUrl("https://www.amazon.co.jp/your-orders/invoice/popover?orderId=D01-6742697-2645837&ref_=fed_digi_order_invoice_ajax")
})"""
    )
    assert data["id"] == "D01-6742697-2645837"


def test_extract_order_date_from_text_supports_subscription_billing_date_label() -> None:
    data = _node_json(
        """({
  date: mod.extractOrderDateFromText("サブスクリプション課金日 2026年1月27日 合計 ￥1,680", 2026)
})"""
    )
    assert data["date"] == "2026-01-27"


def test_extract_amazon_payment_method_from_text() -> None:
    data = _node_json(
        """({
  jp: mod.extractAmazonPaymentMethodFromText("お支払い方法: 代金引換（コンビニ）\\n注文情報"),
  en: mod.extractAmazonPaymentMethodFromText("Payment method: Cash on Delivery"),
  none: mod.extractAmazonPaymentMethodFromText("注文ID: 123")
})"""
    )
    assert data["jp"] == "代金引換（コンビニ）"
    assert data["en"] == "Cash on Delivery"
    assert data["none"] is None


def test_is_amazon_no_receipt_payment_method() -> None:
    data = _node_json(
        """({
  cod_jp: mod.isAmazonNoReceiptPaymentMethod("代金引換"),
  cod_en: mod.isAmazonNoReceiptPaymentMethod("Cash on Delivery"),
  cod_mixed: mod.isAmazonNoReceiptPaymentMethod("代金引換（コンビニ）"),
  cod_symbol: mod.isAmazonNoReceiptPaymentMethod("C.O.D."),
  cod_dash: mod.isAmazonNoReceiptPaymentMethod("collect-on-delivery"),
  cod_collect: mod.isAmazonNoReceiptPaymentMethod("collect on delivery"),
  non_cod: mod.isAmazonNoReceiptPaymentMethod("代金決済"),
  normal: mod.isAmazonNoReceiptPaymentMethod("クレジットカード"),
  blank: mod.isAmazonNoReceiptPaymentMethod("")
})"""
    )
    assert data["cod_jp"] is True
    assert data["cod_en"] is True
    assert data["cod_mixed"] is True
    assert data["cod_symbol"] is True
    assert data["cod_dash"] is True
    assert data["cod_collect"] is True
    assert data["non_cod"] is False
    assert data["normal"] is False
    assert data["blank"] is False


def test_derive_amazon_document_type() -> None:
    data = _node_json(
        """(() => {
  const withInvoice = mod.deriveAmazonDocumentType({
    documents: [{ doc_type: "receipt_like" }, { doc_type: "tax_invoice" }],
    docType: "receipt_like",
    status: "ok",
  });
  const withSummary = mod.deriveAmazonDocumentType({
    documents: [{ doc_type: "order_summary" }],
    status: "ok",
  });
  const noReceipt = mod.deriveAmazonDocumentType({
    documents: [],
    status: "no_receipt",
  });
  const giftCard = mod.deriveAmazonDocumentType({
    documents: [{ doc_type: "receipt_like" }],
    status: "gift_card",
  });
  const fallbackFromDocType = mod.deriveAmazonDocumentType({
    documents: [],
    docType: "tax_invoice",
    status: "ok",
  });
  return { withInvoice, withSummary, noReceipt, giftCard, fallbackFromDocType };
})()"""
    )
    assert data["withInvoice"] == "invoice"
    assert data["withSummary"] == "receipt"
    assert data["noReceipt"] == "no_receipt"
    assert data["giftCard"] is None
    assert data["fallbackFromDocType"] == "invoice"


def test_classify_amazon_document_candidate_ignores_invoice_popover_url() -> None:
    data = _node_json(
        """({
  candidate: mod.classifyAmazonDocumentCandidate(
    "https://www.amazon.co.jp/your-orders/invoice/popover?orderId=503-6793934-9131038&ref_=fed_invoice_ajax",
    "明細書/適格請求書"
  )
})"""
    )
    assert data["candidate"] is None


def test_classify_amazon_document_candidate_ignores_gift_receipt_url() -> None:
    data = _node_json(
        """({
  candidate: mod.classifyAmazonDocumentCandidate(
    "https://www.amazon.co.jp/gcx/-/ty/gr/503-6793934-9131038/shipment?ref=ppx_yo2ov_dt_b_gift_receipt",
    "Gift receipt"
  )
})"""
    )
    assert data["candidate"] is None


def test_build_amazon_document_plan_prioritizes_summary_then_invoice() -> None:
    data = _node_json(
        """(() => {
  const candidates = [
    mod.classifyAmazonDocumentCandidate("https://www.amazon.co.jp/documents/download/abc/invoice.pdf", "明細書/適格請求書"),
    mod.classifyAmazonDocumentCandidate("https://www.amazon.co.jp/gp/css/summary/print.html?orderID=503", "印刷可能な注文概要"),
    mod.classifyAmazonDocumentCandidate("https://www.amazon.co.jp/gcx/-/ty/gr/503/shipment?ref=gift_receipt", "Gift receipt")
  ].filter(Boolean);
  return mod.buildAmazonDocumentPlan(candidates, null);
})()"""
    )
    assert len(data) >= 2
    assert data[0]["kind"] == "order_summary"
    assert data[1]["kind"] == "tax_invoice"


def test_assess_amazon_receipt_page_rejects_selection_screen() -> None:
    data = _node_json(
        """mod.assessAmazonReceiptPageText("明細書/適格請求書 印刷可能な注文概要 適格請求書 選択してください")"""
    )
    assert data["ok"] is False
    assert "selection_page" in str(data["reason"])


def test_assess_amazon_receipt_page_accepts_subscription_order_id() -> None:
    data = _node_json(
        """mod.assessAmazonReceiptPageText("領収書 注文番号 D01-6742697-2645837 サブスクリプション課金日 2026年1月27日")"""
    )
    assert data["ok"] is True


def test_coverage_threshold_failure_and_success() -> None:
    failed = _node_json(
        """(() => {
  const summary = mod.computeCoverageSummary({ monthlyOrdersTotal: 10, pdfSaved: 7, noReceipt: 0, failedOrders: [] });
  let message = "";
  try {
    mod.assertCoverageThreshold(summary, 0.8);
  } catch (e) {
    message = String(e && e.message ? e.message : e);
  }
  return { coverage: summary.coverage, message };
})()"""
    )
    assert failed["coverage"] == 0.7
    assert "AMAZON_COVERAGE_THRESHOLD_NOT_MET" in failed["message"]

    passed = _node_json(
        """(() => {
  const summary = mod.computeCoverageSummary({ monthlyOrdersTotal: 10, pdfSaved: 9, noReceipt: 0, failedOrders: [] });
  mod.assertCoverageThreshold(summary, 0.8);
  return { coverage: summary.coverage };
})()"""
    )
    assert passed["coverage"] == 0.9


def test_detect_amazon_receipt_cutoff_from_blocks_returns_first_match() -> None:
    data = _node_json(
        """({
  cutoff: mod.detectAmazonReceiptCutoffFromBlocks([
    { text: "領収書", top: 20 },
    { text: "1月30日にお届け済み", top: 420 },
    { text: "注文内容", top: 640 }
  ])
})"""
    )
    assert data["cutoff"] == 420


def test_detect_amazon_receipt_cutoff_from_blocks_returns_null_when_not_found() -> None:
    data = _node_json(
        """({
  cutoff: mod.detectAmazonReceiptCutoffFromBlocks([
    { text: "領収書", top: 20 },
    { text: "お支払い方法", top: 80 }
  ])
})"""
    )
    assert data["cutoff"] is None


def test_save_receipt_pdf_head_only_applies_mask_when_cutoff_detected() -> None:
    data = _node_json(
        """await (async () => {
  const fs = await import("node:fs");
  const os = await import("node:os");
  const path = await import("node:path");
  const outPdfPath = path.join(os.tmpdir(), `ax_head_only_${Date.now()}_${Math.random().toString(16).slice(2)}.pdf`);
  const calls = { detect: 0, apply: 0, clear: 0, pdf: 0 };
  const page = {
    emulateMedia: async () => {},
    evaluate: async (_fn, arg) => {
      if (Array.isArray(arg)) {
        calls.detect += 1;
        return [{ text: "1月30日にお届け済み", top: 360 }];
      }
      if (arg && typeof arg === "object" && Object.prototype.hasOwnProperty.call(arg, "cutoff")) {
        calls.apply += 1;
        return { applied: true, hiddenCount: 12 };
      }
      if (arg && typeof arg === "object" && Object.prototype.hasOwnProperty.call(arg, "styleId")) {
        calls.clear += 1;
        return true;
      }
      return null;
    },
    pdf: async ({ path: savePath }) => {
      calls.pdf += 1;
      fs.writeFileSync(savePath, "%PDF-1.4\\n");
    },
  };
  const result = await mod.saveReceiptPdf(page, outPdfPath, { headOnly: true });
  const exists = fs.existsSync(outPdfPath);
  if (exists) fs.unlinkSync(outPdfPath);
  return { result, calls, exists };
})()"""
    )
    assert data["result"]["headOnlyApplied"] is True
    assert data["calls"]["detect"] == 1
    assert data["calls"]["apply"] == 1
    assert data["calls"]["clear"] == 1
    assert data["calls"]["pdf"] == 1
    assert data["exists"] is True


def test_save_receipt_pdf_head_only_falls_back_to_full_page_when_cutoff_missing() -> None:
    data = _node_json(
        """await (async () => {
  const fs = await import("node:fs");
  const os = await import("node:os");
  const path = await import("node:path");
  const outPdfPath = path.join(os.tmpdir(), `ax_head_only_fallback_${Date.now()}_${Math.random().toString(16).slice(2)}.pdf`);
  const calls = { detect: 0, apply: 0, clear: 0, pdf: 0 };
  const page = {
    emulateMedia: async () => {},
    evaluate: async (_fn, arg) => {
      if (Array.isArray(arg)) {
        calls.detect += 1;
        return [];
      }
      if (arg && typeof arg === "object" && Object.prototype.hasOwnProperty.call(arg, "cutoff")) {
        calls.apply += 1;
        return { applied: true, hiddenCount: 3 };
      }
      if (arg && typeof arg === "object" && Object.prototype.hasOwnProperty.call(arg, "styleId")) {
        calls.clear += 1;
        return true;
      }
      return null;
    },
    pdf: async ({ path: savePath }) => {
      calls.pdf += 1;
      fs.writeFileSync(savePath, "%PDF-1.4\\n");
    },
  };
  const result = await mod.saveReceiptPdf(page, outPdfPath, { headOnly: true });
  const exists = fs.existsSync(outPdfPath);
  if (exists) fs.unlinkSync(outPdfPath);
  return { result, calls, exists };
})()"""
    )
    assert data["result"]["headOnlyApplied"] is False
    assert data["calls"]["detect"] == 1
    assert data["calls"]["apply"] == 0
    assert data["calls"]["clear"] == 0
    assert data["calls"]["pdf"] == 1
    assert data["exists"] is True


def test_extract_summary_totals_prefers_billing_total_with_currency_symbol() -> None:
    data = _node_json(
        """(() => {
  const text = [
    "注文概要",
    "商品の小計: ¥6,554",
    "注文合計: ¥6,554",
    "ご請求額: ¥6,554",
    "1月30日にお届け済み",
    "¥873",
    "¥5,681"
  ].join("\\n");
  const totals = mod.extractSummaryTotalsFromText(text);
  const extracted = mod.extractTotalFromText(text);
  return { totals, extracted };
})()"""
    )
    assert data["totals"]["billingTotalYen"] == 6554
    assert data["totals"]["orderTotalYen"] == 6554
    assert data["extracted"] == 6554


def test_extract_summary_totals_supports_yen_suffix_style() -> None:
    data = _node_json(
        """(() => {
  const text = [
    "ご請求額: 6,554円",
    "注文合計: 6,554円"
  ].join("\\n");
  return mod.extractSummaryTotalsFromText(text);
})()"""
    )
    assert data["billingTotalYen"] == 6554
    assert data["orderTotalYen"] == 6554


def test_choose_amazon_order_total_priority_order() -> None:
    billing = _node_json(
        """mod.chooseAmazonOrderTotal({
  billingTotalYen: 6554,
  summaryTotalYen: 6400,
  invoiceTotalSumYen: 6554,
  fallbackTotalYen: 5681
})"""
    )
    assert billing["totalYen"] == 6554
    assert billing["totalSource"] == "billing_total"

    summary = _node_json(
        """mod.chooseAmazonOrderTotal({
  billingTotalYen: null,
  summaryTotalYen: 6554,
  invoiceTotalSumYen: 6500,
  fallbackTotalYen: 5681
})"""
    )
    assert summary["totalYen"] == 6554
    assert summary["totalSource"] == "summary_total"

    invoice_sum = _node_json(
        """mod.chooseAmazonOrderTotal({
  billingTotalYen: null,
  summaryTotalYen: null,
  invoiceTotalSumYen: 6554,
  fallbackTotalYen: 5681
})"""
    )
    assert invoice_sum["totalYen"] == 6554
    assert invoice_sum["totalSource"] == "invoice_sum"

    fallback = _node_json(
        """mod.chooseAmazonOrderTotal({
  billingTotalYen: null,
  summaryTotalYen: null,
  invoiceTotalSumYen: null,
  fallbackTotalYen: 5681
})"""
    )
    assert fallback["totalYen"] == 5681
    assert fallback["totalSource"] == "card_fallback"


def test_is_amazon_no_receipt_payment_method_accepts_cod_abbr() -> None:
    data = _node_json(
        """({
  cod_abbr: mod.isAmazonNoReceiptPaymentMethod("C.O.D."),
  cod_space: mod.isAmazonNoReceiptPaymentMethod("C O D"),
  non_cod: mod.isAmazonNoReceiptPaymentMethod("Credit card")
})"""
    )
    assert data["cod_abbr"] is True
    assert data["cod_space"] is True
    assert data["non_cod"] is False


def test_is_amazon_no_receipt_payment_method_rejects_non_cod_jp() -> None:
    data = _node_json(
        """({
  non_cod_jp: mod.isAmazonNoReceiptPaymentMethod("\u4ee3\u91d1\u6c7a\u6e08")
})"""
    )
    assert data["non_cod_jp"] is False
