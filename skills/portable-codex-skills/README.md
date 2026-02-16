# Portable Codex Skills

このフォルダは、他環境でも同じSKILLを使えるように、`~/.codex/skills` から主要スキルをリポジトリ内に複製したものです。

## 含まれるスキル
- google-apps-script
- spreadsheet
- xlsx
- pptx

## 再反映手順

### 1) スキルを復元したい場合

PowerShell:

```powershell
$src = "${env:USERPROFILE}\\.vscode\\Skillpersonal\\skills\\portable-codex-skills\"  # 例のリポジトリ内コピー先
$dst = "${env:USERPROFILE}\\.codex\\skills"                                 # Codex本体の配置先
Copy-Item -Path "${src}\\<skill>" -Destination "${dst}" -Recurse -Force
```

### 補足
- これは実行可能な設定ファイルや認証情報は含みません。
- スキル本体（SKILL.md / references / scripts）を移行する用途です。
- 必要時は、`Config.toml`や環境変数は別途この環境で再設定してください。
