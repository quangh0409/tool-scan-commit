"""runner.notify.toast: mock subprocess — PowerShell/notify-send/fallback stdout; không raise."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from runner import notify


@pytest.fixture
def no_winotify(monkeypatch):
    monkeypatch.setattr(notify, "_winotify", lambda *a, **k: None)


def test_toast_windows_powershell_script(monkeypatch, no_winotify, fake_docker):
    monkeypatch.setattr(notify, "IS_WIN", True)
    monkeypatch.setattr(notify.sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: r"C:\ps\powershell.exe" if n == "powershell" else None)
    r = notify.toast("SecJIT <xong>", "Run 'A' & B hoàn tất")
    assert r == {"ok": True, "method": "powershell", "detail": ""}
    cmd = fake_docker.calls[-1]
    assert cmd[0].endswith("powershell.exe") and "-NonInteractive" in cmd
    script = cmd[-1]
    assert "ToastNotificationManager" in script
    assert "SecJIT &lt;xong&gt;" in script and "Run 'A' &amp; B hoàn tất" in script   # XML đã escape


def test_toast_powershell_fails_falls_back_stdout(monkeypatch, no_winotify, fake_docker, capsys):
    monkeypatch.setattr(notify, "IS_WIN", True)
    monkeypatch.setattr(notify.sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "powershell" if n == "powershell" else None)
    fake_docker.responses.append((lambda c: True, (1, "", "Exception calling Show")))
    r = notify.toast("T", "M")
    assert r["ok"] is True and r["method"] == "stdout" and "Exception calling Show" in r["detail"]
    assert "[T] M" in capsys.readouterr().out


def test_toast_linux_notify_send(monkeypatch, fake_docker):
    monkeypatch.setattr(notify, "IS_WIN", False)
    monkeypatch.setattr(notify.sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/usr/bin/notify-send" if n == "notify-send" else None)
    r = notify.toast("T", "M")
    assert r["ok"] is True and r["method"] == "notify-send"
    assert fake_docker.calls[-1] == ["/usr/bin/notify-send", "--app-name=SecJIT", "T", "M"]


def test_toast_no_backend_stdout(monkeypatch, capsys):
    monkeypatch.setattr(notify, "IS_WIN", False)
    monkeypatch.setattr(notify.sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: None)
    r = notify.toast("T", "M")
    assert r["method"] == "stdout" and "notify-send" in r["detail"]
    assert "[T] M" in capsys.readouterr().out


def test_toast_never_raises(monkeypatch, no_winotify):
    monkeypatch.setattr(notify, "IS_WIN", True)
    monkeypatch.setattr(notify.sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "powershell")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("ps", 15)
    monkeypatch.setattr(subprocess, "run", boom)
    r = notify.toast(None, None)
    assert r["ok"] is True and r["method"] == "stdout" and "TimeoutExpired" in r["detail"] or "15" in r["detail"]


def test_toast_winotify_preferred(monkeypatch, fake_docker):
    monkeypatch.setattr(notify, "IS_WIN", True)
    monkeypatch.setattr(notify, "_winotify", lambda t, m, a: {"ok": True, "method": "winotify", "detail": ""})
    assert notify.toast("T", "M")["method"] == "winotify"
    assert not fake_docker.calls
