  function getYmFromForm() {
    if (!form) return "";
    const yearEl = form.querySelector("[name=year]");
    const monthEl = form.querySelector("[name=month]");
    return normalizeYm(yearEl?.value, monthEl?.value);
  }

  function setStepStatus(id, state) {
    const el = document.querySelector(`[data-step-status="${id}"]`);
    if (!el) return;
    el.classList.remove("done", "running", "pending");
    if (id === "mf_reconcile" && state !== "running") {
      el.textContent = "未実行";
      el.classList.add("pending");
      return;
    }
    if (state === "done") {
      el.textContent = "完了";
      el.classList.add("done");
      return;
    }
    if (state === "running") {
      el.textContent = "螳溯｡御ｸｭ";
      el.classList.add("running");
      return;
    }
    el.textContent = "未実行";
    el.classList.add("pending");
  }

  function setTaskStatus(id, state) {
    const el = document.querySelector(`[data-task-status="${id}"]`);
    if (!el) return;
    el.classList.remove("done", "running", "pending");
    if (state === "done") {
      el.textContent = "完了";
      el.classList.add("done");
      return;
    }
    if (state === "running") {
      el.textContent = "螳溯｡御ｸｭ";
      el.classList.add("running");
      return;
    }
    el.textContent = "未実行";
    el.classList.add("pending");
  }

  function renderNextStep(message, href, reason = "", linkLabel = "") {
    if (!wizardNext) return;
    wizardNext.innerHTML = "";
    if (!message) {
      wizardNext.classList.add("hidden");
      return;
    }
    wizardNext.classList.remove("hidden");
    const text = document.createElement("span");
    text.textContent = message;
    wizardNext.appendChild(text);
    if (reason) {
      const reasonEl = document.createElement("span");
      reasonEl.className = "muted next-step-reason";
      reasonEl.textContent = reason;
      wizardNext.appendChild(reasonEl);
    }
    if (!href) return;
    const link = document.createElement("a");
    link.href = href;
    link.className = "secondary";
    link.textContent = String(linkLabel || "(msg)").trim() || "(msg)";
    if (String(href || "").trim().startsWith("#")) {
      link.href = href;
      link.addEventListener("click", (event) => {
        event.preventDefault();
        navigateToStep(href);
      });
    }
    wizardNext.appendChild(link);
  }

  const FALLBACK_WIZARD_HREF = "#wizard";
  const FALLBACK_GUIDANCE_LIMIT = 8;

  function recordWizardFallback({ type, runningMode = "", nextStep = "", nextStepReason = "", href = "" }) {
    const entry = {
      ts: Date.now(),
      type: String(type || "").trim() || "unknown",
      runningMode: String(runningMode || "").trim(),
      nextStep: String(nextStep || "").trim(),
      nextStepReason: String(nextStepReason || "").trim(),
      href: String(href || FALLBACK_WIZARD_HREF).trim() || FALLBACK_WIZARD_HREF,
    };
    const log = Array.isArray(window.__wizardFallbackLog) ? window.__wizardFallbackLog : [];
    const last = log.length ? log[log.length - 1] : null;
    const shouldAppend =
      !last ||
      last.type !== entry.type ||
      last.runningMode !== entry.runningMode ||
      last.nextStep !== entry.nextStep ||
      last.nextStepReason !== entry.nextStepReason ||
      last.href !== entry.href;
    if (shouldAppend) {
      log.push(entry);
      if (log.length > FALLBACK_GUIDANCE_LIMIT) {
        log.shift();
      }
      window.__wizardFallbackLog = log;
    }
    const wizard = document.getElementById("wizard");
    if (!wizard) return;
    wizard.dataset.nextStepFallbackType = entry.type;
    wizard.dataset.nextStepFallbackStep = entry.nextStep;
    wizard.dataset.nextStepFallbackMode = entry.runningMode;
    wizard.dataset.nextStepFallbackReason = entry.nextStepReason;
    wizard.dataset.nextStepFallbackHref = entry.href;
    wizard.dataset.nextStepFallbackAt = String(entry.ts);
    wizard.dataset.nextStepFallbackCount = String(log.length);
  }

  function navigateToStep(href) {
    if (!href || typeof href !== "string") return;
    const id = href.trim();
    if (!id.startsWith("#")) return;
    const target = document.querySelector(id);
    if (!target) {
      showToast("(msg)", "warning");
      return;
    }

    if (stepFocusTimer) {
      clearTimeout(stepFocusTimer);
      stepFocusTimer = null;
    }

    target.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    const hadTabIndex = target.hasAttribute("tabindex");
    target.setAttribute("tabindex", "-1");
    const focusTarget =
      target.matches("button, a, input, select, textarea, [tabindex]")
      ? target
      : target.querySelector("button, a, input, select, textarea, [tabindex]");
    const focusable = focusTarget || target;
    if (typeof focusable.focus === "function") {
      try {
        focusable.focus({ preventScroll: true });
      } catch {
        focusable.focus();
      }
    }
    target.classList.add("step-focus");
    stepFocusTimer = setTimeout(() => {
      target.classList.remove("step-focus");
      if (!hadTabIndex) {
        target.removeAttribute("tabindex");
      }
      stepFocusTimer = null;
    }, 1400);
  }

  function inferNextStepFromFlags(data) {
    if (!data || typeof data !== "object") return "done";
    if (!data.preflight?.done) return "preflight";
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    const amazonPending = Boolean(data.amazon?.downloaded && !amazonDone);
    const rakutenPending = Boolean(data.rakuten?.downloaded && !rakutenDone);
    const providerPendingCount = Number.parseInt(String(data.providers?.pending_total ?? 0), 10);
    const providerPending = Number.isFinite(providerPendingCount) ? providerPendingCount > 0 : false;
    if (amazonPending) return "amazon_decide_print";
    if (rakutenPending) return "rakuten_decide_print";
    if (!data.amazon?.downloaded && !data.rakuten?.downloaded) return "amazon_or_rakuten_download";
    if (!data.amazon?.downloaded) return "amazon_download";
    if (!data.rakuten?.downloaded) return "rakuten_download";
    if (providerPending) return "provider_ingest";
    const mfDone = Boolean(data.mf?.step_done ?? data.mf?.reconciled);
    if (!mfDone && (Boolean(data.mf_bulk_upload?.done || data.mf_csv_import?.done))) return "mf_bulk_upload_task";
    const canReconcile =
      "can_reconcile" in data ? Boolean(data.can_reconcile) : (Boolean(data.amazon?.downloaded || data.rakuten?.downloaded) && !(amazonPending || rakutenPending));
    if (!mfDone && canReconcile) return "mf_reconcile";
    if (!mfDone) return "mf_reconcile";
    return "done";
  }

  const KNOWN_NEXT_STEP_VALUES = new Set([
      "preflight_mf",
      "preflight",
      "amazon_or_rakuten_download",
      "amazon_download",
      "amazon_decide_print",
      "rakuten_download",
      "rakuten_decide_print",
      "amazon_print",
      "rakuten_print",
      "provider_ingest",
      "import_provider_receipts",
      "mf_bulk_upload_task",
      "mf_bulk_upload",
      "mf_csv_import",
      "mf_reconcile",
      "done",
  ]);

  function normalizeNextStepValue(rawValue) {
    return String(rawValue || "").trim().toLowerCase();
  }

  function isKnownNextStep(rawValue) {
    return KNOWN_NEXT_STEP_VALUES.has(normalizeNextStepValue(rawValue));
  }

  function resolveNextStep(data) {
    const apiNextStep = normalizeNextStepValue(data?.next_step);
    if (isKnownNextStep(apiNextStep)) {
      return apiNextStep;
    }
    const inferred = inferNextStepFromFlags(data);
    if (apiNextStep) {
      recordWizardFallback({
        type: "next_step_unknown",
        runningMode: String(data?.running_mode || ""),
        nextStep: apiNextStep,
        nextStepReason: String(data?.next_step_reason || "").trim(),
        href: FALLBACK_WIZARD_HREF,
      });
    }
    return inferred;
  }

  function formatArchiveTimeForDisplay(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    const normalized = text.includes("T") ? text : text.replace(" ", "T");
    if (/(Z|[+-]\d{2}:?\d{2})$/.test(normalized)) {
      const jstText = formatDateTimeInJst(normalized);
      if (jstText) return `${jstText} JST`;
    }
    const basicMatch = normalized.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/);
    if (basicMatch) return `${basicMatch[1]} ${basicMatch[2]} JST`;
    return text;
  }

  function archivePageHref(ym) {
    const value = String(ym || "").trim();
    if (!/^\d{4}-\d{2}$/.test(value)) return "";
    const wizard = document.getElementById("wizard");
    const template = String(wizard?.dataset?.archiveHrefTemplate || "").trim();
    if (template && template.includes("__YM__")) {
      return template.replace("__YM__", encodeURIComponent(value));
    }
    return `/runs/${value}/archived-receipts`;
  }

  function applyArchivePageLink(ym) {
    document.querySelectorAll("[data-archive-page-link]").forEach((link) => {
      if (!(link instanceof HTMLAnchorElement)) return;
      const fallbackHref = String(link.dataset.fallbackHref || link.getAttribute("href") || "").trim();
      const href = archivePageHref(ym) || fallbackHref || "#";
      link.href = href;
      if (href === "#") {
        link.classList.add("disabled");
        link.setAttribute("aria-disabled", "true");
        link.setAttribute("tabindex", "-1");
      } else {
        link.classList.remove("disabled");
        link.removeAttribute("aria-disabled");
        link.removeAttribute("tabindex");
      }
    });
  }

  function computeNextStep(data, ym) {
    const nextStep = resolveNextStep(data);
    const apiNextStep = normalizeNextStepValue(data?.next_step);
    const apiNextStepWasUnknown = apiNextStep && !isKnownNextStep(apiNextStep);
    const nextStepKey = String(nextStep || "").trim();
    const runningMode = String(data?.running_mode || "").trim();
    const nextStepReasonCode = String(data?.next_step_reason || "").trim();
    const nextStepGuidance = {
      preflight: {
        message: "準備フローを確認してください。",
        reason: "対象ワークフローの実行条件を確認してから次の工程へ進めてください。",
        linkLabel: "貅門ｙ蟾･遞九∈",
      },
      amazon_or_rakuten_download: {
        message: "まずは Amazon か楽天のいずれかの領収書取得を先に実行してください。",
        reason: "少なくとも1社分の領収書取得が必要です。未取得があると次の処理に進めません。",
        linkLabel: "Amazon／楽天 取得へ",
      },
      amazon_download: {
        message: "Amazon の領収書を取得してください。",
        reason: "Amazon 側の対象月データを取得して、次の除外判断・印刷へ進みます。",
        linkLabel: "Amazon 取得へ",
      },
      amazon_decide_print: {
        message: "Amazon の除外設定・印刷対象を確認してください。",
        reason: "除外対象を確定して印刷完了まで進めると状態が保存されます。",
        linkLabel: "Amazon 除外・印刷へ",
      },
      amazon_print: {
        message: "Amazonの印刷完了待ちステータスを確認してください。",
        reason: "Amazonの印刷処理が完了し、必要に応じて確認・反映を行ってください。",
        linkLabel: "Amazonの印刷ステータスへ",
      },
      rakuten_download: {
        message: "楽天の領収書を取得してください。",
        reason: "楽天側の対象月データを取得して、次の除外判断・印刷へ進みます。",
        linkLabel: "楽天 取得へ",
      },
      rakuten_print: {
        message: "楽天の印刷完了待ちステータスを確認してください。",
        reason: "楽天の印刷処理が完了し、必要に応じて確認・反映を行ってください。",
        linkLabel: "楽天の印刷ステータスへ",
      },
      rakuten_decide_print: {
        message: "楽天の除外設定・印刷対象を確認してください。",
        reason: "除外対象を確定して印刷完了まで進めると状態が保存されます。",
        linkLabel: "楽天 除外・印刷へ",
      },
      provider_ingest: {
        message: "外部CSVの取り込みを実行してください。",
        reason: "Amazon/楽天で取得しきれない分を、共通フォルダ経由で取り込むフェーズです。",
        linkLabel: "共通フォルダ取込へ",
      },
      mf_reconcile: {
        message: "MF連携の突合せ実行へ進めてください。",
        reason: "取り込み済みデータをMFの下書き作成へ反映します。",
        linkLabel: "MF 突合作業へ",
      },
      preflight_mf: {
        message: "MF再取得のみのステップを完了してください。",
        reason: "MF再取得後、ダッシュボードの最新状態を確認して次の作業に進んでください。",
        linkLabel: "MF再取得へ",
      },
      mf_bulk_upload_task: {
        message: "Step 4: MF一括アップロード手順があります。",
        reason: "MF向けの手入力ファイルが用意できている場合、取り込みを実行してください。",
        linkLabel: "MF一括アップロードを開く",
      },
      import_provider_receipts: {
        message: "Provider取り込みステップを実行してください。",
        reason: "外部ベンダーの未処理CSVをMF突合前に取り込んで反映してください。",
        linkLabel: "Provider取り込みへ進む",
      },
      mf_bulk_upload: {
        message: "MF一括アップロードを実行してください。",
        reason: "MFのインポート画面を開いて、対象月の下書き対象を確認してください。",
        linkLabel: "MF一括アップロードを開く",
      },
      mf_csv_import: {
        message: "MF CSVインポートを実行してください。",
        reason: "CSVをMF形式へ揃えたうえで取り込みを実行してください。",
        linkLabel: "MF CSVインポートを開く",
      },
      done: {
        message: "すべて完了しました。月次アーカイブを実行できます。",
        reason: "最後に月次クローズやアーカイブを実行して、次月運用に備えます。",
        linkLabel: "月次クローズへ",
      },
      fallback: {
        message: "処理の取得に時間がかかっています。更新を待ってください。",
        reason: "バックエンドから最新状態を反映するまで数秒待って再取得してください。",
      },
    };

    const runningModeGuidance = {
      preflight: {
        message: "準備処理を実行中です。",
        reason: "処理が完了するまで待機してください。完了後に次の操作が自動で更新されます。",
        linkLabel: "貅門ｙ蟾･遞九∈",
      },
      preflight_mf: {
        message: "MF再取得を実行中です。",
        reason: "MF再取得処理を完了するまで、進行完了後の状態更新を待ってください。",
        linkLabel: "貅門ｙ蟾･遞九∈",
      },
      amazon_download: {
        message: "Amazon 領収書取得を実行中です。",
        reason: "取得が完了すると次の工程へ進める状態になります。完了までお待ちください。",
        linkLabel: "Amazon 取得進行状況へ",
      },
      amazon_print: {
        message: "Amazon 印刷処理を実行中です。",
        reason: "除外・印刷の進行中です。完了後に状態が反映され、次の案内へ進みます。",
        linkLabel: "Amazon 蜊ｰ蛻ｷ迥ｶ豕√∈",
      },
      rakuten_download: {
        message: "楽天領収書取得を実行中です。",
        reason: "取得が完了すると次の工程へ進める状態になります。完了までお待ちください。",
        linkLabel: "楽天 取得進行状況へ",
      },
      rakuten_print: {
        message: "楽天 印刷処理を実行中です。",
        reason: "除外・印刷の進行中です。完了後に状態が反映され、次の案内へ進みます。",
        linkLabel: "讌ｽ螟ｩ 蜊ｰ蛻ｷ迥ｶ豕√∈",
      },
      provider_ingest: {
        message: "共通フォルダ取り込みを実行中です。",
        reason: "取り込み処理完了後に突合せ可能かどうかを再評価します。",
        linkLabel: "共通フォルダ取込へ",
      },
      mf_reconcile: {
        message: "MF突合せを実行中です。",
        reason: "突合せ完了まで暫くお待ちください。完了後に下書きの作成状況が更新されます。",
        linkLabel: "MF遯∝粋迥ｶ豕√∈",
      },
      import_provider_receipts: {
        message: "Provider receipt import is running.",
        reason: "After import, verify files are reflected in MF draft workflow.",
        linkLabel: "Open provider import step",
      },
      mf_bulk_upload: {
        message: "MF bulk upload is running.",
        reason: "Check MF login state and selected bulk import target.",
        linkLabel: "Open MF bulk upload step",
      },
      mf_csv_import: {
        message: "MF CSV import is running.",
        reason: "If CSV import is pending, confirm file encoding and dedupe rules.",
        linkLabel: "Open MF CSV import step",
      },
    };

    const nextStepAnchors = {
      preflight: "#step-preflight",
      preflight_mf: "#step-preflight",
      amazon_or_rakuten_download: "#step-amazon-download",
      amazon_download: "#step-amazon-download",
      amazon_decide_print: "#step-amazon-decide-print",
      rakuten_download: "#step-rakuten-download",
      rakuten_decide_print: "#step-rakuten-decide-print",
      rakuten_print: "#step-rakuten-decide-print",
      amazon_print: "#step-amazon-decide-print",
      provider_ingest: "#step-provider-ingest",
      import_provider_receipts: "#step-provider-ingest",
      mf_bulk_upload_task: "#step-mf-bulk-upload-task",
      mf_bulk_upload: "#step-mf-bulk-upload-task",
      mf_csv_import: "#step-mf-bulk-upload-task",
      mf_reconcile: "#step-mf-reconcile",
      done: "#step-month-close",
    };

    const fallbackHref = FALLBACK_WIZARD_HREF;
    const nextTargetHref = nextStepAnchors[nextStepKey] || fallbackHref;
    const runningTargetHref = nextStepAnchors[runningMode] || nextTargetHref || FALLBACK_WIZARD_HREF;
    if (runningMode) {
      const runningGuidance = runningModeGuidance[runningMode];
      if (runningTargetHref === fallbackHref) {
        recordWizardFallback({
          type: "running_mode_anchor",
          runningMode,
          nextStep: nextStepKey,
          nextStepReason: nextStepReasonCode,
          href: runningTargetHref,
        });
      }
      return {
        message: runningGuidance?.message || `${runningMode} を実行中です。`,
        reason:
          runningGuidance?.reason ||
          "別の処理が進行中です。完了するまで待機してください。",
        href: runningTargetHref,
        linkLabel: runningGuidance?.linkLabel || (runningTargetHref === FALLBACK_WIZARD_HREF ? "手順を確認" : "進捗を確認"),
      };
    }

    const reasonHint = {
      preflight_required: {
        reason: "準備フローが未完了です。まず前提設定の完了が必要です。",
      },
      source_download_required: {
        message: "Amazon か楽天のどちらかの領収書取得を先に実行してください。",
        reason: "少なくとも1社分の対象月データを取得してください。",
      },
      amazon_download_required: {
        message: "Amazon の領収書を取得してください。",
        reason: "対象月分を取得すると次の除外・印刷工程へ進めます。",
      },
      rakuten_download_required: {
        message: "楽天の領収書を取得してください。",
        reason: "対象月分を取得すると次の除外・印刷工程へ進めます。",
      },
      amazon_print_pending: {
        message: "Amazon の除外設定・印刷対象を確認してください。",
        reason: "除外対象の確定と印刷完了を行うと次工程へ進みます。",
      },
      rakuten_print_pending: {
        message: "楽天の除外設定・印刷対象を確認してください。",
        reason: "除外対象の確定と印刷完了を行うと次工程へ進みます。",
      },
      provider_ingest_pending: {
        message: "外部CSVの取り込みを実行してください。",
        reason: "Amazon/楽天で取得しきれない分を共通フォルダから取り込んでください。",
      },
      mf_reconcile_ready: {
        message: "MF連携の突合せ実行へ進めてください。",
        reason: "取り込み済みデータをMFの下書き作成へ反映する準備が整いました。",
      },
      workflow_complete: {
        message: "すべて完了しました。月次アーカイブを実行できます。",
        reason: "最終確認として月次クローズやアーカイブで次月準備に進んでください。",
      },
    };

    const href = nextTargetHref;
    if (href === fallbackHref) {
      recordWizardFallback({
        type: "next_step_anchor",
        runningMode,
        nextStep: nextStepKey,
        nextStepReason: nextStepReasonCode,
        href,
      });
    }
    const baseGuidance = nextStepGuidance[nextStepKey] || nextStepGuidance.fallback;
    const reasonGuidance = reasonHint[nextStepReasonCode];
    const reasonKnown = Object.prototype.hasOwnProperty.call(reasonHint, nextStepReasonCode);
    const apiFallbackReason = apiNextStepWasUnknown
      ? ` [fallback: next_step "${apiNextStep}" was unknown and inferred from current flags]`
      : "";
    if (nextStepReasonCode && !reasonKnown) {
      recordWizardFallback({
        type: "next_step_reason_unknown",
        runningMode,
        nextStep: nextStepKey,
        nextStepReason: nextStepReasonCode,
        href,
      });
    }
    const guidance = reasonGuidance
      ? {
          ...baseGuidance,
          message: reasonGuidance.message || baseGuidance.message,
          reason: `${reasonGuidance.reason || baseGuidance.reason}${apiFallbackReason}`,
        }
      : {
          ...baseGuidance,
          reason: `${baseGuidance.reason || ""}${apiFallbackReason}`,
        };
    return {
      message: guidance.message,
      reason: guidance.reason,
      href,
      linkLabel: guidance.linkLabel || (href === FALLBACK_WIZARD_HREF ? "手順を確認" : ""),
    };
  }
  function inferAllowedModes(data) {
    const apiModes = Array.isArray(data?.allowed_run_modes) ? data.allowed_run_modes : [];
    if (apiModes.length > 0) {
      const normalized = [];
      const seen = new Set();
      for (const mode of apiModes) {
        const normalizedMode = String(mode || "").trim();
        if (!normalizedMode || seen.has(normalizedMode)) continue;
        seen.add(normalizedMode);
        normalized.push(normalizedMode);
      }
      return normalized;
    }
    const allowed = ["preflight", "preflight_mf"];
    if (!data.preflight?.done) return allowed;
    allowed.push("amazon_download");
    allowed.push("rakuten_download");
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    const amazonPending = Boolean(data.amazon?.downloaded && !amazonDone);
    const rakutenPending = Boolean(data.rakuten?.downloaded && !rakutenDone);
    if (data.amazon?.downloaded) {
      allowed.push("amazon_print");
    }
    if (data.rakuten?.downloaded) {
      allowed.push("rakuten_print");
    }
    const canReconcile =
      "can_reconcile" in data ? Boolean(data.can_reconcile) : Boolean(data.amazon?.downloaded || data.rakuten?.downloaded) && !(amazonPending || rakutenPending);
    if (canReconcile) {
      allowed.push("mf_reconcile");
    }
    return allowed;
  }

  function applyActionAvailability(data) {
    const runningMode = String(data.running_mode || "");
    const allowedModes = inferAllowedModes(data);
    document.querySelectorAll("[data-step-action]").forEach((button) => {
      const mode = String(button.dataset.stepAction || "");
      const allowed = allowedModes.includes(mode);
      const blockedByRunning = Boolean(runningMode);
      const blockedByOrder = !allowed;
      button.disabled = blockedByRunning || blockedByOrder;
      if (blockedByRunning) {
        button.title = "Another task is running.";
      } else if (blockedByOrder) {
        button.title = "Follow the wizard order.";
      } else {
        button.title = "";
      }
    });
  }

  function applyArchiveAvailability(data) {
    document.querySelectorAll("[data-archive-action]").forEach((button) => {
      if (button.dataset.busy === "1") {
        button.disabled = true;
        return;
      }
      const runningMode = String(data.running_mode || "");
      const amazonDownloaded = Boolean(data.amazon?.downloaded);
      const rakutenDownloaded = Boolean(data.rakuten?.downloaded);
      const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
      const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
      const amazonPending = Boolean(amazonDownloaded && !amazonDone);
      const rakutenPending = Boolean(rakutenDownloaded && !rakutenDone);
      const hasDownloadedSource = amazonDownloaded || rakutenDownloaded;
      const canArchive =
        "archive" in data && data.archive && typeof data.archive === "object"
          ? Boolean(data.archive.can_archive)
          : (hasDownloadedSource && !(amazonPending || rakutenPending));
      const allowed = canArchive;
      const blockedByRunning = Boolean(runningMode);
      const action = button.dataset.archiveAction;

      // For month_close button, also check checklist state
      if (action === "month_close") {
        const checklistComplete = isChecklistComplete();
        button.disabled = blockedByRunning || !allowed || !checklistComplete;
        if (blockedByRunning) {
          button.title = "Another task is running.";
        } else if (!allowed && !checklistComplete) {
          button.title = "Archive conditions and month-close checklist are incomplete.";
        } else if (!allowed) {
          button.title = "Archive is not available yet.";
        } else if (!checklistComplete) {
          button.title = "Complete month-close checklist first.";
        } else {
          button.title = "";
        }
      } else {
        // For archive_outputs button, keep original logic
        button.disabled = blockedByRunning || !allowed;
        if (blockedByRunning) {
          button.title = "Another task is running.";
        } else if (!allowed) {
          button.title = "Archive is not available yet.";
        } else {
          button.title = "";
        }
      }
    });
  }

  function applyManualAvailability(data) {
    const runningMode = String(data.running_mode || "");
    const preflightDone = Boolean(data.preflight?.done);
    document.querySelectorAll("[data-manual-action]").forEach((button) => {
      if (button.dataset.busy === "1") {
        button.disabled = true;
        return;
      }
      const blockedByRunning = Boolean(runningMode);
      const action = String(button.dataset.manualAction || "");
      const needsPreflight = action === "run_mf_bulk_upload" || action === "run_mf_csv_import";
      const blockedByPreflight = needsPreflight && !preflightDone;
      button.disabled = blockedByRunning || blockedByPreflight;
      if (blockedByRunning) {
        button.title = "Another task is running.";
      } else if (blockedByPreflight) {
        button.title = "Run preflight first.";
      } else {
        button.title = "";
      }
    });
  }

  function applyProviderAvailability(data) {
    const runningMode = String(data.running_mode || "");
    const providers = data && typeof data === "object" ? data.providers : null;
    const sourceStatus = providers && typeof providers === "object" ? providers.source : null;
    const sourceConfigured = Boolean(sourceStatus && sourceStatus.configured);
    const sourceExists = Boolean(sourceStatus && sourceStatus.exists);
    document.querySelectorAll("[data-provider-action]").forEach((button) => {
      if (button.dataset.busy === "1") {
        button.disabled = true;
        return;
      }
      const blockedByRunning = Boolean(runningMode);
      const action = String(button.dataset.providerAction || "");
      if (action === "open_provider_source") {
        const blockedBySource = !sourceConfigured || !sourceExists;
        button.disabled = blockedByRunning || blockedBySource;
        if (blockedByRunning) {
          button.title = "Another task is running.";
        } else if (!sourceConfigured) {
          button.title = "Provider source folder is not configured.";
        } else if (!sourceExists) {
          button.title = "Provider source folder not found.";
        } else {
          button.title = "";
        }
      } else {
        button.disabled = blockedByRunning;
        button.title = blockedByRunning ? "(msg)" : "";
      }
    });
  }

  function toCount(value) {
    const parsed = Number.parseInt(String(value ?? ""), 10);
    if (!Number.isFinite(parsed) || parsed < 0) return 0;
    return parsed;
  }

  function buildMfSummaryText(data) {
    const runningMode = String(data?.running_mode || "");
    if (runningMode === "mf_reconcile") {
      return "MF reconcile is running.";
    }
    const mf = data && typeof data === "object" ? data.mf : null;
    const summary = mf && typeof mf === "object" ? mf.summary : null;
    const missingCandidates = toCount(summary?.missing_candidates);
    const targetsTotal = toCount(summary?.targets_total);
    const created = toCount(summary?.created);
    const failed = toCount(summary?.failed);
    const status = String(summary?.status || "").trim().toLowerCase();
    const hasDraftResult = targetsTotal > 0 || created > 0 || failed > 0 || Boolean(status);
    const reconciled = Boolean(mf?.reconciled);

    if (!reconciled && !hasDraftResult && missingCandidates === 0) {
      return "MF reconcile not started.";
    }
    if (!hasDraftResult) {
      return `Pending candidates: ${missingCandidates}`;
    }
    return `Pending: ${missingCandidates} / Created: ${created}/${targetsTotal} / Failed: ${failed}`;
  }
  function renderMfSummary(data, fallbackMessage = "") {
    const summaryEl = document.querySelector("[data-mf-summary]");
    if (!summaryEl) return;
    if (fallbackMessage) {
      summaryEl.textContent = fallbackMessage;
      return;
    }
    summaryEl.textContent = buildMfSummaryText(data);
  }

  function fileNameFromPath(rawPath) {
    const path = String(rawPath || "").trim();
    if (!path) return "";
    const normalized = path.replace(/\\/g, "/");
    const parts = normalized.split("/");
    return parts.length > 0 ? parts[parts.length - 1] : normalized;
  }

  function buildProviderSourceSummarySuffix(scanSummary, pendingFiles) {
    const summary = scanSummary && typeof scanSummary === "object" ? scanSummary : {};
    const matched = toCount(summary.matched);
    const checked = toCount(summary.checked);
    const pdfFiles = toCount(summary.pdf_files);
    const ignoredOutOfMonth = toCount(summary.ignored_out_of_month);
    const ignoredUnmatchedName = toCount(summary.ignored_unmatched_name);
    const ignoredNonPdf = toCount(summary.ignored_non_pdf);
    const ignoredHidden = toCount(summary.ignored_hidden);
    const parts = [];
    const effectivePending = Math.max(0, pendingFiles);
    if (checked > 0) {
      parts.push(`${checked} file(s) checked`);
    }
    if (pdfFiles > 0) {
      parts.push(`${pdfFiles} PDF file(s)`);
    }
    if (effectivePending > 0) {
      parts.push(`${effectivePending} matched file(s)`);
    }
    if (matched > 0 && pendingFiles === 0) {
      parts.push(`${matched} matched in scan`);
    }
    if (ignoredOutOfMonth > 0) {
      parts.push(`${ignoredOutOfMonth} outside target month`);
    }
    if (ignoredNonPdf > 0) {
      parts.push(`${ignoredNonPdf} non-PDF ignored`);
    }
    if (ignoredHidden > 0) {
      parts.push(`${ignoredHidden} hidden file(s) ignored`);
    }
    const scanError = String(summary.scan_error || "").trim();
    if (scanError) {
      parts.push(`scan status: ${scanError}`);
    }
    return parts.length > 0 ? ` (${parts.join(", ")})` : "";
  }

  function buildProviderSourceSummaryText(rawSource) {
    const source = rawSource && typeof rawSource === "object" ? rawSource : {};
    const configured = Boolean(source.configured);
    const exists = Boolean(source.exists);
    const pending = toCount(source.pending_files);
    const path = String(source.path || "").trim();
    const scanSummary = source.scan_summary && typeof source.scan_summary === "object" ? source.scan_summary : {};
    const sampleMatched = Array.isArray(scanSummary.sample_matched)
      ? scanSummary.sample_matched.map(fileNameFromPath).filter(Boolean).slice(0, 3)
      : [];
    const detailsSuffix = buildProviderSourceSummarySuffix(scanSummary, pending);
    const sampleText = sampleMatched.length > 0 ? ` e.g. ${sampleMatched.join(", ")}` : "";

    if (!configured) {
      return "Provider source folder is not configured.";
    }
    if (!exists) {
      return `Configured provider source folder not found: ${path || "(not set)"}`;
    }
    const checked = toCount(scanSummary.checked);
    if (pending === 0 && checked > 0) {
      const scanHint = String(scanSummary.scan_error || "").trim();
      const status = scanHint ? `${scanHint}; ` : "";
      return `${path}: no files matched the selected year-month. ${status}Checked ${checked} file(s).${sampleText ? ` (sample: ${sampleText})` : ""}${detailsSuffix}`;
    }
    if (!path) {
      return `Provider source folder is ready${detailsSuffix}`;
    }
    if (sampleText) {
      return `${path}: ${sampleText}${detailsSuffix}`;
    }
    return `${path}${detailsSuffix}`;
  }

  function renderProviderSourceSummary(rawSource, fallbackMessage = "") {
    const source = rawSource && typeof rawSource === "object" ? rawSource : {};
    const summaryEl = document.querySelector("[data-provider-source-summary]");
    if (!summaryEl) return;
    const text = fallbackMessage || buildProviderSourceSummaryText(rawSource);
    summaryEl.textContent = text;
    const guideEl = document.querySelector("[data-provider-source-setup-guide]");
    if (guideEl) {
      const needsGuide =
        Boolean(fallbackMessage) ||
        !Boolean(source.configured) ||
        !Boolean(source.exists) ||
        text.toLowerCase().includes("not configured") ||
        text.toLowerCase().includes("not found");
      guideEl.hidden = !needsGuide;
      const guideLinkEl = guideEl.querySelector("a");
      if (guideLinkEl) {
        guideLinkEl.href = PROVIDER_SOURCE_SETUP_GUIDE_URL;
      }
    }
  }

  function buildProviderImportSummaryText(rawProviders, runningMode) {
    const providers = rawProviders && typeof rawProviders === "object" ? rawProviders : {};
    const running = String(runningMode || "").trim() === "import_provider_receipts";
    if (running) {
      return "Provider import is running...";
    }

    const lastImport = providers.last_import && typeof providers.last_import === "object" ? providers.last_import : {};
    const attempted = Boolean(lastImport.attempted);
    const pending = toCount(providers.pending_total);
    const updatedAt = String(lastImport.updated_at || "").trim();
    const updatedText = updatedAt ? ` (${updatedAt})` : "";

    if (!attempted) {
      if (pending > 0) {
        return `${pending} file(s) are waiting to be imported.`;
      }
      return `No provider import has been executed yet.${updatedText}`;
    }

    const foundFiles = toCount(lastImport.found_files);
    const foundPdfs = toCount(lastImport.found_pdfs);
    const imported = toCount(lastImport.imported);
    const skipped = toCount(lastImport.skipped_duplicates);
    const failed = toCount(lastImport.failed);
    const manualActionRequired = Boolean(lastImport.manual_action_required);
    const manualActionReason = String(lastImport.manual_action_reason || "").trim();

    const detected = foundPdfs > 0 ? foundPdfs : foundFiles;
    const parts = [];
    if (detected > 0) {
      parts.push(`Detected: ${detected}`);
    }
    if (imported > 0) {
      parts.push(`Imported: ${imported}`);
    }
    if (skipped > 0) {
      parts.push(`Skipped(dup): ${skipped}`);
    }
    if (failed > 0) {
      parts.push(`Failed: ${failed}`);
    }

    const prefix = manualActionRequired || failed > 0 ? "⚠ Import completed with warnings: " : "Import completed: ";
    const summary = parts.length > 0 ? parts.join(" / ") : "No rows were detected.";
    const reason = manualActionReason ? ` (reason: ${manualActionReason})` : "";
    return `${prefix}${summary}${reason}${updatedText}`;
  }

  function renderProviderImportSummary(rawProviders, runningMode, fallbackMessage = "") {
    const summaryEl = document.querySelector("[data-provider-import-summary]");
    if (!summaryEl) return;
    summaryEl.textContent = fallbackMessage || buildProviderImportSummaryText(rawProviders, runningMode);
  }


  function setStepLinkState(link, enabled, href) {
    if (!link) return;
    if (enabled) {
      link.href = href;
      link.classList.remove("disabled");
      link.removeAttribute("aria-disabled");
      link.removeAttribute("tabindex");
      return;
    }
    link.href = "#";
    link.classList.add("disabled");
    link.setAttribute("aria-disabled", "true");
    link.setAttribute("tabindex", "-1");
  }

  function applyLinkAvailability(data, ym) {
    const amazonExcludeReady = Boolean(data.preflight?.done && data.amazon?.downloaded);
    const rakutenExcludeReady = Boolean(data.preflight?.done && data.rakuten?.downloaded);
    document.querySelectorAll("[data-step-link]").forEach((link) => {
      const key = String(link.dataset.stepLink || "");
      if (key === "amazon_exclude") {
        setStepLinkState(link, amazonExcludeReady, `/runs/${ym}#exclude-section`);
      } else if (key === "rakuten_exclude") {
        setStepLinkState(link, rakutenExcludeReady, `/runs/${ym}#exclude-section`);
      } else {
        setStepLinkState(link, false, "#");
      }
    });
  }

  function buildStepStates(data, runningMode) {
    const amazonRunning = runningMode === "amazon_download" || runningMode === "amazon_print";
    const rakutenRunning = runningMode === "rakuten_download" || runningMode === "rakuten_print";
    const providerRunning = runningMode === "import_provider_receipts";
    const mfBulkUploadRunning = runningMode === "mf_bulk_upload" || runningMode === "mf_csv_import";
    const amazonDone = Boolean(data.amazon?.confirmed && data.amazon?.printed);
    const rakutenDone = Boolean(data.rakuten?.confirmed && data.rakuten?.printed);
    const providerDone = Boolean(data.providers?.step_done);
    const mfBulkUploadDone = Boolean(data.mf_bulk_upload?.done || data.mf_csv_import?.done);
    return {
      preflight: data.preflight?.done ? "done" : runningMode === "preflight" ? "running" : "pending",
      amazon_download: amazonRunning ? "running" : data.amazon?.downloaded ? "done" : "pending",
      amazon_decide_print: runningMode === "amazon_print" ? "running" : amazonDone ? "done" : "pending",
      rakuten_download: rakutenRunning ? "running" : data.rakuten?.downloaded ? "done" : "pending",
      rakuten_decide_print: runningMode === "rakuten_print" ? "running" : rakutenDone ? "done" : "pending",
      provider_ingest: providerRunning ? "running" : providerDone ? "done" : "pending",
      mf_bulk_upload_task: mfBulkUploadRunning ? "running" : mfBulkUploadDone ? "done" : "pending",
      mf_reconcile:
        runningMode === "mf_reconcile"
          ? "running"
          : Boolean(data.mf?.step_done ?? data.mf?.reconciled)
            ? "done"
            : "pending",
    };
  }

  function buildTaskStates(stepStates) {
    const amazonRunning = stepStates.amazon_download === "running" || stepStates.amazon_decide_print === "running";
    const rakutenRunning = stepStates.rakuten_download === "running" || stepStates.rakuten_decide_print === "running";
    return {
      amazon: amazonRunning ? "running" : stepStates.amazon_decide_print === "done" ? "done" : "pending",
      rakuten: rakutenRunning ? "running" : stepStates.rakuten_decide_print === "done" ? "done" : "pending",
    };
  }


window.DashboardIndexRender = {
  getYmFromForm,
  setStepStatus,
  setTaskStatus,
  renderNextStep,
  recordWizardFallback,
  navigateToStep,
  inferNextStepFromFlags,
  normalizeNextStepValue,
  isKnownNextStep,
  resolveNextStep,
  formatArchiveTimeForDisplay,
  archivePageHref,
  applyArchivePageLink,
  computeNextStep,
  inferAllowedModes,
  applyActionAvailability,
  applyArchiveAvailability,
  applyManualAvailability,
  applyProviderAvailability,
  toCount,
  buildMfSummaryText,
  renderMfSummary,
  fileNameFromPath,
  buildProviderSourceSummarySuffix,
  buildProviderSourceSummaryText,
  renderProviderSourceSummary,
  buildProviderImportSummaryText,
  renderProviderImportSummary,
  setStepLinkState,
  applyLinkAvailability,
  buildStepStates,
  buildTaskStates,
};
