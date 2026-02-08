(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));
  const bindCopyButtons = Common.bindCopyButtons || (() => {});

  const excludeSection = document.getElementById("exclude-section");
  const excludeButtons = document.querySelectorAll(".exclude-save");
  const printCompleteButtons = document.querySelectorAll(".print-complete");
  const excludeStatus = document.getElementById("exclude-status");
  const excludeSummary = document.getElementById("exclude-summary");
  const excludeSummaryCount = document.getElementById("exclude-summary-count");
  const statExcluded = document.getElementById("stat-excluded");
  const statIncluded = document.getElementById("stat-included");
  const printPreparedBySource = { amazon: false, rakuten: false };

  function setExcludeStatus(message, kind) {
    if (!excludeStatus) return;
    excludeStatus.textContent = message || "";
    excludeStatus.classList.remove("success", "error");
    if (kind) excludeStatus.classList.add(kind);
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

    excludeButtons.forEach((button) => {
      button.addEventListener("click", async () => {
        const ym = excludeSection.dataset.ym;
        const source = button.dataset.source;
        if (!ym || !source) return;
        printPreparedBySource[source] = false;
        setActionButtonsDisabled(true);
        setExcludeStatus("印刷準備を作成中です。完了までお待ちください。", "success");
        showToast("印刷準備を作成中です...", "success");
        try {
          await saveExclusions(ym, source);
          const printResult = await preparePrint(ym, source);
          printPreparedBySource[source] = true;
          updateExcludeCounters();
          const count = Number.parseInt(String(printResult?.count ?? ""), 10);
          const sourceLabel = source === "amazon" ? "Amazon" : "楽天";
          let successMessage = excludeStatus?.dataset.success || "除外設定を保存しました。印刷準備が完了しました。";
          let toastMessage = "除外設定を保存し印刷準備が完了しました。";
          if (Number.isFinite(count)) {
            if (count > 0) {
              toastMessage = `除外設定を保存し ${count} 件の印刷準備が完了しました。`;
              successMessage = `除外設定を保存しました。${sourceLabel} 印刷対象 ${count} 件を準備しました。手動印刷後に「${sourceLabel}印刷完了を記録」を押してください。`;
            } else {
              toastMessage = "除外設定を保存しました。印刷対象は 0 件です。";
              successMessage = "除外設定を保存しました。印刷対象は 0 件です。";
            }
          }
          setExcludeStatus(successMessage, "success");
          showToast(toastMessage, "success");
        } catch (error) {
          const message = toFriendlyMessage(error?.message);
          setExcludeStatus(message || excludeStatus?.dataset.error || "保存または印刷準備に失敗しました。", "error");
          showToast(message || "保存または印刷準備に失敗しました。", "error");
        } finally {
          setActionButtonsDisabled(false);
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
  }

  bindCopyButtons();
})();
