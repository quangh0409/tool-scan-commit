"""Thông báo hệ thống khi run xong/lỗi. Không bao giờ raise.

toast(title, msg) -> {"ok": bool, "method": "winotify|powershell|notify-send|stdout", "detail": str}
- Windows: winotify nếu có (không bắt buộc) → PowerShell WinRT ToastNotificationManager.
- Linux/macOS: notify-send nếu có.
- Fallback: in ra stdout.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

IS_WIN = os.name == "nt"
APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
TIMEOUT_S = 15

_PS_TEMPLATE = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@'
<toast><visual><binding template="ToastGeneric"><text>{title}</text><text>{msg}</text></binding></visual></toast>
'@)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app_id}').Show($toast)
"""


def _stdout(title: str, msg: str, why: str) -> dict:
    try:
        print(f"[{title}] {msg}", flush=True)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "method": "stdout", "detail": why}


def _winotify(title: str, msg: str, app_id: str) -> dict | None:
    try:
        from winotify import Notification  # type: ignore  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — không cài → bỏ qua
        return None
    try:
        Notification(app_id=app_id, title=title, msg=msg).show()
        return {"ok": True, "method": "winotify", "detail": ""}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "method": "winotify", "detail": str(e)}


def _powershell(title: str, msg: str, app_id: str, timeout_s: float) -> dict:
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return {"ok": False, "method": "powershell", "detail": "không có powershell"}
    script = _PS_TEMPLATE.format(title=escape(title), msg=escape(msg), app_id=app_id.replace("'", "''"))
    try:
        r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                           capture_output=True, text=True, errors="replace", timeout=timeout_s,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0:
            return {"ok": True, "method": "powershell", "detail": ""}
        return {"ok": False, "method": "powershell", "detail": (r.stderr or r.stdout or "").strip()[-300:]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "method": "powershell", "detail": str(e)}


def _notify_send(title: str, msg: str, timeout_s: float) -> dict:
    exe = shutil.which("notify-send")
    if not exe:
        return {"ok": False, "method": "notify-send", "detail": "không có notify-send"}
    try:
        r = subprocess.run([exe, "--app-name=SecJIT", title, msg], capture_output=True, text=True,
                           errors="replace", timeout=timeout_s)
        return {"ok": r.returncode == 0, "method": "notify-send", "detail": (r.stderr or "").strip()[-300:]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "method": "notify-send", "detail": str(e)}


def toast(title: str, msg: str, app_id: str = APP_ID, timeout_s: float = TIMEOUT_S) -> dict:
    """Hiện thông báo; mọi thất bại → in stdout, không raise."""
    title = str(title or "SecJIT")
    msg = str(msg or "")
    try:
        if IS_WIN or sys.platform == "win32":
            r = _winotify(title, msg, app_id)
            if r and r["ok"]:
                return r
            r = _powershell(title, msg, app_id, timeout_s)
        else:
            r = _notify_send(title, msg, timeout_s)
        if r["ok"]:
            return r
        return _stdout(title, msg, f"{r['method']}: {r['detail']}")
    except Exception as e:  # noqa: BLE001
        return _stdout(title, msg, f"{type(e).__name__}: {e}")


__all__ = ["toast", "APP_ID"]
