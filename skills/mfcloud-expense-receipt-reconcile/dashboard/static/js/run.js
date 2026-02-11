(function () {
  const Common = window.DashboardCommon || {};
  const showToast = Common.showToast || (() => {});
  const toFriendlyMessage = Common.toFriendlyMessage || ((text) => String(text || ""));
  const bindCopyButtons = Common.bindCopyButtons || (() => {});

  const SOURCE_LABELS = {
    amazon: "Amazon",
    rakuten: "楽天",
  };

  const excludeSection = document.getElementById("exclude-section");
  const excludeButtons = Array.from(document.querySelectorAll(".exclude-save"));
  const printCompleteButtons = Array.from(document.querySelectorAll(".print-complete"));
  const excludeStatus = document.getElementById("exclude-status");
  const excludeSummary = document.getElementById("exclude-summary");
  const excludeSummaryCount = document.getElementById("exclude-summary-count");
  const statExcluded = document.getElementById("stat-excluded");
  const statIncluded = document.getElementById("stat-included");
  const openReceiptsFolderButton = document.getElementById("open-receipts-folder");
  const printScriptStatus = document.getElementById("print-script-status");
  const printNextBox = document.getElementById("print-next-box");
  const printNextSummary = document.getElementById("print-next-summary");
  const printNextOpen = document.getElementById("print-next-open");
  const printNextCmd = document.getElementById("print-next-cmd");

  const printPreparedBySource = { amazon: false, rakuten: false };
  const bulkPrintReadyBySource = { amazon: false, rakuten: false };
  const excludeDirtyBySource = { amazon: false, rakuten: false };

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

  function sourceLabel(source) {
    return SOURCE_LABELS[source] || String(source || "");
  }

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

  function setStatus(message, kind) {
    setExcludeStatus(message, kind);
    setPrintScriptStatus(message, kind);
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

  function refreshExcludeDirtyBySource() {
    excludeDirtyBySource.amazon = false;
    excludeDirtyBySource.rakuten = false;
    document.querySelectorAll(".exclude-toggle").forEach((el) => {
      const source = String(el.dataset.source || "").trim();
      if (!(source in excludeDirtyBySource)) return;
      const initialChecked = String(el.dataset.initialChecked || "0") === "1";
      if (initialChecked !== Boolean(el.checked)) {
        excludeDirtyBySource[source] = true;
      }
    });
  }

  function markCurrentToggleStateAsSaved() {
    document.querySelectorAll(".exclude-toggle").forEach((el) => {
      el.dataset.initialChecked = el.checked ? "1" : "0";
    });
    refreshExcludeDirtyBySource();
  }

  function hydrateButtonStateFromDom() {
    excludeButtons.forEach((button) => {
      const source = String(button.dataset.source || "").trim();
      if (!source || !(source in bulkPrintReadyBySource)) return;
      const readyRaw = String(button.dataset.printReady || "").trim().toLowerCase();
      bulkPrintReadyBySource[source] = readyRaw === "1" || readyRaw === "true";
    });
    printCompleteButtons.forEach((button) => {
      const source = String(button.dataset.source || "").trim();
      if (!source || !(source in printPreparedBySource)) return;
      printPreparedBySource[source] = !button.disabled;
    });
    document.querySelectorAll(".exclude-toggle").forEach((el) => {
      if (!Object.prototype.hasOwnProperty.call(el.dataset, "initialChecked")) {
        el.dataset.initialChecked = el.checked ? "1" : "0";
      }
    });
    refreshExcludeDirtyBySource();
  }

  function updateExcludeButtonsLabel() {
    excludeButtons.forEach((button) => {
      const source = String(button.dataset.source || "").trim();
      if (!source) return;
      const label = sourceLabel(source);
      const ready = Boolean(bulkPrintReadyBySource[source]);
      const dirty = Boolean(excludeDirtyBySource[source]);
      if (ready && !dirty) {
        button.dataset.action = "run";
        button.textContent = `${label}一括印刷（結合PDFを開く）`;
        return;
      }
      button.dataset.action = "prepare";
      button.textContent = dirty ? `${label}で保存して印刷対象を更新（変更あり）` : `${label}で保存して印刷対象を更新`;
    });
  }

  function setActionButtonsDisabled(isBusy) {
    excludeButtons.forEach((btn) => {
      btn.disabled = isBusy;
    });
    printCompleteButtons.forEach((btn) => {
      const source = String(btn.dataset.source || "").trim();
      const prepared = source ? Boolean(printPreparedBySource[source]) : false;
      btn.disabled = isBusy || !prepared;
    });
    if (openReceiptsFolderButton) openReceiptsFolderButton.disabled = isBusy;
  }

  function showPrintNextActions({ ym, source, count, printCommand, excludedPdfsUrl }) {
    if (!printNextBox) return;
    const label = sourceLabel(source);
    const normalizedCount = Number.isFinite(count) ? Math.max(0, count) : null;
    if (printNextSummary) {
      if (normalizedCount === null) {
        printNextSummary.textContent = `${label}の印刷対象更新が完了しました。印刷後に「印刷完了を記録」を押してください。`;
      } else {
        printNextSummary.textContent = `${label}の印刷対象 ${normalizedCount} 件を更新しました。印刷後に「印刷完了を記録」を押してください。`;
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
      if (el.checked && orderSource && orderId) {
        items.push({ source: orderSource, order_id: orderId });
      }
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

  async function runBulkPrint(ym, source) {
    const res = await fetch(`/api/print-run/${ym}/${encodeURIComponent(source)}`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || "bulk print run failed");
    }
    const count = Number.parseInt(String(data?.count ?? "0"), 10);
    const missingCount = Number.parseInt(String(data?.missing_count ?? "0"), 10);
    return {
      count: Math.max(0, Number.isFinite(count) ? count : 0),
      missingCount: Math.max(0, Number.isFinite(missingCount) ? missingCount : 0),
    };
  }

  if (excludeSection && (excludeButtons.length || printCompleteButtons.length)) {
    hydrateButtonStateFromDom();
    updateExcludeCounters();
    updateExcludeButtonsLabel();
    setActionButtonsDisabled(false);

    document.querySelectorAll(".exclude-toggle").forEach((el) => {
      el.addEventListener("change", () => {
        updateExcludeCounters();
        refreshExcludeDirtyBySource();
        updateExcludeButtonsLabel();
      });
    });

    excludeButtons.forEach((button) => {
      button.addEventListener("click", async () => {
        const ym = String(excludeSection.dataset.ym || "").trim();
        const source = String(button.dataset.source || "").trim();
        if (!ym || !source) return;
        const label = sourceLabel(source);
        const shouldRunBulkPrint = Boolean(bulkPrintReadyBySource[source]) && !Boolean(excludeDirtyBySource[source]);

        setActionButtonsDisabled(true);

        if (shouldRunBulkPrint) {
          setStatus(`${label}の結合PDFを開いています...`, "success");
          try {
            const result = await runBulkPrint(ym, source);
            const message = `${label}の結合PDFを開きました。対象 ${result.count} 件 / 欠落 ${result.missingCount} 件。`;
            setStatus(message, "success");
            showToast(message, "success");
          } catch (error) {
            const message = toFriendlyMessage(error?.message) || "一括印刷の開始に失敗しました。";
            setStatus(message, "error");
            showToast(message, "error");
          } finally {
            setActionButtonsDisabled(false);
          }
          return;
        }

        printPreparedBySource[source] = false;
        bulkPrintReadyBySource[source] = false;
        updateExcludeButtonsLabel();
        setStatus("除外設定を保存しています。完了までお待ちください。", "success");
        showToast("除外設定を保存しています...", "success");
        try {
          await saveExclusions(ym, source);
          const printResult = await preparePrint(ym, source);
          printPreparedBySource[source] = true;
          bulkPrintReadyBySource[source] = true;
          markCurrentToggleStateAsSaved();
          updateExcludeCounters();
          updateExcludeButtonsLabel();

          const count = Number.parseInt(String(printResult?.count ?? ""), 10);
          const normalizedCount = Number.isFinite(count) ? Math.max(0, count) : null;
          const successMessage =
            normalizedCount !== null
              ? `${label}の印刷対象更新が完了しました（対象 ${normalizedCount} 件）。印刷後に「印刷完了を記録」を押してください。`
              : `${label}の印刷対象更新が完了しました。印刷後に「印刷完了を記録」を押してください。`;
          showPrintNextActions({
            ym,
            source,
            count: normalizedCount,
            printCommand: String(printResult?.print_command || "POST /api/print-run/{ym}/{source}"),
            excludedPdfsUrl: String(printResult?.excluded_pdfs_url || ""),
          });
          setStatus(successMessage, "success");
          showToast(successMessage, "success");
        } catch (error) {
          const message = toFriendlyMessage(error?.message) || "保存または印刷対象更新に失敗しました。";
          setStatus(message, "error");
          showToast(message, "error");
        } finally {
          updateExcludeButtonsLabel();
          setActionButtonsDisabled(false);
        }
      });
    });

    printCompleteButtons.forEach((button) => {
      button.addEventListener("click", async () => {
        const ym = String(excludeSection.dataset.ym || "").trim();
        const source = String(button.dataset.source || "").trim();
        if (!ym || !source) return;
        setActionButtonsDisabled(true);
        try {
          const result = await completePrint(ym, source);
          const count = Number.parseInt(String(result?.count ?? ""), 10);
          const label = sourceLabel(source);
          const doneMessage =
            Number.isFinite(count) && count >= 0
              ? `${label}の印刷完了を記録しました（対象 ${count} 件）。`
              : `${label}の印刷完了を記録しました。`;
          setStatus(doneMessage, "success");
          showToast(doneMessage, "success");
        } catch (error) {
          const message = toFriendlyMessage(error?.message) || "印刷完了の記録に失敗しました。";
          setStatus(message, "error");
          showToast(message, "error");
        } finally {
          setActionButtonsDisabled(false);
          updateExcludeButtonsLabel();
        }
      });
    });
  } else {
    setActionButtonsDisabled(false);
  }

  if (openReceiptsFolderButton) {
    openReceiptsFolderButton.addEventListener("click", async () => {
      const ym = getCurrentYm();
      if (!ym) {
        const message = "対象月が取得できませんでした。ページを再読み込みしてください。";
        setStatus(message, "error");
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
        setStatus(message, "success");
        showToast(message, "success");
      } catch (error) {
        const message = toFriendlyMessage(error?.message) || "フォルダを開けませんでした。";
        setStatus(message, "error");
        showToast(message, "error");
      } finally {
        openReceiptsFolderButton.disabled = false;
      }
    });
  }

  bindCopyButtons();

  const mfDraftViewer = document.querySelector("[data-mf-draft-viewer]");
  const mfDraftFilterInput = document.getElementById("mf-draft-filter");
  const mfDraftRefreshButton = document.getElementById("mf-draft-refresh");
  const mfDraftStatusEl = document.getElementById("mf-draft-status");
  const mfDraftTableBody = document.getElementById("mf-draft-table-body");

  let mfDraftItems = [];
  let mfDraftFilterTimer = null;

  function setMfDraftStatus(message, kind) {
    if (!mfDraftStatusEl) return;
    mfDraftStatusEl.textContent = String(message || "");
    mfDraftStatusEl.classList.remove("success", "error");
    if (kind) mfDraftStatusEl.classList.add(kind);
  }

  function setMfDraftStat(name, value) {
    const el = document.querySelector(`[data-mf-draft-stat=\"${name}\"]`);
    if (!el) return;
    el.textContent = value == null ? "-" : String(value);
  }

  function normalizeSearchText(text) {
    const normalize = Common.normalizeSearchText || ((t) => String(t || "").toLowerCase().replace(/\\s+/g, " ").trim());
    return normalize(text);
  }

  function buildStatusPill(status) {
    const s = String(status || "").trim() || "-";
    const pill = document.createElement("span");
    pill.className = "mf-draft-status-pill";
    if (s === "created") pill.classList.add("created");
    if (s === "failed") pill.classList.add("failed");
    if (s === "skipped") pill.classList.add("skipped");
    pill.textContent = s;
    return pill;
  }

  function formatYen(value) {
    const n = Number.parseInt(String(value ?? ""), 10);
    if (!Number.isFinite(n)) return "-";
    return `${n.toLocaleString("ja-JP")}円`;
  }

  function setEmptyRow(text) {
    if (!mfDraftTableBody) return;
    mfDraftTableBody.innerHTML = "";
    const tr = document.createElement("tr");
    tr.setAttribute("data-mf-draft-empty", "1");
    const td = document.createElement("td");
    td.colSpan = 7;
    td.className = "muted";
    td.textContent = text;
    tr.appendChild(td);
    mfDraftTableBody.appendChild(tr);
  }

  function renderMfDraftTable() {
    if (!mfDraftTableBody) return;
    const q = normalizeSearchText(mfDraftFilterInput?.value || "");

    const filtered = mfDraftItems.filter((item) => {
      if (!q) return true;
      const parts = [
        item.mf_expense_id,
        item.status,
        item.reason,
        item.detail,
        item.order_id,
        item.order_source,
        item.mf_vendor,
        item.mf_memo,
      ];
      return normalizeSearchText(parts.join(" ")).includes(q);
    });

    mfDraftTableBody.innerHTML = "";
    if (!filtered.length) {
      setEmptyRow("該当するログがありません。");
      return;
    }

    filtered.forEach((item) => {
      const tr = document.createElement("tr");

      const tdStatus = document.createElement("td");
      tdStatus.appendChild(buildStatusPill(item.status));
      tr.appendChild(tdStatus);

      const tdId = document.createElement("td");
      tdId.className = "mf-draft-code";
      tdId.textContent = String(item.mf_expense_id || "-");
      tr.appendChild(tdId);

      const tdDateAmount = document.createElement("td");
      const dateText = String(item.mf_use_date || item.row_date || "-");
      tdDateAmount.innerHTML = `<div>${dateText}</div><div class=\"muted\">${formatYen(item.mf_amount_yen ?? item.row_amount_yen)}</div>`;
      tr.appendChild(tdDateAmount);

      const tdSummary = document.createElement("td");
      const vendor = String(item.mf_vendor || "").trim();
      const memo = String(item.mf_memo || "").trim();
      tdSummary.textContent = [vendor, memo].filter(Boolean).join(" / ") || "-";
      tdSummary.className = "wide";
      tr.appendChild(tdSummary);

      const tdOrder = document.createElement("td");
      const orderBits = [];
      if (item.order_source) orderBits.push(String(item.order_source));
      if (item.order_id) orderBits.push(String(item.order_id));
      if (item.order_date) orderBits.push(String(item.order_date));
      if (item.order_total_yen != null) orderBits.push(formatYen(item.order_total_yen));
      tdOrder.textContent = orderBits.join(" / ") || "-";
      tr.appendChild(tdOrder);

      const tdReason = document.createElement("td");
      const reason = String(item.reason || "").trim();
      const detail = String(item.detail || "").trim();
      const validationErrors = Array.isArray(item.validation_errors) ? item.validation_errors : [];
      tdReason.innerHTML = reason ? `<div class=\"mf-draft-code\">${reason}</div>` : "<div class=\"muted\">-</div>";
      if (detail) {
        const d = document.createElement("div");
        d.className = "muted mf-draft-code";
        d.textContent = detail;
        tdReason.appendChild(d);
      }
      if (validationErrors.length) {
        const d = document.createElement("div");
        d.className = "muted mf-draft-code";
        d.textContent = `validation: ${validationErrors.join(" / ")}`;
        tdReason.appendChild(d);
      }
      tr.appendChild(tdReason);

      const tdAutofill = document.createElement("td");
      const filled = Array.isArray(item.autofill) ? item.autofill : [];
      if (!filled.length) {
        tdAutofill.innerHTML = "<span class=\"muted\">-</span>";
      } else {
        tdAutofill.innerHTML = filled
          .map((row) => {
            const field = String(row.field || "");
            const text = String(row.text || "");
            return `<div class=\"mf-draft-code\">${field}:${text}</div>`;
          })
          .join("");
      }
      tr.appendChild(tdAutofill);

      mfDraftTableBody.appendChild(tr);
    });
  }

  async function refreshMfDraftActions() {
    if (!mfDraftViewer) return;
    const ym = String(mfDraftViewer.dataset.ym || "").trim();
    if (!ym) return;

    setMfDraftStatus("MF下書き作成ログを読み込み中...", "success");
    setEmptyRow("ログを読み込み中です。");

    const res = await fetch(`/api/mf-draft-actions/${encodeURIComponent(ym)}`, { cache: "no-store" }).catch(() => null);
    if (!res || !res.ok) {
      setMfDraftStatus("ログの取得に失敗しました。", "error");
      setEmptyRow("ログの取得に失敗しました。");
      return;
    }
    const data = await res.json().catch(() => null);
    const exists = Boolean(data?.exists);
    const summary = data?.summary || {};
    const items = Array.isArray(data?.items) ? data.items : [];

    setMfDraftStat("targets", summary.targets);
    setMfDraftStat("created", summary.created);
    setMfDraftStat("skipped", summary.skipped);
    setMfDraftStat("failed", summary.failed);

    mfDraftItems = items.map((raw) => (raw && typeof raw === "object" ? raw : {}));

    if (!exists) {
      setMfDraftStatus("この月のMF下書き作成ログはありません。", "");
      setEmptyRow("まだ Step5 のログがありません。Step5実行後に表示されます。");
      return;
    }

    const loaded = Number.parseInt(String(data?.events_loaded ?? ""), 10);
    const total = Number.parseInt(String(data?.events_total ?? ""), 10);
    const suffix = Number.isFinite(loaded) && Number.isFinite(total) && total > 0 ? `（events ${loaded}/${total}）` : "";
    setMfDraftStatus(`読み込みました ${suffix}`, "success");
    renderMfDraftTable();
  }

  if (mfDraftViewer) {
    refreshMfDraftActions();

    if (mfDraftRefreshButton) {
      mfDraftRefreshButton.addEventListener("click", () => refreshMfDraftActions());
    }

    if (mfDraftFilterInput) {
      mfDraftFilterInput.addEventListener("input", () => {
        clearTimeout(mfDraftFilterTimer);
        mfDraftFilterTimer = setTimeout(() => {
          renderMfDraftTable();
        }, 180);
      });
    }
  }
})();
