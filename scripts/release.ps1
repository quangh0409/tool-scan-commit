# Đóng gói bản phát hành: build exe từ `dev` SẠCH, in SHA256, gom vào release/secjit-scan-<version>/.
# Dùng:  ./scripts/release.ps1 [-Version v0.1.0] [-Force] [-SkipBuild]
#   -Force     : bỏ kiểm "đang ở dev + working tree sạch"
#   -SkipBuild : dùng dist/ hiện có (không build lại)
# Kết quả: release/secjit-scan-<version>/{secjit-scan.exe, secjit-scan-gui.exe, SHA256SUMS.txt, README.md, docs/...}
param(
    [string]$Version = "",
    [switch]$Force,
    [switch]$SkipBuild
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"

# 1. Nguồn phải là dev sạch
$branch = (git rev-parse --abbrev-ref HEAD | Out-String).Trim()
$dirty = (git status --porcelain | Out-String).Trim()
if (-not $Force) {
    if ($branch -ne "dev") { throw "Đang ở nhánh '$branch' — release phải build từ 'dev' (hoặc -Force)." }
    if ($dirty) { throw "Working tree chưa sạch:`n$dirty`nCommit/stash trước (hoặc -Force)." }
}
if (-not $Version) { $Version = (git describe --tags --always --dirty | Out-String).Trim() }
if (-not $Version) { $Version = "dev" }
Write-Host "Release $Version từ $branch @ $((git rev-parse --short HEAD | Out-String).Trim())"

# 2. Build (build_exe.ps1 ghi packaging/_version_build.txt + dist/SHA256SUMS.txt)
if (-not $SkipBuild) {
    $env:SECJIT_APP_VERSION = $Version
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "build_exe.ps1") -Clean
    if ($LASTEXITCODE -ne 0) { throw "build_exe.ps1 thất bại" }
}
foreach ($f in "dist\secjit-scan.exe", "dist\secjit-scan-gui.exe", "dist\SHA256SUMS.txt") {
    if (-not (Test-Path (Join-Path $Root $f))) { throw "Thiếu $f" }
}

# 3. Gom thư mục release
$out = Join-Path $Root "release\secjit-scan-$Version"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force (Join-Path $out "docs") | Out-Null
Copy-Item (Join-Path $Root "dist\*.exe") $out
Copy-Item (Join-Path $Root "dist\SHA256SUMS.txt") $out
Copy-Item (Join-Path $Root "README.md") $out
foreach ($d in "RELEASE_NOTES.md", "GUIDE.md", "METHODOLOGY.md", "HUONG_DAN_GUI.md", "RULE_GAN_NHAN.md", "CONTRACTS.md", "DESKTOP_APP_PLAN.md", "LICENSE") {
    $src = Join-Path $Root $d
    if (Test-Path $src) { Copy-Item $src (Join-Path $out "docs") }
}
@"
secjit-scan $Version
build: $(Get-Date -Format s)  git: $((git rev-parse HEAD | Out-String).Trim())  branch: $branch
python: $((python --version | Out-String).Trim())  pyinstaller: $((python -m PyInstaller --version | Out-String).Trim())

Chạy:
  secjit-scan-gui.exe                 giao diện (WebView2; không có → trình duyệt)
  secjit-scan.exe --preflight --json  kiểm môi trường (Docker Desktop, image, port, RAM)
  secjit-scan.exe --profile P.json    chạy pipeline headless
  secjit-scan.exe --cli --help        mọi lệnh orchestrator
Kiểm toàn vẹn: Get-FileHash -Algorithm SHA256 *.exe  so với SHA256SUMS.txt
"@ | Out-File -Encoding utf8 (Join-Path $out "RELEASE_NOTES.txt")

Write-Host "`nSHA256:"
Get-Content (Join-Path $out "SHA256SUMS.txt")
Write-Host "`nĐã gom: $out"
Get-ChildItem $out -Recurse | Select-Object @{n="MB";e={[math]::Round($_.Length/1MB,2)}}, FullName | Format-Table -AutoSize
