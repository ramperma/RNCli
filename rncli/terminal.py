"""Widget de terminal: emula un VT100 con pyte y lo dibuja con QPainter."""

from __future__ import annotations

import math
import os
import re
import shlex

import pyte
from PySide6.QtCore import QEvent, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from .theme import brighten, resolve_color, theme

PAD_X = 6
PAD_Y = 4

#: CSI completo: ESC [ params intermediates final
CSI_RE = re.compile(rb"\x1b\[([0-9;:?<>=]*)([ -/]*)([@-~])")
#: Cuerpo de un CSI todavía incompleto (llega partido entre dos lecturas).
PARTIAL_CSI_RE = re.compile(rb"^[0-9;:?<>=[ -/]*$")
#: Prefijos privados que pyte interpreta mal (SGR, borrado de líneas...).
BAD_CSI_PREFIXES = (b">", b"<", b"=")

#: Teclas especiales -> secuencia ANSI (modo normal).
KEYS = {
    Qt.Key.Key_Return: b"\r",
    Qt.Key.Key_Enter: b"\r",
    Qt.Key.Key_Backspace: b"\x7f",
    Qt.Key.Key_Tab: b"\t",
    Qt.Key.Key_Escape: b"\x1b",
    Qt.Key.Key_Insert: b"\x1b[2~",
    Qt.Key.Key_Delete: b"\x1b[3~",
    Qt.Key.Key_PageUp: b"\x1b[5~",
    Qt.Key.Key_PageDown: b"\x1b[6~",
    Qt.Key.Key_Home: b"\x1b[H",
    Qt.Key.Key_End: b"\x1b[F",
    Qt.Key.Key_F1: b"\x1bOP",
    Qt.Key.Key_F2: b"\x1bOQ",
    Qt.Key.Key_F3: b"\x1bOR",
    Qt.Key.Key_F4: b"\x1bOS",
    Qt.Key.Key_F5: b"\x1b[15~",
    Qt.Key.Key_F6: b"\x1b[17~",
    Qt.Key.Key_F7: b"\x1b[18~",
    Qt.Key.Key_F8: b"\x1b[19~",
    Qt.Key.Key_F9: b"\x1b[20~",
    Qt.Key.Key_F10: b"\x1b[21~",
    Qt.Key.Key_F11: b"\x1b[23~",
    Qt.Key.Key_F12: b"\x1b[24~",
}

CURSOR_KEYS = {
    Qt.Key.Key_Up: "A",
    Qt.Key.Key_Down: "B",
    Qt.Key.Key_Right: "C",
    Qt.Key.Key_Left: "D",
    Qt.Key.Key_Home: "H",
    Qt.Key.Key_End: "F",
}

# Modificadores que no deben acompañar a Tab ni a Escape-como-Host-Key.
_NAV_MODS = (
    Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.AltModifier
    | Qt.KeyboardModifier.MetaModifier
)
_HOST_MODS = _NAV_MODS | Qt.KeyboardModifier.ShiftModifier


def is_right_ctrl(event) -> bool:
    """Ctrl derecho (scan code 105 / keysym 65508), Host Key tipo VirtualBox."""
    return event.key() == Qt.Key.Key_Control and (
        event.nativeScanCode() == 105 or event.nativeVirtualKey() in (65508, 0xFFE4)
    )


def is_host_key(event, settings) -> bool:
    """True si la tecla libera el teclado hacia RNCli y no debe ir al agente."""
    if is_right_ctrl(event):
        return True
    if getattr(settings, "escape_key", "terminal") != "host":
        return False
    return event.key() == Qt.Key.Key_Escape and not bool(event.modifiers() & _HOST_MODS)


def tab_sequence(event) -> bytes | None:
    """Tab / Shift+Tab para el agente. None si Ctrl/Alt/Meta deben quedársela RNCli."""
    if event.key() not in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
        return None
    if event.modifiers() & _NAV_MODS:
        return None
    reverse = event.key() == Qt.Key.Key_Backtab or bool(
        event.modifiers() & Qt.KeyboardModifier.ShiftModifier
    )
    return b"\x1b[Z" if reverse else b"\t"


