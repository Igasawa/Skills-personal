from __future__ import annotations

import json
from pathlib import Path
import subprocess


SKILL_ROOT = Path(__file__).resolve().parents[1]
AMAZON_MODULE_URL = (SKILL_ROOT / "scripts" / "amazon_download.mjs").resolve().as_uri()


def _node_json(expr: str) -> dict:
    script = f"""
import * as mod from {json.dumps(AMAZON_MODULE_URL)};
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
    assert res.returncode == 0, f"node eval failed\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    return json.loads(res.stdout.strip())


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
