(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));

  const sourceSelect = document.getElementById("kil-review-source");
  const limitSelect = document.getElementById("kil-review-limit");
  const refreshButton = document.getElementById("kil-review-refresh");
  const statusEl = document.getElementById("kil-review-status");
  const sourceUsedEl = document.getElementById("kil-review-source-used");
  const countEl = document.getElementById("kil-review-count");
  const indexCountEl = document.getElementById("kil-review-index-count");
  const markdownCountEl = document.getElementById("kil-review-markdown-count");
  const overdueEl = document.getElementById("kil-review-overdue");
  const dueSoonEl = document.getElementById("kil-review-due-soon");
  const noDeadlineEl = document.getElementById("kil-review-no-deadline");
  const generatedAtEl = document.getElementById("kil-review-generated-at");
  const riskGridEl = document.getElementById("kil-review-risk-grid");
  const itemsEl = document.getElementById("kil-review-items");
  const emptyEl = document.getElementById("kil-review-empty");
  const filesEl = document.getElementById("kil-review-data-files");

  function setText(el, value) {
    if (!el) return;
    el.textContent = String(value == null ? "" : value);
  }

  function toInt(value, fallback = 0) {
    const parsed = Number.parseInt(String(value || ""), 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function escapeText(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function toDeadlineBadge(value) {
    const text = String(value || "").trim();
    if (!text) return "未設定";
    const normalized = text.trim();
    return normalized;
  }

  function renderSummary(payload) {
    const review = payload.review || {};
    setText(sourceUsedEl, payload.source_used || payload.requested_source || "-");
    setText(countEl, toInt(payload.count, 0));
    setText(indexCountEl, toInt(payload.source_counts?.index, 0));
    setText(markdownCountEl, toInt(payload.source_counts?.markdown, 0));
    setText(overdueEl, toInt(review.overdue, 0));
    setText(dueSoonEl, toInt(review.due_within_7d, 0));
    setText(noDeadlineEl, toInt(review.no_deadline, 0));
    setText(generatedAtEl, payload.generated_at ? String(payload.generated_at) : "-");
  }

  function renderFiles(payload) {
    if (!filesEl) return;
    const files = payload.data_files || {};
    const indexPath = String(files.index_path || "AGENT_BRAIN_INDEX.jsonl");
    const markdownPath = String(files.markdown_path || "AGENT_BRAIN.md");
    const indexState = files.index_exists ? "あり" : "未作成";
    const mdState = files.markdown_exists ? "あり" : "未作成";
    filesEl.innerHTML = "";
    const li1 = document.createElement("li");
    li1.textContent = `${indexPath} (${indexState})`;
    const li2 = document.createElement("li");
    li2.textContent = `${markdownPath} (${mdState})`;
    filesEl.appendChild(li1);
    filesEl.appendChild(li2);
  }

  function renderRisk(payload) {
    if (!riskGridEl) return;
    const entries = payload.risk_counts || {};
    const keys = Object.keys(entries);
    riskGridEl.innerHTML = "";
    if (!keys.length) {
      riskGridEl.innerHTML = `<div class="muted">リスクラベルがありません</div>`;
      return;
    }
    keys
      .sort((a, b) => entries[b] - entries[a])
      .forEach((name) => {
        const card = document.createElement("div");
        card.className = "kil-review-stat";
        const label = document.createElement("span");
        label.className = "label";
        label.textContent = name;
        const value = document.createElement("span");
        value.className = "value";
        value.textContent = String(toInt(entries[name], 0));
        card.appendChild(label);
        card.appendChild(value);
        riskGridEl.appendChild(card);
      });
  }

  function renderItems(payload) {
    if (!itemsEl || !emptyEl) return;
    const items = Array.isArray(payload.items) ? payload.items : [];
    itemsEl.innerHTML = "";
    if (!items.length) {
      emptyEl.classList.remove("hidden");
      return;
    }
    emptyEl.classList.add("hidden");

    items.forEach((item) => {
      const row = document.createElement("li");
      row.className = "kil-review-item";

      const head = document.createElement("div");
      head.className = "kil-review-item-head";
      const title = document.createElement("span");
      title.className = "kil-review-item-title";
      const commit = String(item.commit || "").trim() || "unknown";
      title.textContent = `${item.source || "-"} / ${commit.slice(0, 10)}...`;

      const date = document.createElement("span");
      date.className = "muted";
      date.textContent = String(item.date || "-");

      head.appendChild(title);
      head.appendChild(date);

      const summary = document.createElement("p");
      summary.className = "kil-review-item-summary";
      summary.textContent = String(item.summary || "").trim() || "(要約なし)";

      const meta = document.createElement("div");
      meta.className = "kil-review-item-meta";
      const risk = document.createElement("span");
      risk.className = "kil-review-chip";
      risk.textContent = `risk: ${String(item.risk || "normal")}`;
      const deadline = document.createElement("span");
      deadline.className = "kil-review-chip";
      deadline.textContent = `deadline: ${toDeadlineBadge(item.deadline)}`;
      meta.appendChild(risk);
      meta.appendChild(deadline);

      const details = document.createElement("details");
      const summaryEl = document.createElement("summary");
      summaryEl.textContent = "詳細";
      const body = document.createElement("pre");
      body.className = "log";
      const detailPayload = {
        commit: item.commit || "",
        knowledge: item.knowledge || [],
        rules: item.rules || [],
        context: item.context || [],
      };
      body.textContent = JSON.stringify(detailPayload, null, 2);
      details.appendChild(summaryEl);
      details.appendChild(body);

      row.appendChild(head);
      row.appendChild(summary);
      row.appendChild(meta);
      row.appendChild(details);
      itemsEl.appendChild(row);
    });
  }

  function setBusy(state) {
    if (refreshButton) {
      refreshButton.disabled = !!state;
      refreshButton.textContent = state ? "読込中..." : "更新";
    }
    if (statusEl) {
      statusEl.textContent = state ? "読み込み中..." : statusEl.textContent;
    }
  }

  async function fetchKilReview() {
    if (!sourceSelect || !limitSelect) return;
    const source = sourceSelect.value || "auto";
    const limit = Number.parseInt(String(limitSelect.value || "20"), 10) || 20;
    const params = new URLSearchParams({ source, limit: String(limit) });
    setBusy(true);
    setText(statusEl, "取得中...");
    try {
      const res = await fetch(`/api/kil-review?${params}`, { cache: "no-store" });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(toFriendlyMessage(detail.detail || `HTTP ${res.status}`));
      }
      const payload = await res.json().catch(() => ({}));
      renderSummary(payload || {});
      renderFiles(payload || {});
      renderRisk(payload || {});
      renderItems(payload || {});
      setText(statusEl, "最終更新: " + new Date().toLocaleString("ja-JP"));
      showToast("KIL情報を更新しました", "success");
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "KIL Reviewデータの取得に失敗しました");
      setText(statusEl, message);
      showToast(message, "error");
    } finally {
      setBusy(false);
    }
  }

  if (refreshButton) {
    refreshButton.addEventListener("click", () => {
      void fetchKilReview();
    });
  }

  if (sourceSelect) {
    sourceSelect.addEventListener("change", () => {
      void fetchKilReview();
    });
  }

  if (limitSelect) {
    limitSelect.addEventListener("change", () => {
      void fetchKilReview();
    });
  }

  void fetchKilReview();
})();