def local_drop_paths(mime) -> list[str]:
    """Rutas locales existentes que vienen en un arrastre (explorador u otro)."""
    if mime is None or not mime.hasUrls():
        return []
    paths: list[str] = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = os.path.realpath(os.path.expanduser(url.toLocalFile() or ""))
        if path and os.path.exists(path):
            paths.append(path)
    return list(dict.fromkeys(paths))


def split_drop_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    """Separa archivos (imagen, PDF, texto…) de carpetas."""
    files: list[str] = []
    directories: list[str] = []
    for path in paths:
        if os.path.isfile(path):
            files.append(path)
        elif os.path.isdir(path):
            directories.append(path)
    return files, directories


def quote_drop_paths(paths: list[str]) -> str:
    return " ".join(shlex.quote(path) for path in paths if path)


class TerminalWidget(QWidget):
    """Terminal con scrollback, selección, copiar/pegar y aviso de campana."""

    inputReady = Signal(bytes)      # el usuario tecleó algo
    focusReceived = Signal()
    userFocusReceived = Signal()
    hostKeyPressed = Signal()
    directoryDropped = Signal(str)
    filesDropped = Signal(list)
    restartRequested = Signal()
    bell = Signal()
    titleChanged = Signal(str)
    sizeChanged = Signal(int, int)

    def __init__(self, session, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.settings = settings

        self._screen = pyte.HistoryScreen(80, 24, history=int(settings.scrollback), ratio=0.5)
        self._stream = pyte.ByteStream(self._screen)
        self._scroll_offset = 0
        self._blank = pyte.screens.Char(" ")
        self._last_title = ""
        self._bell_pending = False
        self._raw_tail = b""

        self._sel_anchor: tuple[int, int] | None = None
        self._sel_focus: tuple[int, int] | None = None
        self._sel_press: tuple[int, int] | None = None
        self._sel_visible = False
        self._last_cursor: tuple[int, int] | None = None

        self._font = QFont(settings.font_family)
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._font.setFixedPitch(True)
        self._font.setPointSizeF(max(6.0, float(settings.font_size)))
        self._recalc_fonts()

        self._palette = theme(settings.theme)
        self._bg_default = QColor(self._palette["bg"])
        self._fg_default = QColor(self._palette["fg"])
        self._cursor_color = QColor(self._palette["cursor"])
        self._selection_color = QColor(self._palette["selection"])
        self._fg_cache: dict = {}
        self._bg_cache: dict = {}
        self._apply_palette()

        self._cursor_on = True
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(530)
        self._blink_timer.timeout.connect(self._blink)
        if settings.cursor_blink:
            self._blink_timer.start()

        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setAcceptDrops(True)
        self.setMinimumSize(self._cell_w * 20 + 2 * PAD_X, self._cell_h * 5 + 2 * PAD_Y)
        self.setMouseTracking(True)

        # Campana: si pyte expone `bell` como método, lo interceptamos.
        if callable(getattr(self._screen, "bell", None)):
            self._screen.bell = self._emit_bell  # type: ignore[method-assign]

        session.dataReceived.connect(self._feed)

    # ------------------------------------------------------------------ tamaño
    @staticmethod
    def _apply_font_strategy(font: QFont) -> None:
        """Sin antialias LCD: al pintar celda a celda deja franjas azul/rojo."""
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        font.setStyleStrategy(
            QFont.StyleStrategy.NoSubpixelAntialias | QFont.StyleStrategy.PreferMatch
        )

    def _recalc_fonts(self) -> None:
        self._apply_font_strategy(self._font)
        self._font_bold = QFont(self._font)
        self._font_bold.setBold(True)
        self._font_italic = QFont(self._font)
        self._font_italic.setItalic(True)
        self._font_bold_italic = QFont(self._font)
        self._font_bold_italic.setBold(True)
        self._font_bold_italic.setItalic(True)
        for variant in (self._font_bold, self._font_italic, self._font_bold_italic):
            self._apply_font_strategy(variant)
        metrics = QFontMetricsF(self._font)
        # Celdas con medidas enteras: si no, los repintados parciales dejan franjas.
        self._cell_w = float(max(1, math.ceil(metrics.horizontalAdvance("M"))))
        self._cell_h = float(max(1, math.ceil(metrics.height())))
        self._ascent = metrics.ascent()

    def set_font(self, family: str, size: int) -> None:
        self._font = QFont(family)
        self._font.setPointSizeF(max(6.0, float(size)))
        self._recalc_fonts()
        self._apply_size()
        self.update()

    def set_theme(self, name: str) -> None:
        self._palette = theme(name)
        self._bg_default = QColor(self._palette["bg"])
        self._fg_default = QColor(self._palette["fg"])
        self._cursor_color = QColor(self._palette["cursor"])
        self._selection_color = QColor(self._palette["selection"])
        self._fg_cache.clear()
        self._bg_cache.clear()
        self._apply_palette()
        self.update()

    def _apply_palette(self) -> None:
        """El color de fondo del widget coincide con el tema (sin franjas negras)."""
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, self._bg_default)
        palette.setColor(QPalette.ColorRole.Base, self._bg_default)
        self.setPalette(palette)

    def _apply_size(self) -> None:
        cols = max(2, int((self.width() - 2 * PAD_X) // self._cell_w))
        rows = max(2, int((self.height() - 2 * PAD_Y) // self._cell_h))
        if (cols, rows) != (self._screen.columns, self._screen.lines):
            self._screen.resize(lines=rows, columns=cols)
            self.session.resize(cols, rows)
            self._scroll_offset = min(self._scroll_offset, self._history_len())
            self.sizeChanged.emit(cols, rows)
            self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 (API Qt)
        super().resizeEvent(event)
        self._apply_size()
        # El splitter termina de asignar el tamaño después del resizeEvent.
        # Repintar en el siguiente ciclo evita que quede visible solo una parte
        # del contenido hasta que el usuario vuelva a escribir.
        QTimer.singleShot(0, self._refresh_after_resize)

    def _refresh_after_resize(self) -> None:
        if not self.isVisible():
            return
        self._apply_size()
        self.update()

    def refresh(self) -> None:
        """Repinta todo el búfer sin cambiar posición, foco ni contenido."""
        self.update()

    def refresh_layout(self) -> None:
        """Sincroniza filas/columnas después de que un splitter cambie de tamaño."""
        self._apply_size()
        self.update()

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize

        return QSize(int(self._cell_w * 80 + 2 * PAD_X), int(self._cell_h * 24 + 2 * PAD_Y))

    def history_len(self) -> int:
        return self._history_len()

    def _history_len(self) -> int:
        return len(self._screen.history.top)

    # ------------------------------------------------------------------ entrada
    @staticmethod
    def sanitize(data: bytes, tail: bytes = b"") -> tuple[bytes, bytes]:
        """Quita secuencias CSI que pyte malinterpreta.

        Las TUI modernas envían peticiones con prefijo privado (por ejemplo
        ``ESC [ > 4 ; 1 m`` para modifyOtherKeys). pyte las trata como SGR y
        activa subrayado/negrita en toda la pantalla, así que las filtramos.
        Devuelve (datos_limpios, resto_incompleto).
        """
        if tail:
            data = tail + data
            tail = b""

        out = bytearray()
        pos = 0
        length = len(data)
        while pos < length:
            idx = data.find(b"\x1b[", pos)
            if idx < 0:
                chunk = data[pos:]
                if chunk.endswith(b"\x1b"):
                    tail = b"\x1b"
                    chunk = chunk[:-1]
                out += chunk
                break
            out += data[pos:idx]
            match = CSI_RE.match(data, idx)
            if match is None:
                pending = data[idx:]
                if len(pending) < 64 and PARTIAL_CSI_RE.match(pending[2:]):
                    tail = pending
                else:
                    out += b"\x1b["
                    pos = idx + 2
                    continue
                break
            pos = match.end()
            if match.group(1)[:1] in BAD_CSI_PREFIXES:
                continue
            out += match.group(0)
        return bytes(out), tail

    def _feed(self, data: bytes) -> None:
        before = self._history_len()
        data, self._raw_tail = self.sanitize(data, self._raw_tail)
        if not data:
            return
        try:
            self._stream.feed(data)
        except Exception:
            return
        grown = self._history_len() - before
        if self._scroll_offset > 0 and grown:
            # mantenemos a la vista el mismo contenido mientras llega salida nueva
            self._scroll_offset = min(self._history_len(), self._scroll_offset + grown)

        if not callable(getattr(self._screen, "bell", None)) and getattr(self._screen, "bell", False):
            self._screen.bell = False
            self._emit_bell()

        title = getattr(self._screen, "title", None)
        if isinstance(title, str) and title and title != self._last_title:
            self._last_title = title
            self.titleChanged.emit(title)

        if self.isVisible():
            self._schedule_repaint()
        else:
            self._screen.dirty.clear()

    def feed_text(self, text: str) -> None:
        """Escribe texto generado por la propia aplicación en el búfer."""
        self._feed(text.replace("\n", "\r\n").encode("utf-8", "replace"))

    def _schedule_repaint(self) -> None:
        self._screen.dirty.clear()
        self.update()

    def _emit_bell(self) -> None:
        self.bell.emit()

    def _blink(self) -> None:
        if not self.hasFocus() or self._scroll_offset > 0:
            return
        self._cursor_on = not self._cursor_on
        self.update()

    # ------------------------------------------------------------------ teclado
    def _is_host_key(self, event) -> bool:
        return is_host_key(event, self.settings)

    def focusNextPrevChild(self, _next: bool) -> bool:  # noqa: N802
        """Tab no cambia el foco: cursor-agent y otras TUI la necesitan."""
        return False

    def event(self, event) -> bool:
        """Captura Tab/Backtab antes de que QWidget los use para cambiar el foco."""
        if event.type() == QEvent.Type.KeyPress:
            data = tab_sequence(event)
            if data is not None:
                self.send_special(data)
                event.accept()
                return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)

        # VirtualBox-style Host Key: no se envía al agente y devuelve el
        # control al chasis de RNCli para que sus atajos funcionen.
        if self._is_host_key(event):
            self.hostKeyPressed.emit()
            event.accept()
            return

        # Atajos de la propia terminal
        if ctrl and shift and key == Qt.Key.Key_C:
            self.copy_selection()
            return
        if ctrl and shift and key == Qt.Key.Key_V:
            self.paste()
            return
        if ctrl and shift and key == Qt.Key.Key_A:
            self.select_all()
            return

        if self._scroll_offset and key not in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            self.scroll_to_bottom()

        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) and shift:
            self.scroll_by(10 if key == Qt.Key.Key_PageUp else -10)
            return

        if not self.session.is_alive():
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.restartRequested.emit()
            return

        data = self._encode_key(event, key, ctrl, alt, shift)
        if data:
            self.session.write(data)
            self.inputReady.emit(data)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if self._is_host_key(event):
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _encode_key(self, event, key, ctrl: bool, alt: bool, shift: bool) -> bytes:
        app_cursor = 1 in getattr(self._screen, "mode", set())

        # VT100 reverse-tab (Shift+Tab), usado por Pi y por muchas TUI.
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and shift and not ctrl:
            seq = b"\x1b[Z"
            return b"\x1b" + seq if alt else seq

        if key in CURSOR_KEYS:
            letter = CURSOR_KEYS[key]
            if app_cursor and not ctrl:
                seq = f"\x1bO{letter}".encode()
            else:
                prefix = f"\x1b[1;{2 if shift else 1}" if shift else "\x1b["
                seq = prefix.encode() + letter.encode()
            return b"\x1b" + seq if alt else seq

        if key in KEYS and not ctrl:
            seq = KEYS[key]
            return b"\x1b" + seq if alt else seq

        if ctrl:
            if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
                code = key - Qt.Key.Key_A + 1
                seq = bytes([code])
                return b"\x1b" + seq if alt else seq
            if key in (Qt.Key.Key_Space, Qt.Key.Key_2, Qt.Key.Key_At):
                return b"\x1b\x00" if alt else b"\x00"
            if key in (Qt.Key.Key_BracketLeft, Qt.Key.Key_3):
                return b"\x1b\x1b" if alt else b"\x1b"
            if key in (Qt.Key.Key_Backslash, Qt.Key.Key_4):
                return b"\x1c"
            return b""

        text = event.text()
        if not text:
            return b""
        if text == "\r":
            return b"\r"
        data = text.encode("utf-8", "replace")
        return b"\x1b" + data if alt else data

    def send_special(self, data: bytes) -> None:
        """Envía una secuencia que Qt puede consumir antes de keyPressEvent."""
        if self.session.is_alive():
            self.session.write(data)
            self.inputReady.emit(data)

    # ------------------------------------------------------------------ portapapeles
    def copy_selection(self) -> None:
        text = self.selected_text()
        if text:
            QApplication.clipboard().setText(text)

    def paste(self) -> None:
        text = QApplication.clipboard().text()
        if text:
            self._write_pasted_text(text, broadcast=True)

    def insert_paths(self, paths: list[str]) -> None:
        """Pega rutas entrecomilladas en ESTE terminal (imagen, PDF, texto, cualquier archivo)."""
        existing = [
            os.path.realpath(path) for path in paths if path and os.path.exists(path)
        ]
        quoted = quote_drop_paths(existing)
        if quoted:
            self._write_pasted_text(quoted + " ", broadcast=False)

    def _write_pasted_text(self, text: str, *, broadcast: bool) -> None:
        if not self.session.is_alive() or not text:
            return
        text = text.replace("\r\n", "\r").replace("\n", "\r")
        bracketed = 2004 in getattr(self._screen, "mode", set())
        data = (f"\x1b[200~{text}\x1b[201~" if bracketed else text).encode("utf-8", "replace")
        self.session.write(data)
        if broadcast:
            self.inputReady.emit(data)

    def select_all(self) -> None:
        self._sel_anchor = (0, 0)
        self._sel_focus = (self._history_len() + self._screen.lines - 1, self._screen.columns - 1)
        self._sel_visible = True
        self.update()

    def _clear_selection(self) -> None:
        self._sel_anchor = None
        self._sel_focus = None
        self._sel_press = None
        self._sel_visible = False

    def _selection_rows(self) -> tuple[int, int]:
        if not self._sel_visible or self._sel_anchor is None or self._sel_focus is None:
            return (0, -1)
        start, end = sorted((self._sel_anchor, self._sel_focus))
        return start[0], end[0]

    def selected_text(self) -> str:
        if not self._sel_visible or self._sel_anchor is None or self._sel_focus is None:
            return ""
        start, end = sorted((self._sel_anchor, self._sel_focus))
        (r1, c1), (r2, c2) = start, end
        lines: list[str] = []
        columns = self._screen.columns
        for row in range(r1, r2 + 1):
            chars = self._row_abs(row)
            first = c1 if row == r1 else 0
            last = c2 if row == r2 else columns - 1
            first = max(0, min(columns - 1, first))
            last = max(first, min(columns - 1, last))
            text = "".join(
                (chars[col].data or "") for col in range(first, last + 1)
            )
            lines.append(text.rstrip())
        return "\n".join(lines)

    # ------------------------------------------------------------------ ratón
    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._blink_timer.stop()
        self._cursor_on = True
        if event.button() == Qt.MouseButton.LeftButton:
            # Un clic para enfocar no es una selección: si pintamos esa celda
            # queda un cuadrado azul permanente en cada terminal.
            self._clear_selection()
            self._sel_press = self._cell_at(event.position().x(), event.position().y())
            self.update()
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.paste()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if local_drop_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if local_drop_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        files, directories = split_drop_paths(local_drop_paths(event.mimeData()))
        if files:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.insert_paths(files)
            self.filesDropped.emit(files)
            event.acceptProposedAction()
            return
        if directories:
            self.directoryDropped.emit(directories[0])
            event.acceptProposedAction()
            return
        event.ignore()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton and self._sel_press is not None:
            cell = self._cell_at(event.position().x(), event.position().y())
            if cell is not None and cell != self._sel_press:
                self._sel_anchor = self._sel_press
                self._sel_focus = cell
                self._sel_visible = True
                self.update()
            elif cell == self._sel_press and self._sel_visible:
                self._sel_anchor = None
                self._sel_focus = None
                self._sel_visible = False
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._sel_press = None
            if self._sel_visible and self.settings.copy_on_select:
                self.copy_selection()
            if self.settings.cursor_blink:
                self._blink_timer.start()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        cell = self._cell_at(event.position().x(), event.position().y())
        if cell is None:
            return
        row, col = cell
        chars = self._row_abs(row)
        text = [chars[c].data for c in range(self._screen.columns)]
        start = col
        while start > 0 and (text[start - 1].isalnum() or text[start - 1] in "._-/"):
            start -= 1
        end = col
        while end < self._screen.columns - 1 and (text[end + 1].isalnum() or text[end + 1] in "._-/"):
            end += 1
        self._sel_press = None
        self._sel_anchor = (row, start)
        self._sel_focus = (row, end)
        self._sel_visible = True
        self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta == 0:
            return
        self.scroll_by(3 if delta > 0 else -3)
        event.accept()

    def scroll_by(self, lines: int) -> None:
        limit = self._history_len()
        new_offset = max(0, min(limit, self._scroll_offset + lines))
        if new_offset != self._scroll_offset:
            self._scroll_offset = new_offset
            self.update()

    def scroll_to_bottom(self) -> None:
        if self._scroll_offset:
            self._scroll_offset = 0
            self.update()

    def _cell_at(self, x: float, y: float) -> tuple[int, int] | None:
        """Celda bajo el ratón, acotada al grid (así el arrastre al margen coge el final)."""
        if self._cell_w <= 0 or self._cell_h <= 0 or self._screen.columns < 1:
            return None
        col = int((x - PAD_X) // self._cell_w)
        row = int((y - PAD_Y) // self._cell_h)
        col = max(0, min(self._screen.columns - 1, col))
        row = max(0, min(self._screen.lines - 1, row))
        base = self._history_len() - self._scroll_offset
        return (base + row, col)

    # ------------------------------------------------------------------ pintado
    def _row_abs(self, abs_row: int) -> list:
        """Fila (histórica o viva) como lista de Char, una por columna."""
        cols = self._screen.columns
        if abs_row < 0:
            return [self._blank] * cols
        hist = self._screen.history.top
        hlen = len(hist)
        if abs_row < hlen:
            row = hist[abs_row]
            return [row.get(col, self._blank) for col in range(cols)]
        y = abs_row - hlen
        if 0 <= y < self._screen.lines:
            row = self._screen.buffer[y]
            return [row[col] for col in range(cols)]
        return [self._blank] * cols

    def _fg(self, value, bold: bool, bright_variant: str | None) -> QColor:
        key = (value, bold)
        cached = self._fg_cache.get(key)
        if cached is not None:
            return cached
        if bold and bright_variant:
            color = QColor(self._palette.get(bright_variant, self._palette["fg"]))
        else:
            color = resolve_color(value, self._palette, "fg")
            if bold and value not in ("default", None) and str(value) not in self._palette:
                color = brighten(color)
        self._fg_cache[key] = color
        return color

    def _bg(self, value) -> QColor:
        key = value
        cached = self._bg_cache.get(key)
        if cached is not None:
            return cached
        color = resolve_color(value, self._palette, "bg")
        self._bg_cache[key] = color
        return color

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        pal = self._palette
        painter.fillRect(self.rect(), self._bg_default)

        cell_w, cell_h = max(1, int(self._cell_w)), max(1, int(self._cell_h))
        first = 0
        last = self._screen.lines - 1
        base = self._history_len() - self._scroll_offset
        sel_rows = self._selection_rows()
        sel_start, sel_end = (
            sorted((self._sel_anchor, self._sel_focus))
            if self._sel_visible and self._sel_anchor and self._sel_focus
            else (None, None)
        )

        for row in range(first, last + 1):
            y = int(PAD_Y + row * cell_h)
            chars = self._row_abs(base + row)

            if sel_start is not None and sel_rows[0] <= base + row <= sel_rows[1]:
                c_from, c_to = 0, self._screen.columns - 1
                if base + row == sel_start[0]:
                    c_from = sel_start[1]
                if base + row == sel_end[0]:
                    c_to = sel_end[1]
                painter.fillRect(
                    QRect(int(PAD_X + c_from * cell_w), y, (c_to - c_from + 1) * cell_w, cell_h),
                    self._selection_color,
                )

            run_text: list[str] = []
            run_x = 0
            run_pen = None
            x = int(PAD_X)
            for col in range(self._screen.columns):
                ch = chars[col]
                if ch.data == "":
                    x += cell_w
                    continue
                pen = (
                    ch.fg, ch.bg, ch.bold, ch.italics, ch.underscore, ch.strikethrough, ch.reverse,
                )
                if pen != run_pen:
                    self._flush_run(painter, run_text, run_x, y, run_pen)
                    run_text = []
                    run_pen = pen
                    run_x = x
                run_text.append(ch.data if ch.data else " ")
                x += cell_w
            self._flush_run(painter, run_text, run_x, y, run_pen)

        # Cursor: solo en el terminal con foco, y del tamaño exacto de la celda
        # para no dejar un pixel extra en la celda vecina.
        if (
            self.hasFocus()
            and self._cursor_on
            and not self._screen.cursor.hidden
            and self._scroll_offset == 0
        ):
            cx = self._screen.cursor.x
            cy = self._screen.cursor.y
            if 0 <= cy < self._screen.lines and 0 <= cx < self._screen.columns:
                rect_cursor = QRect(int(PAD_X + cx * cell_w), int(PAD_Y + cy * cell_h), cell_w, cell_h)
                chars = self._row_abs(base + cy)
                char = chars[cx].data or " "
                painter.fillRect(rect_cursor, self._cursor_color)
                painter.setFont(self._font)
                painter.setPen(self._bg_default)
                painter.save()
                painter.setClipRect(rect_cursor, Qt.ClipOperation.IntersectClip)
                painter.drawText(QPointF(rect_cursor.x(), rect_cursor.y() + self._ascent), char)
                painter.restore()
                self._last_cursor = (cx, cy)

        if self._scroll_offset:
            label = f"  SCROLL -{self._scroll_offset}  "
            painter.setFont(self._font)
            fm = QFontMetricsF(self._font)
            w = fm.horizontalAdvance(label) + 8
            bar = QRect(int(self.width() - w - 8), int(self.height() - cell_h - 8), int(w), int(cell_h))
            painter.fillRect(bar, QColor(pal["selection"]))
            painter.setPen(QColor(pal["fg"]))
            painter.drawText(bar, Qt.AlignmentFlag.AlignCenter, label.strip())

        # Borde de foco
        if self.hasFocus():
            pen = painter.pen()
            pen.setColor(QColor(pal["accent"]))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()

    def _flush_run(self, painter: QPainter, text: list[str], x: float, y: float, pen) -> None:
        if not text or pen is None:
            return
        fg_value, bg_value, bold, italics, underscore, strikethrough, reverse = pen
        bright = None
        if bold and isinstance(fg_value, str) and fg_value in self._palette and not fg_value.startswith("bright"):
            bright = "bright" + fg_value
        fg = self._fg(fg_value, bold, bright)
        bg = self._bg(bg_value)
        if reverse:
            fg, bg = (self._bg_default if bg_value == "default" else bg), (
                self._fg_default if fg_value == "default" else fg
            )
        content = "".join(text)
        cell_w = max(1, int(self._cell_w))
        cell_h = max(1, int(self._cell_h))
        origin_x = int(x)
        origin_y = int(y)

        if bg != self._bg_default or reverse:
            painter.fillRect(QRect(origin_x, origin_y, len(content) * cell_w, cell_h), bg)

        font = self._font
        if bold and italics:
            font = self._font_bold_italic
        elif bold:
            font = self._font_bold
        elif italics:
            font = self._font_italic
        painter.setFont(font)
        painter.setPen(fg)
        # Un carácter por celda, recortado a ella: si no, el glifo y el cursor
        # invaden el vecino y quedan manchas al mover el foco.
        baseline = origin_y + self._ascent
        for index, glyph in enumerate(content):
            cell = QRect(origin_x + index * cell_w, origin_y, cell_w, cell_h)
            painter.save()
            painter.setClipRect(cell, Qt.ClipOperation.IntersectClip)
            painter.drawText(QPointF(cell.x(), baseline), glyph)
            painter.restore()

        if underscore or strikethrough:
            pen_line = painter.pen()
            pen_line.setColor(fg)
            painter.setPen(pen_line)
            width = len(content) * cell_w
            if underscore:
                uy = origin_y + self._ascent + 2
                painter.drawLine(QPointF(origin_x, uy), QPointF(origin_x + width, uy))
            if strikethrough:
                sy = origin_y + self._ascent - cell_h * 0.28
                painter.drawLine(QPointF(origin_x, sy), QPointF(origin_x + width, sy))

    # ------------------------------------------------------------------ foco
    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._cursor_on = True
        if self.settings.cursor_blink:
            self._blink_timer.start()
        self.focusReceived.emit()
        if event.reason() == Qt.FocusReason.MouseFocusReason:
            self.userFocusReceived.emit()
        self.update()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self._blink_timer.stop()
        self._cursor_on = False
        self._last_cursor = None
        self.update()
