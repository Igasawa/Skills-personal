(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));
  const bindCopyButtons = Common.bindCopyButtons || (() => {});

  const excludeSection = document.getElementById("exclude-section");
  const excludeButtons = document.querySelectorAll(".exclude-save");
  const excludeStatus = document.getElementById("exclude-status");

  function setExcludeStatus(message, kind) {
    if (!excludeStatus) return;
    excludeStatus.textContent = message || "";
    excludeStatus.classList.remove("success", "error");
    if (kind) excludeStatus.classList.add(kind);
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
    excludeButtons.forEach((button) => {
      button.addEventListener("click", async () => {
        const ym = excludeSection.dataset.ym;
        const source = button.dataset.source;
        if (!ym || !source) return;
        excludeButtons.forEach((btn) => (btn.disabled = true));
      try {
        await saveExclusions(ym, source);
        await runPrint(ym, source);
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
