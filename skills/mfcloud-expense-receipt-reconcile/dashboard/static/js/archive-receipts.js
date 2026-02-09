(function () {
  const Common = window.DashboardCommon || {};
  const normalize = Common.normalizeSearchText || ((t) => String(t || "").toLowerCase().replace(/\s+/g, " ").trim());

  const rows = Array.from(document.querySelectorAll(".archive-row"));
  const searchInput = document.getElementById("archive-search");
  const monthSelect = document.getElementById("filter-month");
  const countEl = document.getElementById("archive-count");

  function updateCount() {
    if (!countEl) return;
    const visible = rows.filter((row) => !row.classList.contains("hidden")).length;
    countEl.textContent = String(visible);
  }

  function applyFilter() {
    if (!rows.length) return;
    const query = normalize(searchInput?.value || "");
    const tokens = query ? query.split(" ") : [];
    rows.forEach((row) => {
      const hay = normalize(row.dataset.search || "");
      const matched = tokens.every((token) => hay.includes(token));
      row.classList.toggle("hidden", !matched);
    });
    updateCount();
  }

  searchInput?.addEventListener("input", applyFilter);
  monthSelect?.addEventListener("change", () => {
    const targetYm = String(monthSelect.value || "").trim();
    const currentYm = String(monthSelect.dataset.currentYm || "").trim();
    if (!/^\d{4}-\d{2}$/.test(targetYm) || targetYm === currentYm) return;
    window.location.href = `/runs/${targetYm}/archived-receipts`;
  });

  applyFilter();
})();
