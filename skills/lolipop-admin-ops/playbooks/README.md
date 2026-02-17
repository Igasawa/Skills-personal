# LoLipop Playbook Samples

このフォルダは `skills/lolipop-admin-ops/scripts/run.py` の `--playbook` として使うテンプレートを置きます。

- `ssl_renewal.json` はSSL再発行向けです。
- `php_version_change.json` はPHPバージョン変更向けです。
- `cron_check.json` はCron一覧の確認向けです。

実行例:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service lolipop -- `
  python skills/lolipop-admin-ops/scripts/run.py --domain example.lolipop.jp --playbook .\skills\lolipop-admin-ops\playbooks\ssl_renewal.json --dry-run
```

適用例:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ax.ps1 secrets exec --service lolipop -- `
  python skills/lolipop-admin-ops/scripts/run.py --domain example.lolipop.jp --playbook .\skills\lolipop-admin-ops\playbooks\ssl_renewal.json --apply --allow-production
```

実際の画面とセレクタが変わる場合は、このファイルの selector を差し替えてください。
