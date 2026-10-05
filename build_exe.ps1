# Build 2 exe onefile bằng PyInstaller (secjit.spec) và in kích thước + SHA256.
# Dùng: ./build_exe.ps1 [-Clean] [-Python python]
# Yêu cầu: pip install pyinstaller pywebview pythonnet (pywebview/pythonnet tuỳ chọn — GUI fallback trình duyệt).
param(
    [switch]$Clean,
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# 1. Phiên bản build -> packaging/_version_build.txt (exe đọc, không cần git)
$ver = ""
try { $ver = (git describe --tags --always --dirty 2>$null | Out-String).Trim() } catch { $ver = "" }
if (-not $ver) { $ver = "dev" }
[IO.File]::WriteAllText((Join-Path $PSScriptRoot "packaging\_version_build.txt"), $ver, (New-Object Text.UTF8Encoding $false))
Write-Host "Phiên bản build: $ver"

# 2. Dọn
if ($Clean) {
    Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
}

# 3. PyInstaller
& $Python -m PyInstaller --noconfirm --clean secjit.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller thất bại (exit $LASTEXITCODE)" }

# 4. Kích thước + SHA256
$sums = @()
foreach ($name in "secjit-scan.exe") {
    $f = Join-Path $PSScriptRoot "dist\$name"
    if (-not (Test-Path $f)) { Write-Warning "Thiếu $f"; continue }
    $mb = [math]::Round((Get-Item $f).Length / 1MB, 1)
    $sha = (Get-FileHash -Algorithm SHA256 $f).Hash.ToLower()
    Write-Host ("{0,-22} {1,8} MB  sha256={2}" -f $name, $mb, $sha)
    $sums += "$sha  $name"
}
[IO.File]::WriteAllText((Join-Path $PSScriptRoot "dist\SHA256SUMS.txt"), (($sums -join "`n") + "`n"), (New-Object Text.UTF8Encoding $false))
Write-Host "Xong: dist\SHA256SUMS.txt"
