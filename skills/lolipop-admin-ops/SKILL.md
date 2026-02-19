---
name: lolipop-admin-ops
description: LoLipop 管理UIの操作を再現可能な UI playbook として実行する。まず dry-run で確認し、実変更は apply モードで実行する。
---
# lolipop 管理運用

このスキルは LoLipop 管理作業を JSON playbook で実行し、同じ手順を再現できるようにする。

## 安全ルール
- `--dry-run` が既定で、書き込み前に必ず使う。
- `--apply` で `run-playbook` が実行され、変更操作が有効になる。
- 本番環境への書き込みには `--allow-production` が必須。
- `--action validate` は読み取り専用チェックを実行する。

## 事前準備
- AXディレクトリの初期化
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets init
```
- Playwright ブラウザの導入
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 playwright install --browser chromium
```
- ログインセッション保存（推奨）
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 playwright login --name lolipop --url "https://secure.lolipop.jp/"
```
  - 既定のセッションパス: `C:\Users\<user>\.ax\sessions\lolipop.storage.json`
- セッションファイルが使えない場合は `LOLIPOP_USERNAME` / `LOLIPOP_PASSWORD` へフォールバック可能だが、セッション利用を優先する。

## 実行
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service lolipop -- `
  python skills/lolipop-admin-ops/scripts/run.py --domain example.lolipop.jp --playbook .\skills\lolipop-admin-ops\playbooks\ssl_renewal.json --dry-run
```
- dry-run の出力とスクリーンショットを確認する。
- 問題なければ `--apply` で本実行する。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service lolipop -- `
  python skills/lolipop-admin-ops/scripts/run.py --domain example.lolipop.jp --playbook .\skills\lolipop-admin-ops\playbooks\ssl_renewal.json --apply --allow-production
```

## パラメータ
- `--domain` 対象ドメイン（必須）
- `--base-url` 管理画面のベースURL（既定: `https://secure.lolipop.jp`）
- `--environment` `production` または `staging`
- `--playbook` playbook JSONのパス
- `--action` `validate` または `run-playbook`
- `--dry-run` 読み取り専用の計画モード
- `--apply` 変更を実行（production は allow-production が必要）
- `--allow-production` 本番実行の明示承認
- `--session-name` storage_state 名（既定 `lolipop`）
- `--storage-state` storage_state パスを明示指定

## Playbook ファイル
- `playbooks/ssl_renewal.json`
- `playbooks/php_version_change.json`
- `playbooks/cron_check.json`

### SSL更新
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service lolipop -- `
  python skills/lolipop-admin-ops/scripts/run.py --environment staging --domain example.lolipop.jp --playbook .\skills\lolipop-admin-ops\playbooks\ssl_renewal.json --dry-run
```

### PHPバージョン変更
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service lolipop -- `
  python skills/lolipop-admin-ops/scripts/run.py --environment staging --domain example.lolipop.jp --playbook .\skills\lolipop-admin-ops\playbooks\php_version_change.json --dry-run
```

### Cron確認
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service lolipop -- `
  python skills/lolipop-admin-ops/scripts/run.py --environment production --domain example.lolipop.jp --playbook .\skills\lolipop-admin-ops\playbooks\cron_check.json --dry-run
```

## 返却JSON
- `status`: `success` or `error`
- `data`: execution context and step results
- `error`: type/message if failed

出力に認証情報は含めない。
