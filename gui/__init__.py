"""SecJIT Scan GUI — server HTTP stdlib + web tĩnh (vanilla JS). Xem CONTRACTS.md §9–10.

Chạy: ``python -m gui [--dev] [--mock] [--port N] [--no-browser]``.
"""
from __future__ import annotations

import sys
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parent
ROOT = GUI_DIR.parent
WEB_DIR = GUI_DIR / "web"
FIXTURES_DIR = GUI_DIR / "fixtures"

# Cho phép `import orchestrator.profile` khi chạy `python -m gui` từ gốc repo mà không set PYTHONPATH.
_src = str(ROOT / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

__all__ = ["GUI_DIR", "ROOT", "WEB_DIR", "FIXTURES_DIR"]
