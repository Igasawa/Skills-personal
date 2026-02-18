(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));

  const sourceSelect = document.getElementById("kil-review-source");
  const limitSelect = document.getElementById("kil-review-limit");
  const refreshButton = document.getElementById("kil-review-refresh");
  const statusEl = document.getElementById("kil-review-status");
  const summaryLineEl = document.getElementById("kil-review-summary-line");
  const sourceUsedEl = document.getElementById("kil-review-source-used");
  const countEl = document.getElementById("kil-review-count");
  const reviewNeededEl = document.getElementById("kil-review-review-needed");
  const indexCountEl = document.getElementById("kil-review-index-count");
  const markdownCountEl = document.getElementById("kil-review-markdown-count");
  const overdueEl = document.getElementById("kil-review-overdue");
  const dueSoonEl = document.getElementById("kil-review-due-soon");
  const noDeadlineEl = document.getElementById("kil-review-no-deadline");
  const generatedAtEl = document.getElementById("kil-review-generated-at");
  const healthStatusEl = document.getElementById("kil-review-health-status");
  const healthScoreEl = document.getElementById("kil-review-health-score");
  const healthLagCommitsEl = document.getElementById("kil-review-health-lag-commits");
  const healthLagDaysEl = document.getElementById("kil-review-health-lag-days");
  const healthFallbackEl = document.getElementById("kil-review-health-fallback-ratio");
  const healthAnalyzedAtEl = document.getElementById("kil-review-health-analyzed-at");
  const healthAnalyzedCommitEl = document.getElementById("kil-review-health-analyzed-commit");
  const healthMessageEl = document.getElementById("kil-review-health-message");
  const riskGridEl = document.getElementById("kil-review-risk-grid");
  const itemsEl = document.getElementById("kil-review-items");
  const emptyEl = document.getElementById("kil-review-empty");
  const filesEl = document.getElementById("kil-review-data-files");
  const KIL_REVIEW_REQUEST_TIMEOUT_MS = 12000;
  const KIL_REVIEW_API_PATH = "/api/kil-review";
  const KIL_REVIEW_FALLBACK_PORTS = ["8765", "8000"];

  function setText(el, value) {
    if (!el) return;
    el.textContent = String(value == null ? "" : value);
  }

  function toInt(value, fallback = 0) {
    const parsed = Number.parseInt(String(value || ""), 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function toLowerSafe(value) {
    return String(value || "")
      .trim()
      .toLowerCase();
  }

  function toPercent(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return "0%";
    return `${Math.round(parsed * 100)}%`;
  }

  function getApiBaseCandidates() {
    const candidates = new Set();
    const origin = (window && window.location ? window.location.origin : "").toLowerCase();
    if (origin && origin !== "null") {
      candidates.add(origin);
    }
    const hostOnly = origin ? origin.replace(/:\d+$/, "") : "";
    const isLocalHost = origin.includes("127.0.0.1") || origin.includes("localhost");
    if (!isLocalHost) {
      if (hostOnly && hostOnly !== origin) {
        candidates.add(hostOnly);
      }
      if (hostOnly && !hostOnly.endsWith("://")) {
        candidates.add("http://127.0.0.1");
        candidates.add("http://localhost");
      }
    }

    const endpoints = [];
    for (const baseRaw of Array.from(candidates)) {
      const base = String(baseRaw || "").replace(/\/$/, "");
      if (base) endpoints.push(`${base}${KIL_REVIEW_API_PATH}`);
      for (const port of KIL_REVIEW_FALLBACK_PORTS) {
        const host = baseRaw.replace(/\/$/, "").replace(/:\d+$/, "");
        if (host) {
          endpoints.push(`${host}:${port}${KIL_REVIEW_API_PATH}`);
        }
      }
    }

    if (!endpoints.length) {
      endpoints.push(KIL_REVIEW_API_PATH);
    }

    return Array.from(new Set(endpoints));
  }

  function parseDate(value) {
    const text = String(value || "").trim();
    if (!text) return null;
    const direct = Date.parse(text);
    if (!Number.isNaN(direct)) {
      return new Date(direct);
    }
    const yyyyMmDd = text.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (yyyyMmDd) {
      return new Date(Number(yyyyMmDd[1]), Number(yyyyMmDd[2]) - 1, Number(yyyyMmDd[3]));
    }
    const yyyySlash = text.match(/(\d{4})\/(\d{1,2})\/(\d{1,2})/);
    if (yyyySlash) {
      return new Date(Number(yyyySlash[1]), Number(yyyySlash[2]) - 1, Number(yyyySlash[3]));
    }
    return null;
  }

  function deadlineStatus(value) {
    const deadline = parseDate(value);
    if (!deadline) return "no_deadline";

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const target = new Date(deadline.getFullYear(), deadline.getMonth(), deadline.getDate());
    const diffDays = Math.floor((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));

    if (diffDays < 0) return "overdue";
    if (diffDays <= 7) return "due_within_7d";
    return "normal";
  }

  function toDeadlineBadge(value) {
    const state = deadlineStatus(value);
    if (state === "no_deadline") return "期限なし";
    if (state === "overdue") return "期限超過";
    if (state === "due_within_7d") return "7日以内";
    return "期限内";
  }

  function isReviewTarget(item) {
    const status = deadlineStatus(item?.deadline);
    const risk = toLowerSafe(item?.risk);
    return status === "overdue" || status === "due_within_7d" || (risk && ![
      "normal",
      "low",
      "info",
      "none",
      "",
    ].includes(risk));
  }

  function renderSummary(payload) {
    const review = payload.review || {};
    const overdue = toInt(review.overdue, 0);
    const dueSoon = toInt(review.due_within_7d, 0);
    const noDeadline = toInt(review.no_deadline, 0);
    const total = toInt(payload.count, 0);
    const reviewNeeded = overdue + dueSoon;

    setText(sourceUsedEl, payload.source_used || payload.requested_source || "-");
    setText(countEl, total);
    setText(reviewNeededEl, reviewNeeded);
    setText(indexCountEl, toInt(payload.source_counts?.index, 0));
    setText(markdownCountEl, toInt(payload.source_counts?.markdown, 0));
    setText(overdueEl, overdue);
    setText(dueSoonEl, dueSoon);
    setText(noDeadlineEl, noDeadline);
    setText(generatedAtEl, payload.generated_at ? String(payload.generated_at) : "-");

    if (summaryLineEl) {
      const line = `要レビュー: ${reviewNeeded}件（期限超過 ${overdue}件 / 7日以内 ${dueSoon}件） / 合計 ${total}件`;
      setText(summaryLineEl, line);
    }
  }

  function renderFiles(payload) {
    if (!filesEl) return;
    const files = payload.data_files || {};
    const indexPath = String(files.index_path || "AGENT_BRAIN_INDEX.jsonl");
    const markdownPath = String(files.markdown_path || "AGENT_BRAIN.md");
    const indexState = files.index_exists ? "有効" : "未作成";
    const mdState = files.markdown_exists ? "有効" : "未作成";

    filesEl.innerHTML = "";
    const li1 = document.createElement("li");
    li1.textContent = `${indexPath}（${indexState}）`;
    const li2 = document.createElement("li");
    li2.textContent = `${markdownPath}（${mdState}）`;
    filesEl.appendChild(li1);
    filesEl.appendChild(li2);
  }

  function renderHealth(payload) {
    if (!healthStatusEl || !healthScoreEl || !healthLagCommitsEl || !healthLagDaysEl || !healthFallbackEl || !healthAnalyzedAtEl || !healthAnalyzedCommitEl || !healthMessageEl) {
      return;
    }

    const health = payload.health || {};
    const score = toInt(health.score, 0);
    const status = String(health.status || "warning");
    const statusLabel = String(health.status_label || "要確認");

    const lagCommits = health.lag_commits;
    const lagDays = health.lag_days;

    const statusClass = `kil-review-health-status-${status}`;
    const oldClasses = String(healthStatusEl.className || "")
      .split(" ")
      .filter((cls) => Boolean(cls) && !cls.startsWith("kil-review-health-status-"));
    oldClasses.push(statusClass);
    healthStatusEl.className = oldClasses.join(" ").trim();

    setText(healthStatusEl, statusLabel);
    setText(healthScoreEl, `${score}点`);
    setText(healthLagCommitsEl, lagCommits == null ? "-" : String(toInt(lagCommits, 0)));
    setText(healthLagDaysEl, lagDays == null ? "-" : `${toInt(lagDays, 0)}日`);
    setText(healthFallbackEl, `${toPercent(health.fallback_ratio)} / ${toInt(health.fallback_records, 0)}件`);
    setText(healthAnalyzedAtEl, health.analyzed_at || "-");
    setText(healthAnalyzedCommitEl, health.analyzed_commit || "unknown");
    setText(healthMessageEl, health.message || "学習ヘルス情報を取得しました。");
  }

  function renderRisk(payload) {
    if (!riskGridEl) return;
    const entries = payload.risk_counts || {};
    const keys = Object.keys(entries);
    riskGridEl.innerHTML = "";

    if (!keys.length) {
      riskGridEl.innerHTML = `<div class="muted">リスク集計データがありません</div>`;
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
    const reviewItems = items.filter(isReviewTarget);

    itemsEl.innerHTML = "";
    if (!items.length) {
      emptyEl.classList.remove("hidden");
      setText(emptyEl, "データがありません。")
      return;
    }
    if (!reviewItems.length) {
      emptyEl.classList.remove("hidden");
      setText(emptyEl, "今回の対象ではレビュー対象の項目はありません。")
      return;
    }
    emptyEl.classList.add("hidden");

    reviewItems.forEach((item) => {
      const row = document.createElement("li");
      row.className = "kil-review-item";

      const head = document.createElement("div");
      head.className = "kil-review-item-head";

      const title = document.createElement("span");
      title.className = "kil-review-item-title";
      const commit = String(item.commit || "").trim() || "unknown";
      const sourceName = String(item.source || "-");
      const deadlineStatusLabel = toDeadlineBadge(item.deadline);
      title.textContent = `${sourceName} / ${commit.slice(0, 8)}...`;

      const date = document.createElement("span");
      date.className = "muted";
      date.textContent = String(item.date || "-");

      head.appendChild(title);
      head.appendChild(date);

      const summary = document.createElement("p");
      summary.className = "kil-review-item-summary";
      summary.textContent = String(item.summary || "").trim() || "要約がありません";

      const meta = document.createElement("div");
      meta.className = "kil-review-item-meta";

      const risk = document.createElement("span");
      risk.className = "kil-review-chip";
      risk.textContent = `リスク: ${String(item.risk || "normal")}`;

      const deadline = document.createElement("span");
      deadline.className = "kil-review-chip";
      deadline.textContent = `期限: ${deadlineStatusLabel}`;

      const action = document.createElement("span");
      action.className = "kil-review-chip";
      action.textContent = "要レビュー";

      const details = document.createElement("details");
      const detailSummary = document.createElement("summary");
      detailSummary.textContent = "詳細（必要なときのみ）";
      const body = document.createElement("pre");
      body.className = "log";
      const detailPayload = {
        commit: item.commit || "",
        knowledge: item.knowledge || [],
        rules: item.rules || [],
        context: item.context || [],
      };
      body.textContent = JSON.stringify(detailPayload, null, 2);

      meta.appendChild(risk);
      meta.appendChild(deadline);
      meta.appendChild(action);

      details.appendChild(detailSummary);
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
      refreshButton.textContent = state ? "更新中..." : "更新";
    }

    if (statusEl) {
      statusEl.textContent = state ? "読み込み中..." : statusEl.textContent;
    }
  }

  function fetchWithTimeout(url, options = {}, timeoutMs = KIL_REVIEW_REQUEST_TIMEOUT_MS) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      controller.abort();
    }, timeoutMs);

    return fetch(url, { ...options, signal: controller.signal })
      .finally(() => {
        window.clearTimeout(timeoutId);
      })
      .catch((error) => {
        if (error?.name === "AbortError") {
          throw new Error(`タイムアウト: ${timeoutMs}ms`);
        }
        throw error;
      });
  }

  async function fetchKilReview() {
    if (!sourceSelect || !limitSelect) return;

    const source = sourceSelect.value || "auto";
    const limit = Number.parseInt(String(limitSelect.value || "20"), 10) || 20;
    const params = new URLSearchParams({ source, limit: String(limit) });
    const candidates = getApiBaseCandidates();

    setBusy(true);
    setText(statusEl, "取得中...");
    setText(summaryLineEl, "取得中...");

    try {
      let payload = null;
      let lastError = "unknown";

      for (const base of candidates) {
        const url = `${base}?${params}`;
        try {
          const res = await fetchWithTimeout(url, { cache: "no-store" });
          if (!res.ok) {
            const detail = await res.json().catch(() => ({}));
            lastError = `${url} -> HTTP ${res.status}: ${toFriendlyMessage(detail.detail || `HTTP ${res.status}`)}`;
            continue;
          }
          const data = await res.json().catch(() => ({}));
          if (data && typeof data === "object") {
            payload = data;
            break;
          }
          lastError = `${url} -> 応答が空または不正です`;
        } catch (error) {
          lastError = `${url} -> ${error?.message ? String(error.message) : "Request failed"}`;
        }
      }

      if (!payload) {
        throw new Error(`KIL Review API 取得に失敗しました: ${lastError}`);
      }

      renderSummary(payload || {});
      renderFiles(payload || {});
      renderRisk(payload || {});
      renderHealth(payload || {});
      renderItems(payload || {});

      setText(statusEl, "最終更新: " + new Date().toLocaleString("ja-JP"));
      showToast("KIL Review を更新しました", "success");
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "KIL Review の取得に失敗しました");
      setText(statusEl, message);
      setText(summaryLineEl, "取得失敗。後で再読み込みしてください。");
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
