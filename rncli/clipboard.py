"""Portapapeles del sistema: CLIPBOARD (Ctrl+C/V) y PRIMARY (selección / botón central).

En Linux hay dos buffers. Las terminales copian la selección al PRIMARY (pegar
con el botón central, entre paneles y hacia otras apps) y Ctrl+Shift+C/V usan
CLIPBOARD.

Qt en Wayland anuncia el portapapeles, pero Hyprland no entrega el contenido a
otras apps (``wl-paste`` espera hasta el timeout). ``wl-copy`` usa data-control
y sí llega a GTK, Electron y el resto. El búfer interno cubre el pegado entre
paneles aunque el compositor falle.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from PySide6.QtCore import QByteArray, QMimeData
from PySide6.QtGui import QClipboard, QGuiApplication

_primary_text = ""
_clipboard_text = ""
_tools: dict[str, str | None] = {}


def _tool(name: str) -> str | None:
    if name not in _tools:
        _tools[name] = shutil.which(name)
    return _tools[name]


def system_sync_enabled() -> bool:
    """False en pruebas: no pisar el portapapeles del escritorio."""
    if os.environ.get("RNCLI_NO_CLIPBOARD_SYNC"):
        return False
    qpa = os.environ.get("QT_QPA_PLATFORM", "")
    if qpa == "offscreen" or qpa.startswith("offscreen"):
        return False
    app = QGuiApplication.instance()
    if app is not None and app.platformName() == "offscreen":
        return False
    return True


def _platform() -> str:
    app = QGuiApplication.instance()
    if app is not None:
        name = app.platformName()
        if name:
            return name
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "xcb"
    return ""


def _clipboard() -> QClipboard | None:
    return QGuiApplication.clipboard()


def _mime(text: str) -> QMimeData:
    encoded = QByteArray(text.encode("utf-8"))
    mime = QMimeData()
    mime.setText(text)
    mime.setData("text/plain;charset=utf-8", encoded)
    mime.setData("UTF8_STRING", encoded)
    mime.setData("TEXT", encoded)
    mime.setData("STRING", encoded)
    return mime


def _set_qt(text: str, mode: QClipboard.Mode) -> None:
    cb = _clipboard()
    if cb is None:
        return
    if mode == QClipboard.Mode.Selection and not cb.supportsSelection():
        return
    cb.setMimeData(_mime(text), mode)


def _get_qt(mode: QClipboard.Mode) -> str:
    cb = _clipboard()
    if cb is None:
        return ""
    if mode == QClipboard.Mode.Selection and not cb.supportsSelection():
        return ""
    text = cb.text(mode) or ""
    if text:
        return text
    mime = cb.mimeData(mode)
    if mime is not None and mime.hasText():
        return mime.text() or ""
    return ""


def _run(args: list[str], *, payload: bytes | None, timeout: float) -> bytes | None:
    try:
        completed = subprocess.run(
            args,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
            start_new_session=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout if payload is None else b""


def _write_external(text: str, *, primary: bool) -> None:
    if not system_sync_enabled() or not text:
        return
    encoded = text.encode("utf-8")
    platform = _platform()
    wayland = platform == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
    if wayland and platform != "xcb":
        wl_copy = _tool("wl-copy")
        if wl_copy:
            args = [wl_copy, "--type", "text/plain"]
            if primary:
                args.append("--primary")
            if _run(args, payload=encoded, timeout=2.0) is not None:
                return
    xclip = _tool("xclip")
    if xclip and os.environ.get("DISPLAY"):
        selection = "primary" if primary else "clipboard"
        _run([xclip, "-selection", selection, "-in"], payload=encoded, timeout=2.0)


def _read_external(*, primary: bool) -> str:
    if not system_sync_enabled():
        return ""
    platform = _platform()
    wayland = platform == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
    if wayland and platform != "xcb":
        wl_paste = _tool("wl-paste")
        if wl_paste:
            args = [wl_paste, "-n"]
            if primary:
                args.append("--primary")
            data = _run(args, payload=None, timeout=0.35)
            if data:
                return data.decode("utf-8", "replace")
            return ""
    xclip = _tool("xclip")
    if xclip and os.environ.get("DISPLAY"):
        selection = "primary" if primary else "clipboard"
        data = _run([xclip, "-selection", selection, "-o"], payload=None, timeout=0.35)
        if data:
            return data.decode("utf-8", "replace")
    return ""


def set_clipboard(text: str) -> None:
    """Escribe el portapapeles global (Ctrl+V / Ctrl+Shift+V)."""
    global _clipboard_text
    if not text:
        return
    _clipboard_text = text
    _set_qt(text, QClipboard.Mode.Clipboard)
    _write_external(text, primary=False)


def set_primary(text: str) -> None:
    """Escribe la selección PRIMARY (botón central) y el búfer interno entre paneles."""
    global _primary_text
    if not text:
        return
    _primary_text = text
    _set_qt(text, QClipboard.Mode.Selection)
    _write_external(text, primary=True)


def set_both(text: str) -> None:
    set_clipboard(text)
    set_primary(text)


def clipboard_text() -> str:
    external = _read_external(primary=False)
    if external:
        return external
    return _get_qt(QClipboard.Mode.Clipboard) or _clipboard_text


def primary_text() -> str:
    external = _read_external(primary=True)
    if external:
        return external
    return _get_qt(QClipboard.Mode.Selection) or _primary_text


def paste_text(*, primary: bool = False) -> str:
    """Texto a pegar: PRIMARY (con reserva CLIPBOARD) o al revés."""
    if primary:
        return primary_text() or clipboard_text()
    return clipboard_text() or primary_text()


def reset_for_tests() -> None:
    global _primary_text, _clipboard_text
    _primary_text = ""
    _clipboard_text = ""
