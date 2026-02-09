(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));
  const bindCopyButtons = Common.bindCopyButtons || (() => {});

  const excludeSection = document.getElementById("exclude-section");
  const excludeButtons = Array.from(document.querySelectorAll(".exclude-save"));
  const printCompleteButtons = Array.from(document.querySelectorAll(".print-complete"));
  const excludeStatus = document.getElementById("exclude-status");
  const excludeSummary = document.getElementById("exclude-summary");
  const excludeSummaryCount = document.getElementById("exclude-summary-count");
  const statExcluded = document.getElementById("stat-excluded");
  const statIncluded = document.getElementById("stat-included");
  const runPrintScriptButtons = Array.from(document.querySelectorAll(".run-print-script"));
  const openReceiptsFolderButton = document.getElementById("open-receipts-folder");
  const printScriptStatus = document.getElementById("print-script-status");
  const printNextBox = document.getElementById("print-next-box");
  const printNextSummary = document.getElementById("print-next-summary");
  const printNextOpen = document.getElementById("print-next-open");
  const printNextCmd = document.getElementById("print-next-cmd");

  const printPreparedBySource = { amazon: false, rakuten: false };
  const bulkPrintReadyBySource = { amazon: false, rakuten: false };

  runPrintScriptButtons.forEach((button) => {
    const source = String(button.dataset.printSource || "").trim();
    if (source) {
      bulkPrintReadyBySource[source] = !button.disabled;
    }
  });

  const receiptsFolderApiCandidates = (ym) => {
    const encodedYm = encodeURIComponent(String(ym || "").trim());
    return [
      `/api/folders/${encodedYm}/receipts`,
      `/api/folders/${encodedYm}/receipt`,
      `/api/folders/${encodedYm}/open-receipts`,
      `/api/folder/${encodedYm}/receipts`,
      `/api/folders/receipts?ym=${encodedYm}`,
      `/api/folders/receipt?ym=${encodedYm}`,
      `/api/folders/open-receipts?ym=${encodedYm}`,
    ];
  };

  function setExcludeStatus(message, kind) {
    if (!excludeStatus) return;
    excludeStatus.textContent = message || "";
    excludeStatus.classList.remove("success", "error");
    if (kind) excludeStatus.classList.add(kind);
  }

  function setPrintScriptStatus(message, kind) {
    if (!printScriptStatus) return;
    printScriptStatus.textContent = message || "";
    printScriptStatus.classList.remove("success", "error");
    if (kind) printScriptStatus.classList.add(kind);
  }

  function computeExcludedFromRows() {
    let excluded = 0;
    document.querySelectorAll("#exclude-section tbody tr").forEach((row) => {
      const toggle = row.querySelector(".exclude-toggle");
      if (toggle) {
        if (toggle.checked) excluded += 1;
        return;
      }
      const cellText = String(row.cells?.[0]?.textContent || "").trim();
      if (cellText.includes("自動除外")) excluded += 1;
    });
    return excluded;
  }

  function updateExcludeCounters() {
    if (!excludeSummary) return;
    const ordersTotal = Number.parseInt(excludeSummary.dataset.ordersTotal || "0", 10);
    const excluded = computeExcludedFromRows();
    const included = Math.max(0, ordersTotal - excluded);
    if (excludeSummaryCount) excludeSummaryCount.textContent = String(excluded);
    if (statExcluded) statExcluded.textContent = String(excluded);
    if (statIncluded) statIncluded.textContent = String(included);
  }

  function setActionButtonsDisabled(isBusy) {
    excludeButtons.forEach((btn) => {
      btn.disabled = isBusy;
    });
    printCompleteButtons.forEach((btn) => {
      const source = btn.dataset.source;
      const prepared = source ? Boolean(printPreparedBySource[source]) : false;
      btn.disabled = isBusy || !prepared;
    });
  }

  function setBulkPrintButtonsDisabled(isBusy) {
    runPrintScriptButtons.forEach((button) => {
      const source = String(button.dataset.printSource || "").trim();
      const ready = source ? Boolean(bulkPrintReadyBySource[source]) : false;
      button.disabled = isBusy || !ready;
    });
  }

  function showPrintNextActions({ ym, source, count, printCommand, excludedPdfsUrl }) {
    if (!printNextBox) return;
    const sourceLabel = source === "amazon" ? "Amazon" : source === "rakuten" ? "楽天" : source;
    const normalizedCount = Number.isFinite(count) ? Math.max(0, count) : null;
    if (printNextSummary) {
      if (normalizedCount === null) {
        printNextSummary.textContent = `${sourceLabel} の印刷準備が完了しました。`;
      } else {
        printNextSummary.textContent = `${sourceLabel} の印刷対象 ${normalizedCount} 件を準備しました。`;
      }
    }
    if (printNextOpen) {
      const fallback = ym ? `/runs/${ym}/excluded-pdfs` : "#";
      printNextOpen.href = excludedPdfsUrl || fallback;
    }
    if (printNextCmd) {
      printNextCmd.textContent = printCommand || "";
    }
    printNextBox.classList.remove("hidden");
  }

  function getCurrentYm() {
    const fromOpenButton = String(openReceiptsFolderButton?.dataset.ym || "").trim();
    if (fromOpenButton) return fromOpenButton;
    const fromRunPrintButton = String(runPrintScriptButtons[0]?.dataset?.ym || "").trim();
    if (fromRunPrintButton) return fromRunPrintButton;
    const fromSection = String(excludeSection?.dataset.ym || "").trim();
    if (fromSection) return fromSection;
    const match = String(window.location.pathname || "").match(/\/runs\/(\d{4}-\d{2})/);
    return match ? String(match[1]) : "";
  }

  async function saveExclusions(ym, source) {
    const items = [];
    document.querySelectorAll(".exclude-toggle").forEach((el) => {
      const orderSource = el.dataset.source;
      const orderId = el.dataset.orderId;
      if (el.checked && orderSource && orderId) items.push({ source: orderSource, order_id: orderId });
    });

    const res = await fetch(`/api/exclusions/${ym}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exclude: items, source }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "save failed");
    }
  }

  async function preparePrint(ym, source) {
    const res = await fetch(`/api/print/${ym}/${source}`, { method: "POST" });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "print failed");
    }
    return await res.json().catch(() => ({}));
  }

  async function completePrint(ym, source) {
    const res = await fetch(`/api/print/${ym}/${source}/complete`, { method: "POST" });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "print complete failed");
    }
    return await res.json().catch(() => ({}));
  }

  if (excludeSection && (excludeButtons.length || printCompleteButtons.length)) {
    printCompleteButtons.forEach((btn) => {
      const source = btn.dataset.source;
      if (source) printPreparedBySource[source] = !btn.disabled;
    });
    document.querySelectorAll(".exclude-toggle").forEach((el) => {
      el.addEventListener("change", updateExcludeCounters);
    });
    updateExcludeCounters();
    setActionButtonsDisabled(false);
    setBulkPrintButtonsDisabled(false);

    excludeButtons.forEach((button) => {
      button.addEventListener("click", async () => {
        const ym = excludeSection.dataset.ym;
        const source = button.dataset.source;
        if (!ym || !source) return;
        printPreparedBySource[source] = false;
        bulkPrintReadyBySource[source] = false;
        setActionButtonsDisabled(true);
        setBulkPrintButtonsDisabled(true);
        setExcludeStatus("除外設定を保存中です。完了までお待ちください。", "success");
        showToast("除外設定を保存中です...", "success");
        try {
          await saveExclusions(ym, source);
          const printResult = await preparePrint(ym, source);
          printPreparedBySource[source] = true;
          bulkPrintReadyBySource[source] = true;
          updateExcludeCounters();
          const count = Number.parseInt(String(printResult?.count ?? ""), 10);
          const normalizedCount = Number.isFinite(count) ? Math.max(0, count) : null;
          const sourceLabel = source === "amazon" ? "Amazon" : "楽天";
          const successMessage =
            normalizedCount !== null
              ? `${sourceLabel} の印刷準備が完了しました（対象 ${normalizedCount} 件）。`
              : `${sourceLabel} の印刷準備が完了しました。`;
          showPrintNextActions({
            ym,
            source,
            count: normalizedCount,
            printCommand: String(printResult?.print_command || "POST /api/print-run/{ym}/{source}"),
            excludedPdfsUrl: String(printResult?.excluded_pdfs_url || ""),
          });
          setExcludeStatus(successMessage, "success");
          showToast(successMessage, "success");
        } catch (error) {
          const message = toFriendlyMessage(error?.message);
          setExcludeStatus(message || "印刷準備に失敗しました。", "error");
          showToast(message || "印刷準備に失敗しました。", "error");
        } finally {
          setActionButtonsDisabled(false);
          setBulkPrintButtonsDisabled(false);
        }
      });
    });

    printCompleteButtons.forEach((button) => {
      button.addEventListener("click", async () => {
        const ym = excludeSection.dataset.ym;
        const source = button.dataset.source;
        if (!ym || !source) return;
        setActionButtonsDisabled(true);
        try {
          const result = await completePrint(ym, source);
          const count = Number.parseInt(String(result?.count ?? ""), 10);
          const sourceLabel = source === "amazon" ? "Amazon" : "楽天";
          const doneMessage =
            Number.isFinite(count) && count >= 0
              ? `${sourceLabel} の手動印刷完了を記録しました（対象 ${count} 件）。`
              : `${sourceLabel} の手動印刷完了を記録しました。`;
          setExcludeStatus(doneMessage, "success");
          showToast(doneMessage, "success");
        } catch (error) {
          const message = toFriendlyMessage(error?.message);
          setExcludeStatus(message || "印刷完了の記録に失敗しました。", "error");
          showToast(message || "印刷完了の記録に失敗しました。", "error");
        } finally {
          setActionButtonsDisabled(false);
        }
      });
    });
  } else {
    setBulkPrintButtonsDisabled(false);
  }

  if (runPrintScriptButtons.length) {
    runPrintScriptButtons.forEach((button) => {
      button.addEventListener("click", async () => {
        const ym = getCurrentYm();
        const source = String(button.dataset.printSource || "").trim();
        if (!ym) {
          const message = "対象年月を取得できませんでした。ページを再読み込みしてください。";
          setPrintScriptStatus(message, "error");
          showToast(message, "error");
          return;
        }
        if (!source) {
          const message = "印刷ソースが不正です。";
          setPrintScriptStatus(message, "error");
          showToast(message, "error");
          return;
        }

        setBulkPrintButtonsDisabled(true);
        if (openReceiptsFolderButton) openReceiptsFolderButton.disabled = true;
        setPrintScriptStatus(`${source} 一括印刷用の結合PDFを生成しています...`, "success");
        try {
          const res = await fetch(`/api/print-run/${ym}/${encodeURIComponent(source)}`, { method: "POST" });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.detail || "一括印刷の開始に失敗しました。");

          const count = Number.parseInt(String(data?.count ?? "0"), 10);
          const missingCount = Number.parseInt(String(data?.missing_count ?? "0"), 10);
          const sourceLabel = source === "amazon" ? "Amazon" : source === "rakuten" ? "楽天" : source;
          const message = `${sourceLabel} の結合PDFを開きました。手動で印刷してください（モノクロ設定 / 対象 ${Math.max(0, count)} 件 / 欠損 ${Math.max(0, missingCount)} 件）。`;
          setPrintScriptStatus(message, "success");
          showToast(message, "success");
        } catch (error) {
          const message = toFriendlyMessage(error?.message) || "一括印刷の開始に失敗しました。";
          setPrintScriptStatus(message, "error");
          showToast(message, "error");
        } finally {
          setBulkPrintButtonsDisabled(false);
          if (openReceiptsFolderButton) openReceiptsFolderButton.disabled = false;
        }
      });
    });
  }

  if (openReceiptsFolderButton) {
    openReceiptsFolderButton.addEventListener("click", async () => {
      const ym = getCurrentYm();
      if (!ym) {
        const message = "対象年月を取得できませんでした。ページを再読み込みしてください。";
        setPrintScriptStatus(message, "error");
        showToast(message, "error");
        return;
      }
      openReceiptsFolderButton.disabled = true;
      try {
        let data = {};
        let lastDetail = "";
        let opened = false;
        for (const url of receiptsFolderApiCandidates(ym)) {
          const res = await fetch(url, { method: "POST" });
          const payload = await res.json().catch(() => ({}));
          if (res.ok) {
            data = payload;
            opened = true;
            break;
          }
          lastDetail = String(payload?.detail || "");
          if (!(res.status === 404 && lastDetail === "Not Found")) {
            break;
          }
        }
        if (!opened) throw new Error(lastDetail || "フォルダを開けませんでした。");
        const path = String(data?.path || "").trim();
        const message = path ? `領収書フォルダを開きました: ${path}` : "領収書フォルダを開きました。";
        setPrintScriptStatus(message, "success");
        showToast(message, "success");
      } catch (error) {
        const message = toFriendlyMessage(error?.message) || "フォルダを開けませんでした。";
        setPrintScriptStatus(message, "error");
        showToast(message, "error");
      } finally {
        openReceiptsFolderButton.disabled = false;
      }
    });
  }

  bindCopyButtons();
})();
