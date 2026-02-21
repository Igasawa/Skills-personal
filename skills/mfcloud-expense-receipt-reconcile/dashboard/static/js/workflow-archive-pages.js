(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));

  function formatWorkflowYm(year, month) {
    const y = Number.parseInt(String(year || "").trim(), 10);
    const m = Number.parseInt(String(month || "").trim(), 10);
    if (!Number.isInteger(y) || !Number.isInteger(m) || m < 1 || m > 12) return "";
    return `${y}-${String(m).padStart(2, "0")}`;
  }

  async function loadArchivedWorkflowPages() {
    const listEl = document.getElementById("workflow-archive-list");
    const emptyEl = document.getElementById("workflow-archive-empty");
    if (!listEl || !emptyEl) return;
    listEl.innerHTML = "";
    try {
      const res = await fetch("/api/workflow-pages?include_archived=true", { cache: "no-store" });
      const data = await res.json().catch(() => ({}));
      const rows = Array.isArray(data.workflow_pages) ? data.workflow_pages : [];
      const archivedRows = rows
        .filter((row) => Boolean(row?.archived))
        .sort((left, right) =>
          String(right?.archived_at || right?.updated_at || "").localeCompare(
            String(left?.archived_at || left?.updated_at || ""),
          ),
        );
      if (archivedRows.length === 0) {
        emptyEl.hidden = false;
        return;
      }
      emptyEl.hidden = true;
      archivedRows.forEach((row) => {
        const item = document.createElement("div");
        item.className = "workflow-archive-item";
        const meta = document.createElement("div");
        meta.className = "workflow-archive-meta";
        const nameEl = document.createElement("div");
        nameEl.className = "workflow-archive-name";
        const ym = formatWorkflowYm(row?.year, row?.month);
        nameEl.textContent = `${String(row?.name || "")}${ym ? ` (${ym})` : ""}`;
        const detailsEl = document.createElement("span");
        detailsEl.className = "muted";
        const archivedAt = String(row?.archived_at || "").trim();
        detailsEl.textContent = archivedAt ? `アーカイブ日時: ${archivedAt}` : "アーカイブ日時: -";
        meta.appendChild(nameEl);
        meta.appendChild(detailsEl);

        const restore = document.createElement("button");
        restore.type = "button";
        restore.className = "secondary";
        restore.textContent = "♻️ 復元";
        restore.addEventListener("click", async () => {
          const workflowPageId = String(row?.id || "").trim();
          if (!workflowPageId) return;
          try {
            const patchRes = await fetch(`/api/workflow-pages/${encodeURIComponent(workflowPageId)}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                archived: false,
                base_updated_at: String(row?.updated_at || ""),
              }),
            });
            const patchData = await patchRes.json().catch(() => ({}));
            if (!patchRes.ok) {
              const message = toFriendlyMessage(patchData.detail) || "復元に失敗しました。";
              showToast(message, "error");
              return;
            }
            showToast("ワークフローを復元しました。", "success");
            loadArchivedWorkflowPages();
          } catch {
            showToast("復元に失敗しました。", "error");
          }
        });
        item.appendChild(meta);
        item.appendChild(restore);
        listEl.appendChild(item);
      });
    } catch {
      emptyEl.hidden = false;
      showToast("アーカイブ一覧の取得に失敗しました。", "error");
    }
  }

  const refreshButton = document.getElementById("workflow-archive-refresh");
  refreshButton?.addEventListener("click", () => {
    loadArchivedWorkflowPages();
  });

  loadArchivedWorkflowPages();
})();
