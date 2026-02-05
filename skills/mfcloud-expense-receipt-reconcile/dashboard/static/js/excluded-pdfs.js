(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const normalize = Common.normalizeSearchText || ((t) => String(t || "").toLowerCase().replace(/\s+/g, " ").trim());

  const printButtons = document.querySelectorAll(".print-single");
  const printStatus = document.getElementById("print-status");
  const excludedSearch = document.getElementById("excluded-search");
  const excludedRows = document.querySelectorAll(".excluded-row");
  const excludedCount = document.getElementById("excluded-count");
  const filterAmazon = document.getElementById("filter-amazon");
  const filterRakuten = document.getElementById("filter-rakuten");
  const filterPdf = document.getElementById("filter-pdf");

  function setPrintStatus(message, kind) {
    if (!printStatus) return;
    printStatus.textContent = message || "";
    printStatus.classList.remove("success", "error");
    if (kind) printStatus.classList.add(kind);
  }

  function updateExcludedCount() {
    if (!excludedCount) return;
    let visible = 0;
    excludedRows.forEach((row) => {
      if (!row.classList.contains("hidden")) visible += 1;
    });
    excludedCount.textContent = String(visible);
  }

  function applyExcludedFilters() {
    if (!excludedRows.length) return;
    const query = normalize(excludedSearch?.value || "");
    const tokens = query ? query.split(" ") : [];
    const amazonOn = filterAmazon ? filterAmazon.checked : true;
    const rakutenOn = filterRakuten ? filterRakuten.checked : true;
    const pdfMode = filterPdf ? filterPdf.value : "all";
    excludedRows.forEach((row) => {
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
        printButtons.forEach((btn) => (btn.disabled = true));
        setPrintStatus("印刷を開始しています...", "success");
        try {
          const res = await fetch(`/api/print-pdf/${ym}/${source}/${filename}`, { method: "POST" });
          if (!res.ok) throw new Error("print failed");
          setPrintStatus("印刷を開始しました。", "success");
          showToast("印刷を開始しました。", "success");
        } catch {
          setPrintStatus("印刷に失敗しました。", "error");
          showToast("印刷に失敗しました。", "error");
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
    applyExcludedFilters();
  }
})();
