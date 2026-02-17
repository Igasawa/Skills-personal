/**
 * 領収書メールを検索し、PDFをGoogleドライブの指定フォルダに保存する
 * 保存先: _ax > gaspdf (ID: 1JspZZVZExqdfWUgHJ0pspmmB4ouSFKvC)
 */
function saveReceiptsToDrive() {
  const FOLDER_ID = '1JspZZVZExqdfWUgHJ0pspmmB4ouSFKvC'; 
  const PROCESSED_LABEL = '領収書保存済み'; 
  
  // 1. 添付PDFがあるメールの検索クエリ
  const ATTACHMENT_QUERY = '(from:Anthropic OR "Aqua Voice" OR from:Gamma OR "Google Cloud Platform" OR "GOOGLE ONE" OR "Receipt from Replit") has:attachment filename:pdf -label:' + PROCESSED_LABEL;
  
  // 2. 本文をPDF化する必要があるメールの検索クエリ（Google Play）
  const BODY_PDF_QUERY = '"Google Play からの注文明細" -label:' + PROCESSED_LABEL;

  try {
    const folder = DriveApp.getFolderById(FOLDER_ID);
    const label = getOrCreateLabel(PROCESSED_LABEL);

    // --- 処理1: 添付PDFの保存 ---
    processMessages(ATTACHMENT_QUERY, folder, label, true);

    // --- 処理2: 本文PDF化（Google Play用） ---
    processMessages(BODY_PDF_QUERY, folder, label, false);

    console.log("すべての処理が正常に完了しました。");

  } catch (e) {
    console.error("システムエラーが発生しました: " + e.toString());
  }
}

/**
 * メッセージを処理してファイルを保存する共通関数
 */
function processMessages(query, folder, label, isAttachment) {
  const threads = GmailApp.search(query);
  
  threads.forEach(thread => {
    const messages = thread.getMessages();
    messages.forEach(message => {
      const date = Utilities.formatDate(message.getDate(), "JST", "yyyyMMdd");
      const subject = message.getSubject();

      try {
        if (isAttachment) {
          // 添付ファイルの処理
          const attachments = message.getAttachments();
          attachments.forEach(attachment => {
            if (attachment.getContentType() === "application/pdf") {
              const safeName = sanitizeFileName(`${date}_${attachment.getName()}`);
              folder.createFile(attachment).setName(safeName);
              console.log("添付ファイルを保存しました: " + safeName);
            }
          });
        } else {
          // 本文をPDF化する処理
          const safeSubject = sanitizeFileName(subject);
          const fileName = `${date}_GooglePlay領収書_${safeSubject}.pdf`;
          const htmlBody = message.getBody();
          const blob = Utilities.newBlob(htmlBody, "text/html", fileName).getAs("application/pdf");
          folder.createFile(blob);
          console.log("本文をPDFとして保存しました: " + fileName);
        }
      } catch (fileError) {
        console.error("個別のファイル保存でエラーが発生しました: " + fileError.toString());
      }
    });
    thread.addLabel(label); // 最後にラベルを付けて処理済みにする
  });
}

/**
 * ファイル名として使えない禁止文字を除去する関数
 */
function sanitizeFileName(name) {
  if (!name) return "unnamed";
  // WindowsやGoogleドライブで禁止されている文字（\ / : * ? " < > |）を _ に置換
  return name.replace(/[\\\/:\*\?"<>\|]/g, "_");
}

/**
 * ラベルが存在しない場合は作成する
 */
function getOrCreateLabel(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}