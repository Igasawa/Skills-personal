(function () {
  // UI文言方針: toFriendlyMessage は利用者向けに日本語文言を返す。
  const toastEl = document.getElementById("toast");

  function showToast(message, type = "info") {
    if (!toastEl || !message) return;
    toastEl.textContent = message;
    toastEl.classList.remove("success", "error", "show");
    if (type === "success") toastEl.classList.add("success");
    if (type === "error") toastEl.classList.add("error");
    requestAnimationFrame(() => toastEl.classList.add("show"));
    clearTimeout(window.__toastTimer);
    window.__toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2400);
  }

  function bindCopyButtons(root = document) {
    root.querySelectorAll(".copy-button").forEach((button) => {
      button.addEventListener("click", async () => {
        const targetId = button.dataset.copyTarget;
        const target = targetId ? document.getElementById(targetId) : null;
        const text = target ? target.textContent : "";
        if (!text) return;
        try {
          await navigator.clipboard.writeText(text);
          button.textContent = "コピーしました";
          setTimeout(() => {
            button.textContent = "コピー";
          }, 1200);
        } catch {
          alert("クリップボードにコピーできませんでした。");
        }
      });
    });
  }

  function toFriendlyMessage(detail) {
    const text = String(detail || "");
    if (text.includes("Another run is already in progress")) return "すでに実行中の処理があります。完了してから再度お試しください。";
    if (text.includes("MF Cloud expense list URL is required")) return "MFクラウド経費一覧URLを入力してください。";
    if (text.includes("Invalid year/month") || text.includes("Month must be")) return "年月の形式が正しくありません。YYYY-MM で確認してください。";
    if (text.includes("Missing amazon/orders.jsonl")) return "Amazonの注文データがありません。先にAmazonの領収書取得を実行してください。";
    if (text.includes("Missing mfcloud/expenses.jsonl")) return "MFクラウドの抽出データがありません。先にMF抽出を実行してください。";
    if (text.includes("Invalid mode")) return "実行モードが不正です。";
    if (text.includes("Workflow order violation")) return "実行順序が正しくありません。画面の次ステップ案内に従ってください。";
    if (text.includes("Run not found")) return "対象月の実行成果物がありません。先に領収書取得を実行してください。";
    if (text.includes("AMAZON_COVERAGE_THRESHOLD_NOT_MET")) return "Amazon取得率が基準(80%)未満のため失敗しました。再取得してください。";
    if (text.includes("menu_not_found")) return "Amazonの「領収書等」メニューが見つかりませんでした。画面表示を確認して再実行してください。";
    if (text.includes("link_not_resolved")) return "領収書リンクを解決できませんでした。注文カードの「領収書等」を確認してください。";
    if (text.includes("document_validation_failed")) return "領収書文書ページの検証に失敗しました。取得対象ページを確認してください。";
    if (text.includes("save_failed")) return "PDF保存に失敗しました。再実行してください。";
    if (text.includes("Cannot find package 'playwright'") || text.includes("ERR_MODULE_NOT_FOUND")) {
      return "Playwright依存が見つかりませんでした。初回起動の準備を行ってから再実行してください。";
    }
    if (text.includes("Failed to install Node dependencies")) {
      return "Node依存のセットアップに失敗しました。ネットワーク接続と npm の設定を確認してください。";
    }
    if (text.includes("Provider auto-download is disabled")) {
      return "Step3の自動取得は無効です。各サービスで手動取得した領収書を共通フォルダに置いてから「共通フォルダから取り込み」を実行してください。";
    }
    if (text === "Not Found") {
      return "APIエンドポイントが見つかりません。ダッシュボードを再起動して再試行してください。";
    }
    return text || "実行に失敗しました。ログを確認してください。";
  }

  function normalizeSearchText(text) {
    return String(text || "").toLowerCase().replace(/\s+/g, " ").trim();
  }

  window.DashboardCommon = {
    bindCopyButtons,
    normalizeSearchText,
    showToast,
    toFriendlyMessage,
  };
})();
