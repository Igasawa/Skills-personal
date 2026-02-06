(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));
  const bindCopyButtons = Common.bindCopyButtons || (() => {});

  const excludeSection = document.getElementById("exclude-section");
  const excludeButtons = document.querySelectorAll(".exclude-save");
  const excludeStatus = document.getElementById("exclude-status");
  const excludeSummary = document.getElementById("exclude-summary");
  const excludeSummaryCount = document.getElementById("exclude-summary-count");
  const statExcluded = document.getElementById("stat-excluded");
  const statIncluded = document.getElementById("stat-included");

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

  async function runPrint(ym, source) {
    const res = await fetch(`/api/print/${ym}/${source}`, { method: "POST" });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "print failed");
    }
  }

  if (excludeSection && excludeButtons.length) {
    document.querySelectorAll(".exclude-toggle").forEach((el) => {
      el.addEventListener("change", updateExcludeCounters);
    });
    updateExcludeCounters();

    excludeButtons.forEach((button) => {
      button.addEventListener("click", async () => {
        const ym = excludeSection.dataset.ym;
        const source = button.dataset.source;
        if (!ym || !source) return;
        excludeButtons.forEach((btn) => (btn.disabled = true));
        try {
          await saveExclusions(ym, source);
          await runPrint(ym, source);
          updateExcludeCounters();
          setExcludeStatus(excludeStatus?.dataset.success || "除外設定を保存しました。印刷を実行しました。", "success");
          showToast("除外設定を保存し印刷を開始しました。", "success");
        } catch (error) {
          const message = toFriendlyMessage(error?.message);
          setExcludeStatus(message || excludeStatus?.dataset.error || "保存または印刷に失敗しました。", "error");
          showToast(message || "保存または印刷に失敗しました。", "error");
        } finally {
          excludeButtons.forEach((btn) => (btn.disabled = false));
        }
      });
    });
  }

  bindCopyButtons();
})();
