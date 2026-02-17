(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));

  const sourceSelect = document.getElementById("kil-review-source");
  const limitSelect = document.getElementById("kil-review-limit");
  let reviewOnlySelect = document.getElementById("kil-review-only-review");
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
  const KIL_REVIEW_API_PATH = "/api/kil-review";
  const KIL_REVIEW_FALLBACK_PORTS = ["8765", "8000"];

  (function ensureReviewOnlyToggle() {
    if (reviewOnlySelect || !statusEl) {
      return;
    }

    const container = statusEl.closest(".kil-review-toolbar-controls");
    if (!container) {
      return;
    }

    reviewOnlySelect = document.createElement("input");
    reviewOnlySelect.type = "checkbox";
    reviewOnlySelect.id = "kil-review-only-review";

    const label = document.createElement("label");
    label.className = "inline-check";
    label.appendChild(reviewOnlySelect);
    label.appendChild(document.createTextNode(" 繝ｬ繝薙Η繝ｼ蟇ｾ雎｡縺ｮ縺ｿ"));
    container.insertBefore(label, statusEl);
  })();

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

    const isLocalHost = origin.includes("127.0.0.1") || origin.includes("localhost");
    if (!isLocalHost) {
      candidates.add("http://127.0.0.1");
      candidates.add("http://localhost");
    }

    const endpoints = [];
    for (const baseRaw of Array.from(candidates)) {
      const base = String(baseRaw || "").replace(/\/$/, "");
      endpoints.push(`${base}${KIL_REVIEW_API_PATH}`);
      const hostOnly = base.replace(/:\d+$/, "");
      for (const port of KIL_REVIEW_FALLBACK_PORTS) endpoints.push(`${hostOnly}:${port}${KIL_REVIEW_API_PATH}`);
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
    if (state === "no_deadline") return "譛ｪ險ｭ螳・;
    if (state === "overdue") return "譛滄剞雜・℃";
    if (state === "due_within_7d") return "7譌･莉･蜀・;
    return "譛滄剞縺ゅｊ";
  }

  function isReviewTarget(item) {
    const needsHumanReview = item?.needs_human_review;
    if (typeof needsHumanReview === "boolean") {
      return needsHumanReview;
    }

    const status = deadlineStatus(item?.deadline);
    const severity = toLowerSafe(item?.review_severity || item?.risk);

    if (status === "overdue" || status === "due_within_7d") {
      return true;
    }
    if (status === "no_deadline") {
      return false;
    }
    return severity === "high" || severity === "critical";
  }

  function renderSummary(payload) {
    const review = payload.review || {};
    const reviewCounts = payload.review_counts || {};
    const overdue = toInt(review.overdue, 0);
    const dueSoon = toInt(review.due_within_7d, 0);
    const noDeadline = toInt(review.no_deadline, 0);
    const total = toInt(payload.count, 0);
    const humanReviewRequired = toInt(reviewCounts.human_review_required, 0);
    const hasReviewCounts = humanReviewRequired > 0 || toInt(reviewCounts.human_review_soon, 0) > 0;
    const reviewNeeded = hasReviewCounts ? humanReviewRequired : overdue + dueSoon;

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
      const line = `隕√Ξ繝薙Η繝ｼ: ${reviewNeeded}莉ｶ・域悄髯占ｶ・℃ ${overdue}莉ｶ / 7譌･莉･蜀・${dueSoon}莉ｶ・・/ 蜈ｨ莉ｶ ${total}莉ｶ`;
      setText(summaryLineEl, line);
    }
  }

  function renderHealth(payload) {
    const health = payload.health || {};
    if (!healthStatusEl || !healthScoreEl || !healthLagCommitsEl || !healthLagDaysEl || !healthFallbackEl || !healthAnalyzedAtEl || !healthAnalyzedCommitEl || !healthMessageEl) {
      return;
    }
    const score = toInt(health.score, 0);
    const statusLabel = String(health.status_label || "隕∫｢ｺ隱・);
    const status = String(health.status || "warning");
    const lagCommits = health.lag_commits;
    const lagDays = health.lag_days;

    const statusClass = `kil-review-health-status-${status}`;
    const oldClasses = String(healthStatusEl.className || "")
      .split(" ")
      .filter((cls) => Boolean(cls) && !cls.startsWith("kil-review-health-status-"));
    oldClasses.push(statusClass);
    healthStatusEl.className = oldClasses.join(" ").trim();

    setText(healthStatusEl, statusLabel);
    setText(healthScoreEl, `${score}轤ｹ`);
    setText(healthLagCommitsEl, lagCommits == null ? "-" : String(toInt(lagCommits, 0)));
    setText(healthLagDaysEl, lagDays == null ? "-" : `${toInt(lagDays, 0)}譌･`);
    setText(healthFallbackEl, `${toPercent(health.fallback_ratio)}・・{toInt(health.fallback_records, 0)}莉ｶ・荏);
    setText(healthAnalyzedAtEl, health.analyzed_at || "-");
    setText(healthAnalyzedCommitEl, health.analyzed_commit || "unknown");
    setText(healthMessageEl, health.message || "蟄ｦ鄙堤憾諷九ｒ蜿門ｾ励〒縺阪∪縺帙ｓ縲・);
  }

  function renderFiles(payload) {
    if (!filesEl) return;
    const files = payload.data_files || {};
    const indexPath = String(files.index_path || "AGENT_BRAIN_INDEX.jsonl");
    const markdownPath = String(files.markdown_path || "AGENT_BRAIN.md");
    const candidates = Array.isArray(files.docs_dir_diagnostics)
      ? files.docs_dir_diagnostics
      : Array.isArray(files.docs_dir_candidates)
      ? files.docs_dir_candidates.map((path) => ({
          path,
          status: "legacy",
          label: "candidate",
        }))
      : [];
    const indexState = files.index_exists ? "縺ゅｊ" : "縺ｪ縺・;
    const mdState = files.markdown_exists ? "縺ゅｊ" : "縺ｪ縺・;

    filesEl.innerHTML = "";
    const li1 = document.createElement("li");
    li1.textContent = `${indexPath} / ${indexState}`;
    const li2 = document.createElement("li");
    li2.textContent = `${markdownPath} / ${mdState}`;
    filesEl.appendChild(li1);
    filesEl.appendChild(li2);
    const li3 = document.createElement("li");
    const selected = candidates.find((entry) => entry.selected);
    if (selected && selected.path) {
      li3.textContent = `AGENT_BRAIN search target: ${selected.path} (${selected.status || "selected"})`;
    } else {
      li3.textContent = `AGENT_BRAIN search target: ${candidates.length ? candidates[0].path : "-"}`;
    }
    if (!candidates.length) {
      li3.title = "No diagnostics for AGENT_BRAIN directory candidates.";
    } else if (selected && typeof selected.path === "string") {
      li3.title = selected.path;
    } else {
      li3.title = String(candidates.map((entry) => `${entry.label || "candidate"}: ${entry.path}`).join(" | "));
    }
    filesEl.appendChild(li3);

    const li4 = document.createElement("li");
    li4.textContent = "AGENT_BRAIN candidate list:";
    filesEl.appendChild(li4);

    if (!candidates.length) {
      const liNone = document.createElement("li");
      liNone.textContent = "-";
      filesEl.appendChild(liNone);
    } else {
      candidates.forEach((candidate) => {
        const hasFiles = candidate.contains_index || candidate.contains_markdown || candidate.contains_review ? "yes" : "no";
        const marker = candidate.selected ? "*" : "-";
        const status = candidate.status || "unknown";
        const line = document.createElement("li");
        line.textContent = `${marker} ${candidate.label || "candidate"}: ${candidate.path || "-"} / files=${hasFiles} / ${status}`;
        filesEl.appendChild(line);
      });
    }
  }

  function riskLabel(value) {
    switch (value) {
      case "high":
        return "鬮・;
      case "medium":
        return "荳ｭ";
      case "low":
        return "菴・;
      default:
        return value || "荳肴・";
    }
  }

  function renderRisk(payload) {
    if (!riskGridEl) return;
    const entries = payload.risk_counts || {};
    const keys = Object.keys(entries);
    riskGridEl.innerHTML = "";

    if (!keys.length) {
      riskGridEl.innerHTML = `<div class="muted">繝ｪ繧ｹ繧ｯ諠・ｱ縺後≠繧翫∪縺帙ｓ</div>`;
      return;
    }

    keys
      .sort((a, b) => entries[b] - entries[a])
      .forEach((name) => {
        const card = document.createElement("div");
        card.className = "kil-review-stat";

        const label = document.createElement("span");
        label.className = "label";
        label.textContent = riskLabel(name);

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
    const showOnlyReview = Boolean(reviewOnlySelect && reviewOnlySelect.checked);
    const reviewItems = items.filter(isReviewTarget);
    const visibleItems = showOnlyReview ? items.filter((item) => item?.needs_human_review === true) : reviewItems;

    itemsEl.innerHTML = "";
    if (!items.length) {
      emptyEl.classList.remove("hidden");
      setText(emptyEl, "繝・・繧ｿ縺後≠繧翫∪縺帙ｓ");
      return;
    }
    if (!visibleItems.length) {
      emptyEl.classList.remove("hidden");
      setText(emptyEl, "隕√Ξ繝薙Η繝ｼ蟇ｾ雎｡縺ｯ縺ゅｊ縺ｾ縺帙ｓ・郁ｨｭ螳壹ｒ隕狗峩縺励※縺上□縺輔＞・・);
      return;
    }

    emptyEl.classList.add("hidden");

    visibleItems.forEach((item) => {
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
      summary.textContent = String(item.summary || "").trim() || "隕∫ｴ・↑縺・;

      const reviewIssues = Array.isArray(item.review_issues) ? item.review_issues.filter(Boolean) : [];
      const reviewRecommendations = Array.isArray(item.review_recommendations)
        ? item.review_recommendations.filter(Boolean)
        : [];
      if (item?.needs_human_review) {
        const reason = document.createElement("p");
        reason.className = "kil-review-item-summary";
        if (reviewIssues.length > 0) {
          reason.textContent = `レビュー理由: ${String(reviewIssues[0])}`;
        } else {
          reason.textContent = "レビュー理由: 要レビュー条件に該当しました（要件: 期限超過/高リスク/Confidenceしきい値下回り）。再実行して理由を確認してください。";
        }
        row.appendChild(reason);
      } else if (toLowerSafe(item?.review_severity) === "high" || toLowerSafe(item?.review_severity) === "critical") {
        const reason = document.createElement("p");
        reason.className = "kil-review-item-summary";
        reason.textContent = "レビュー理由: 高リスク差分として自動分類（要レビュー情報が未取得）";
        row.appendChild(reason);
      } else if (reviewRecommendations.length > 0) {
        const recommendation = document.createElement("p");
        recommendation.className = "kil-review-item-summary";
        recommendation.textContent = `次アクション: ${String(reviewRecommendations[0])}`;
        row.appendChild(recommendation);
      }

      const meta = document.createElement("div");
      meta.className = "kil-review-item-meta";

      const risk = document.createElement("span");
      risk.className = "kil-review-chip";
      risk.textContent = `驥崎ｦ∝ｺｦ: ${String(item.risk || "normal")}`;

      const deadline = document.createElement("span");
      deadline.className = "kil-review-chip";
      deadline.textContent = `譛滄剞: ${deadlineStatusLabel}`;

      const action = document.createElement("span");
      action.className = "kil-review-chip";
      action.textContent = item?.needs_human_review ? "要レビュー" : "自動判定済み";

      const details = document.createElement("details");
      const detailSummary = document.createElement("summary");
      detailSummary.textContent = "螻暮幕縺励※遒ｺ隱・;
      const body = document.createElement("pre");
      body.className = "log";
      const detailPayload = {
        commit: item.commit || "",
        needs_human_review: !!item.needs_human_review,
        needs_soon: !!item.needs_soon,
        review_severity: item.review_severity || item.risk || "",
        review_issues: item.review_issues || [],
        review_recommendations: item.review_recommendations || [],
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
      refreshButton.textContent = state ? "譖ｴ譁ｰ荳ｭ..." : "譖ｴ譁ｰ";
    }

    if (statusEl) {
      statusEl.textContent = state ? "隱ｭ縺ｿ霎ｼ縺ｿ荳ｭ..." : statusEl.textContent;
    }
  }

  async function fetchKilReview() {
    if (!sourceSelect || !limitSelect) return;

    const source = sourceSelect.value || "auto";
    const limit = Number.parseInt(String(limitSelect.value || "20"), 10) || 20;
    const params = new URLSearchParams({ source, limit: String(limit) });
    if (reviewOnlySelect && reviewOnlySelect.checked) {
      params.set("only_review", "1");
    }

    setBusy(true);
    setText(statusEl, "蜿門ｾ嶺ｸｭ...");
    setText(summaryLineEl, "蜿門ｾ嶺ｸｭ...");

    try {
      let lastError = "unknown";
      let payload = null;
      for (const base of getApiBaseCandidates()) {
        const url = `${base}?${params}`;
        try {
          const res = await fetch(url, { cache: "no-store" });
          if (!res.ok) {
            const detail = await res.json().catch(() => ({}));
            lastError = `${url} -> HTTP ${res.status}: ${toFriendlyMessage(detail.detail || "Request failed")}`;
            continue;
          }
          payload = await res.json().catch(() => ({}));
          if (payload) {
            break;
          }
          lastError = `${url} -> 遨ｺ繝ｬ繧ｹ繝昴Φ繧ｹ`;
          break;
        } catch (error) {
          lastError = `${url} -> ${error?.message ? String(error.message) : "Request failed"}`;
          continue;
        }
      }

      if (!payload) {
        throw new Error(`KIL Review API 縺ｮ蜿門ｾ励↓螟ｱ謨励＠縺ｾ縺励◆縲・{lastError}`);
      }

      renderSummary(payload || {});
      renderHealth(payload || {});
      renderFiles(payload || {});
      renderRisk(payload || {});
      renderItems(payload || {});

      setText(statusEl, "譖ｴ譁ｰ: " + new Date().toLocaleString("ja-JP"));
      showToast("KIL Review 繧呈峩譁ｰ縺励∪縺励◆", "success");
    } catch (error) {
      const message = toFriendlyMessage(error?.message || "KIL Review 縺ｮ蜿門ｾ励↓螟ｱ謨励＠縺ｾ縺励◆");
      setText(statusEl, message);
      setText(summaryLineEl, "蜿門ｾ励↓螟ｱ謨励＠縺ｾ縺励◆");
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

  if (reviewOnlySelect) {
    reviewOnlySelect.addEventListener("change", () => {
      void fetchKilReview();
    });
  }

  void fetchKilReview();
})();


