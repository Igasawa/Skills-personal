(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const normalize = Common.normalizeSearchText || ((t) => String(t || "").toLowerCase().replace(/\s+/g, " ").trim());

  const printButtons = document.querySelectorAll(".print-single");
  const printStatus = document.getElementById("print-status");
  const excludedSearch = document.getElementById("excluded-search");
  const excludedRows = document.querySelectorAll(".excluded-row");
  const excludedRowsList = Array.from(excludedRows);
  const excludedCount = document.getElementById("excluded-count");
  const filterAmazon = document.getElementById("filter-amazon");
  const filterRakuten = document.getElementById("filter-rakuten");
  const filterPdf = document.getElementById("filter-pdf");
  const filterMonth = document.getElementById("filter-month");
  const sortOrder = document.getElementById("sort-order");
  const excludedTableBody = document.getElementById("excluded-table-body");

  function setPrintStatus(message, kind) {
    if (!printStatus) return;
    printStatus.textContent = message || "";
    printStatus.classList.remove("success", "error");
    if (kind) printStatus.classList.add(kind);
  }

  function updateExcludedCount() {
    if (!excludedCount) return;
    let visible = 0;
    excludedRowsList.forEach((row) => {
      if (!row.classList.contains("hidden")) visible += 1;
    });
    excludedCount.textContent = String(visible);
  }

  function compareText(a, b) {
    if (a === b) return 0;
    return a < b ? -1 : 1;
  }

  function sortExcludedRows() {
    if (!excludedTableBody || !excludedRowsList.length) return;
    const mode = sortOrder ? String(sortOrder.value || "date_desc") : "date_desc";
    excludedRowsList.sort((left, right) => {
      const leftDate = String(left.dataset.orderDate || "");
      const rightDate = String(right.dataset.orderDate || "");
      const leftSource = String(left.dataset.source || "");
      const rightSource = String(right.dataset.source || "");
      const leftOrder = String(left.dataset.orderId || "");
      const rightOrder = String(right.dataset.orderId || "");

      if (mode === "date_asc") {
        return compareText(leftDate, rightDate) || compareText(leftOrder, rightOrder);
      }
      if (mode === "source_date_asc") {
        return (
          compareText(leftSource, rightSource) ||
          compareText(leftDate, rightDate) ||
          compareText(leftOrder, rightOrder)
        );
      }
      return compareText(rightDate, leftDate) || compareText(rightOrder, leftOrder);
    });

    excludedRowsList.forEach((row) => {
      excludedTableBody.appendChild(row);
    });
  }

  function applyExcludedFilters() {
    if (!excludedRowsList.length) return;
    sortExcludedRows();
    const query = normalize(excludedSearch?.value || "");
    const tokens = query ? query.split(" ") : [];
    const amazonOn = filterAmazon ? filterAmazon.checked : true;
    const rakutenOn = filterRakuten ? filterRakuten.checked : true;
    const pdfMode = filterPdf ? filterPdf.value : "all";
    excludedRowsList.forEach((row) => {
      const source = row.dataset.source || "";
      const hasPdf = row.dataset.hasPdf || "yes";
      const sourceMatch = (source === "amazon" && amazonOn) || (source === "rakuten" && rakutenOn);
      const pdfMatch = pdfMode === "all" || (pdfMode === "yes" && hasPdf === "yes") || (pdfMode === "no" && hasPdf === "no");
      const hay = normalize(row.dataset.search);
      const textMatch = tokens.every((t) => hay.includes(t));
      row.classList.toggle("hidden", !(sourceMatch && pdfMatch && textMatch));
    });
    updateExcludedCount();
  }

  if (printButtons.length) {
    printButtons.forEach((button) => {
      button.addEventListener("click", async () => {
        const ym = button.dataset.ym;
        const source = button.dataset.source;
        const filename = button.dataset.filename;
        if (!ym || !source || !filename) return;
        const previewWindow = window.open("about:blank", "_blank");
        if (!previewWindow) {
          setPrintStatus("ポップアップがブロックされました。許可して再実行してください。", "error");
          showToast("ポップアップがブロックされました。", "error");
          return;
        }
        printButtons.forEach((btn) => (btn.disabled = true));
        setPrintStatus("PDFを開いています...", "success");
        try {
          const res = await fetch(`/api/print-pdf/${ym}/${source}/${filename}`, { method: "POST" });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(String(data?.detail || "print failed"));
          const pdfUrl = String(data?.pdf_url || "");
          if (!pdfUrl) throw new Error("print target missing");
          previewWindow.location.replace(pdfUrl);
          try {
            previewWindow.focus();
          } catch {
            // no-op
          }
          setPrintStatus("PDFを開きました。印刷はブラウザ側で実行してください（Ctrl+P、モノクロ設定を確認）。", "success");
          showToast("PDFを開きました。Ctrl+Pでモノクロ設定を確認して印刷してください。", "success");
        } catch (error) {
          try {
            previewWindow.close();
          } catch {
            // no-op
          }
          const message = String(error?.message || "");
          const blocked = message.toLowerCase().includes("popup");
          const label = blocked
            ? "ポップアップがブロックされました。"
            : "PDFの表示に失敗しました。";
          setPrintStatus(label, "error");
          showToast(label, "error");
        } finally {
          printButtons.forEach((btn) => (btn.disabled = false));
        }
      });
    });
  }

  if (excludedRows.length) {
    excludedSearch?.addEventListener("input", applyExcludedFilters);
    filterAmazon?.addEventListener("change", applyExcludedFilters);
    filterRakuten?.addEventListener("change", applyExcludedFilters);
    filterPdf?.addEventListener("change", applyExcludedFilters);
    sortOrder?.addEventListener("change", applyExcludedFilters);
    filterMonth?.addEventListener("change", () => {
      const targetYm = String(filterMonth.value || "").trim();
      const currentYm = String(filterMonth.dataset.currentYm || "").trim();
      if (!/^\d{4}-\d{2}$/.test(targetYm) || targetYm === currentYm) return;
      window.location.href = `/runs/${targetYm}/excluded-pdfs`;
    });
    applyExcludedFilters();
  }
})();
