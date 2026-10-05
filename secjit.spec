# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: 2 exe onefile dùng chung 1 Analysis.

  dist/secjit-scan.exe      console=True  — CLI: --version, --preflight --json, --profile F (headless), -m orchestrator.cli

Build: ./build_exe.ps1  (hoặc: python -m PyInstaller --noconfirm --clean secjit.spec)
"""
import importlib.util
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()  # noqa: F821 — SPECPATH do PyInstaller cấp
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def tree(src: str, dst: str) -> list:
    p = ROOT / src
    return [(str(p), dst)] if p.exists() else []


def importable(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:  # noqa: BLE001
        return False


# Dữ liệu kèm theo (CONTRACTS/TASKS đợt 2): nguồn orchestrator (để `python -m` fallback đọc), web GUI, fixture,
# Dockerfile (preflight build FSB/CodeQL), và nguồn các gói top-level; phiên bản build.
datas = (
    tree("src/orchestrator", "src/orchestrator")
    + tree("gui/web", "gui/web")
    + tree("gui/fixtures", "gui/fixtures")
    + tree("docker", "docker")
    + tree("preflight", "preflight")
    + tree("runner", "runner")
    + tree("registry", "registry")
    + tree("packaging/version.py", "packaging")          # launcher nạp theo đường dẫn (tránh trùng PyPI `packaging`)
    + tree("packaging/_version_build.txt", "packaging")
)

hiddenimports = []
for pkg in ("orchestrator", "gui", "runner", "registry", "preflight"):
    if importable(pkg):
        hiddenimports += collect_submodules(pkg)
# pywebview backend Windows (EdgeChromium/WebView2) + pythonnet; chỉ thêm nếu đã cài
for mod in ("webview", "webview.platforms.edgechromium", "webview.platforms.winforms", "clr", "clr_loader", "pythonnet"):
    if importable(mod.split(".")[0]):
        hiddenimports.append(mod)
hiddenimports += ["winreg", "sqlite3", "xml.etree.ElementTree", "http.server", "runpy"]

excludes = ["tkinter", "matplotlib", "numpy", "PIL", "pandas", "scipy", "playwright", "pytest", "IPython",
            "setuptools", "pip", "wheel", "PyQt5", "PyQt6", "PySide2", "PySide6", "gi", "webview.platforms.gtk",
            "webview.platforms.qt", "webview.platforms.cocoa", "webview.platforms.android"]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT), str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

common = dict(
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    runtime_tmpdir=None, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)

exe_cli = EXE(  # noqa: F821
    pyz, a.scripts, a.binaries, a.datas, [],
    name="secjit-scan", console=True, **common,
)
# 2026-10-05: BỎ secjit-scan-gui.exe (console=False). User chỉ giữ secjit-scan.exe: nhấp đúp mở cửa sổ app
# + cửa sổ console = log server backend. Bản noconsole còn làm mỗi lệnh docker/git bật 1 cửa sổ cmd.
