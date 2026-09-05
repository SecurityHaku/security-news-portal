# ローカルで「収集 -> 採点 -> 日本語化 -> レポート生成」を一括実行する（PowerShell）。
#   .\scripts\run_pipeline.ps1                 # 前月分のレポートまで
#   .\scripts\run_pipeline.ps1 -Month 2026-05
#   .\scripts\run_pipeline.ps1 -Month 2026-05 -SendEmail
#   .\scripts\run_pipeline.ps1 -SkipEnrich     # 翻訳・見解をスキップ（英語のまま）
param(
  [string]$Month = "",
  [switch]$SendEmail,
  [switch]$SkipCollect,
  [switch]$SkipEnrich
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# .env があれば読み込む（ANTHROPIC_API_KEY などをこのセッションに反映）
if (Test-Path .env) {
  Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') {
      [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
  }
}

if (-not $SkipCollect) {
  Write-Host "== collect ==" -ForegroundColor Cyan
  python scripts/collect.py
}

Write-Host "== score ==" -ForegroundColor Cyan
python scripts/score.py

if (-not $SkipEnrich) {
  Write-Host "== enrich (日本語化 + アナリスト見解) ==" -ForegroundColor Cyan
  python scripts/enrich.py
}

Write-Host "== generate_report ==" -ForegroundColor Cyan
if ($Month) { python scripts/generate_report.py --month $Month }
else        { python scripts/generate_report.py }

if ($SendEmail) {
  Write-Host "== send_email ==" -ForegroundColor Cyan
  if ($Month) { python scripts/send_email.py --month $Month }
  else        { python scripts/send_email.py }
} else {
  Write-Host "メール送信はスキップ（-SendEmail で有効化）" -ForegroundColor Yellow
}

Write-Host "完了。プレビュー: python scripts/serve.py" -ForegroundColor Green
