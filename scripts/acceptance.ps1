# Nghiệm thu Run A/B (CONTRACTS §6/§11): verify_run A, verify_run B, compare A↔B, results_report, stats A.
# Dùng:  ./scripts/acceptance.ps1 -DbA <A.sqlite> -ExportA <export_A> -DbB <B.sqlite> -ExportB <export_B> [-Out RESULTS.md] [-Python python]
# Exit 0 CHỈ KHI verify A PASS, verify B PASS và compare rc 0. DB mở chỉ đọc (verify_run/stats/compare đều mode=ro).
param(
    [Parameter(Mandatory = $true)][string]$DbA,
    [Parameter(Mandatory = $true)][string]$ExportA,
    [Parameter(Mandatory = $true)][string]$DbB,
    [Parameter(Mandatory = $true)][string]$ExportB,
    [string]$Out = "RESULTS.md",
    [string]$Python = "python"
)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:PYTHONPATH = "src"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

foreach ($p in @($DbA, $ExportA, $DbB, $ExportB)) {
    if (-not (Test-Path $p)) { Write-Host "THIẾU: $p"; exit 1 }
}
$Out = [IO.Path]::GetFullPath($Out)
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("secjit-acceptance-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force $tmp | Out-Null
$logs = Join-Path $tmp "logs"; New-Item -ItemType Directory -Force $logs | Out-Null

$steps = @()
function Run-Step {
    param([string]$Name, [string[]]$Cmd, [bool]$Gate)
    Write-Host ("`n=== " + $Name + " ===") -ForegroundColor Cyan
    Write-Host ("    " + ($Cmd -join " "))
    $log = Join-Path $logs (($Name -replace '[^a-zA-Z0-9_-]', '_') + ".log")
    $t0 = Get-Date
    & $Python @Cmd 2>&1 | Tee-Object -FilePath $log | Out-Host
    $rc = $LASTEXITCODE
    $dt = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    $script:steps += [pscustomobject]@{ Name = $Name; Rc = $rc; Gate = $Gate; Sec = $dt; Log = $log }
    return $rc
}

$null = Run-Step "verify_A"  @("scripts/verify_run.py", "--db", $DbA, "--export", $ExportA) $true
$null = Run-Step "verify_B"  @("scripts/verify_run.py", "--db", $DbB, "--export", $ExportB) $true
$null = Run-Step "compare"   @("-m", "orchestrator.cli", "compare", "--a", $ExportA, "--b", $ExportB, "--format", "md") $true
$null = Run-Step "report"    @("scripts/results_report.py", "--a", $ExportA, "--b", $ExportB, "--db-a", $DbA, "--db-b", $DbB, "--out", $Out) $false
$statsDir = Join-Path $tmp "stats_A"
$null = Run-Step "stats_A"   @("-m", "orchestrator.cli", "stats", "--db", $DbA, "--format", "json", "--out", $statsDir) $false

# ----------------------------------------------------------------- tóm tắt
Write-Host "`n================ TÓM TẮT NGHIỆM THU ================" -ForegroundColor Cyan
$ok = $true
foreach ($s in $steps) {
    $st = if ($s.Rc -eq 0) { "PASS" } else { "FAIL" }
    $gate = if ($s.Gate) { "(cổng)" } else { "(thông tin)" }
    $color = if ($s.Rc -eq 0) { "Green" } elseif ($s.Gate) { "Red" } else { "Yellow" }
    Write-Host ("  {0,-4} {1,-10} rc={2,-3} {3,6}s {4}" -f $st, $s.Name, $s.Rc, $s.Sec, $gate) -ForegroundColor $color
    if ($s.Gate -and $s.Rc -ne 0) { $ok = $false }
}
Write-Host ("  RESULTS.md : " + $(if (Test-Path $Out) { $Out } else { "KHÔNG tạo được" }))
Write-Host ("  stats A    : " + $(if (Test-Path $statsDir) { $statsDir } else { "KHÔNG tạo được" }))
Write-Host ("  log từng bước: " + $logs)
Write-Host ("  KẾT LUẬN   : " + $(if ($ok) { "ĐẠT (verify A, verify B, compare đều PASS)" } else { "KHÔNG ĐẠT" })) -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
exit $(if ($ok) { 0 } else { 1 })
