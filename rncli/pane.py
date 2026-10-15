"""Panel: cabecera con el nombre del agente + la terminal."""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollBar,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .agents import Agent
from .pty_session import PtySession
from .terminal import TerminalWidget
from .theme import theme

#: MIME interno para arrastrar un panel a otro sitio o a otra pestaña.
PANE_MIME = "application/x-rncli-pane"

_active_drag = None


def is_pane_drag(mime) -> bool:
    return mime is not None and mime.hasFormat(PANE_MIME)


def dragging_pane() -> PaneWidget | None:
    """Panel que se está arrastrando, o None si no hay un arrastre en curso."""
    return _active_drag


class PaneWidget(QFrame):
    """Un agente ejecutándose en su propia terminal."""

    closeRequested = Signal(object)
    focusRequested = Signal(object)
    exited = Signal(object)
    inputReady = Signal(object, bytes)
    hostKeyRequested = Signal(object)
    userFocusRequested = Signal(object)
    directoryDropped = Signal(object, str)
    filesDropped = Signal(object, list)
    paneMoveDropped = Signal(object, object, str)

    def __init__(self, agent: Agent, settings, cwd: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.agent = agent
        self.settings = settings
        self.cwd = cwd or settings.start_dir or os.path.expanduser("~")
        self.session: PtySession | None = None
        self.terminal: TerminalWidget | None = None
        self.scrollbar: QScrollBar | None = None
        self.title = agent.name
        self.pane_id = format(id(self), "x")
        self._grave: list[PtySession] = []
        self._drag_origin_global: QPoint | None = None
        self._drop_edge: str | None = None
        self._drag_widgets: tuple[QWidget, ...] = ()

        self.setObjectName("Pane")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAcceptDrops(True)

        self._build_header()
        self.start()

    # ------------------------------------------------------------------ cabecera
    def _build_header(self) -> None:
        self.header = QWidget(self)
        self.header.setObjectName("PaneHeader")
        self.header.setFixedHeight(34)
        self.header.setCursor(Qt.CursorShape.OpenHandCursor)
        self.header.setToolTip("Arrastra para reordenar o soltar en otra pestaña")
        layout = QHBoxLayout(self.header)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(8)

        self.dot = QLabel("●", self.header)
        self.dot.setStyleSheet(f"color: {self.agent.color}; font-size: 11px;")
        self.dot.setFixedWidth(14)

        self.name_label = QLabel(self.agent.name, self.header)
        self.name_label.setObjectName("PaneTitle")
        self.name_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self.path_label = QLabel("", self.header)
        self.path_label.setObjectName("PanePath")
        self.path_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.path_label.setMaximumWidth(220)

        self.status_label = QLabel("", self.header)
        self.status_label.setObjectName("PaneStatus")

        self.broadcast_label = QLabel("difusión", self.header)
        self.broadcast_label.setObjectName("PaneBroadcast")
        self.broadcast_label.setVisible(False)

        self.restart_button = QToolButton(self.header)
        self.restart_button.setObjectName("PaneButton")
        self.restart_button.setText("↻")
        self.restart_button.setToolTip("Reiniciar el agente (Enter en la terminal también lo reinicia)")
        self.restart_button.setAutoRaise(True)
        self.restart_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.restart_button.setFixedSize(24, 24)
        self.restart_button.clicked.connect(self.restart)

        self.close_button = QToolButton(self.header)
        self.close_button.setObjectName("PaneClose")
        self.close_button.setText("✕")
        self.close_button.setToolTip("Cerrar este panel")
        self.close_button.setAutoRaise(True)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setFixedSize(24, 24)
        self.close_button.clicked.connect(lambda: self.closeRequested.emit(self))

        layout.addWidget(self.dot)
        layout.addWidget(self.name_label)
        layout.addWidget(self.path_label, 1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.broadcast_label)
        layout.addWidget(self.restart_button)
        layout.addWidget(self.close_button)

        self.body = QWidget(self)
        self.body_layout = QHBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.header)
        outer.addWidget(self.body, 1)

        self._drag_widgets = (
            self.header,
            self.dot,
            self.name_label,
            self.path_label,
            self.status_label,
            self.broadcast_label,
        )
        for widget in self._drag_widgets:
            widget.installEventFilter(self)
            widget.setCursor(Qt.CursorShape.OpenHandCursor)

    # ------------------------------------------------------------------ arrastre
    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched in self._drag_widgets:
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_origin_global = event.globalPosition().toPoint()
                self.focusRequested.emit(self)
                self.userFocusRequested.emit(self)
            elif (
                etype == QEvent.Type.MouseMove
                and self._drag_origin_global is not None
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                delta = event.globalPosition().toPoint() - self._drag_origin_global
                if delta.manhattanLength() >= QApplication.startDragDistance():
                    self._drag_origin_global = None
                    self._begin_pane_drag()
                    return True
            elif etype == QEvent.Type.MouseButtonRelease:
                self._drag_origin_global = None
        return super().eventFilter(watched, event)

    def _begin_pane_drag(self) -> None:
        """Arranca un QDrag con este panel; el destino decide si reordena o cambia de pestaña."""
        global _active_drag
        _active_drag = self
        mime = QMimeData()
        mime.setData(PANE_MIME, QByteArray(self.pane_id.encode("utf-8")))
        host = self.window() if self.window() is not None else self
        drag = QDrag(host)
        drag.setMimeData(mime)
        pixmap = self.header.grab()
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(pixmap.rect().center())
        try:
            drag.exec(Qt.DropAction.MoveAction, Qt.DropAction.MoveAction)
        finally:
            _active_drag = None
            self.set_drop_edge(None)

    def accept_pane_drag(self, mime=None) -> bool:
        return is_pane_drag(mime) if mime is not None else dragging_pane() is not None

    def show_pane_drop(self, pos) -> None:
        source = dragging_pane()
        if source is None or source is self:
            self.set_drop_edge(None)
            return
        self.set_drop_edge(self._edge_at(pos))

    def receive_pane_drop(self, pos) -> None:
        source = dragging_pane()
        self.set_drop_edge(None)
        if source is None or source is self:
            return
        edge = self._edge_at(pos)
        # Diferir el movimiento: reparentar el origen mientras QDrag.exec sigue
        # activo cancela el arrastre o destruye el widget a medias.
        QTimer.singleShot(0, lambda s=source, t=self, e=edge: self.paneMoveDropped.emit(s, t, e))

    def _edge_at(self, pos) -> str:
        x = pos.x()
        y = pos.y()
        width = max(1, self.width())
        height = max(1, self.height())
        mode = None
        parent = self.parent()
        while parent is not None:
            mode = getattr(parent, "layout_mode", None)
            if isinstance(mode, str):
                break
            parent = parent.parent()
        # En paralelo solo cuenta izquierda/derecha; apilados, arriba/abajo.
        if mode in ("2v", "1"):
            return "left" if x < width / 2 else "right"
        if mode == "2h":
            return "top" if y < height / 2 else "bottom"
        if abs(x - width / 2) >= abs(y - height / 2):
            return "left" if x < width / 2 else "right"
        return "top" if y < height / 2 else "bottom"

    def set_drop_edge(self, edge: str | None) -> None:
        if edge == self._drop_edge:
            return
        self._drop_edge = edge
        self._apply_frame(self.property("rncliActive") is True)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if dragging_pane() is not None:
            event.acceptProposedAction()
            self.show_pane_drop(event.position())
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if dragging_pane() is not None:
            event.acceptProposedAction()
            self.show_pane_drop(event.position())
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.set_drop_edge(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        if dragging_pane() is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.receive_pane_drop(event.position())

    # ------------------------------------------------------------------ arranque
    def start(self) -> None:
        self._teardown()
        env = dict(self.agent.env)
        env.setdefault("RNCLI_PANE", "1")
        self.session = PtySession(
            self.agent.command,
            cwd=self.cwd,
            env=env,
            parent=self,
        )
        self.terminal = TerminalWidget(self.session, self.settings, self.body)
        self.terminal.restartRequested.connect(self.restart)
        self.terminal.bell.connect(self._on_bell)
        self.terminal.inputReady.connect(self._on_input)
        self.terminal.titleChanged.connect(self._on_osc_title)
        self.terminal.focusReceived.connect(lambda: self.focusRequested.emit(self))
        self.terminal.hostKeyPressed.connect(lambda: self.hostKeyRequested.emit(self))
        self.terminal.userFocusReceived.connect(lambda: self.userFocusRequested.emit(self))
        self.terminal.directoryDropped.connect(self._on_directory_drop)
        self.terminal.filesDropped.connect(self._on_files_drop)

        self.scrollbar = QScrollBar(Qt.Orientation.Vertical, self.body)
        self.scrollbar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scrollbar.sliderPressed.connect(lambda: self.focusRequested.emit(self))
        self.terminal.attach_scrollbar(self.scrollbar)

        self.body_layout.addWidget(self.terminal, 1)
        self.body_layout.addWidget(self.scrollbar, 0)
        self.session.exited.connect(self._on_exited)
        self._set_status("")
        self._refresh_header()
        self.apply_theme(self.settings.theme)
        self.terminal.setFocus(Qt.FocusReason.OtherFocusReason)

    def _teardown(self) -> None:
        old_session, old_terminal, old_scrollbar = (
            self.session,
            self.terminal,
            self.scrollbar,
        )
        self.session, self.terminal, self.scrollbar = None, None, None
        if old_terminal is not None:
            try:
                old_session.dataReceived.disconnect(old_terminal._feed)
            except (RuntimeError, TypeError):
                pass
            old_terminal.setParent(None)
            old_terminal.deleteLater()
        if old_scrollbar is not None:
            old_scrollbar.setParent(None)
            old_scrollbar.deleteLater()
        if old_session is not None:
            try:
                old_session.exited.disconnect(self._on_exited)
            except (RuntimeError, TypeError):
                pass
            # Sin esto, reiniciar (↻, Ctrl+Shift+R o cambio de carpeta) dejaba
            # el agente anterior vivo en segundo plano.
            old_session.terminate(force_after_ms=600)
            self._grave.append(old_session)
            QTimer.singleShot(4000, lambda s=old_session: self._prune_grave(s))

    def _prune_grave(self, session: PtySession) -> None:
        if session in self._grave:
            self._grave.remove(session)
        session.deleteLater()

    def restart(self) -> None:
        self.start()
        self.focusRequested.emit(self)

    # ------------------------------------------------------------------ estado
    def is_alive(self) -> bool:
        return self.session is not None and self.session.is_alive()

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))

    def _refresh_header(self) -> None:
        base = os.path.basename(self.cwd.rstrip(os.sep)) or self.cwd
        self.path_label.setText(base)
        self.path_label.setToolTip(self.cwd)

    def _on_exited(self, code: int) -> None:
        if self.sender() is not self.session:
            return  # evento de una sesión ya reemplazada
        self._set_status(f"finalizado · {code}")
        if self.terminal is not None:
            if code == 127:
                self.terminal.feed_text(
                    f"\n[rncli] no se pudo ejecutar «{self.agent.name}» "
                    f"({' '.join(self.agent.command)}).\n"
                )
                self.terminal.feed_text(
                    "[rncli] No aparece en el PATH. Opciones:\n"
                    "[rncli]  1) instálalo, o\n"
                    "[rncli]  2) abre la configuración (⚙ → Abrir config.json) y pon la "
                    "ruta absoluta en \"command\".\n"
                    "[rncli] Después pulsa ↻ para reintentar.\n"
                )
            else:
                self.terminal.feed_text(f"\n[rncli] «{self.agent.name}» terminó con código {code}.")
                self.terminal.feed_text("[rncli] Pulsa Enter o ↻ para reiniciarlo.\n")
        self.exited.emit(self)

    def _on_bell(self) -> None:
        """Aviso visual breve cuando el agente lanza un BEL."""
        pal = theme(self.settings.theme)
        self.setStyleSheet(
            f"#Pane {{ border: 1px solid {pal['brightbrown']}; border-radius: 8px; background: {pal['bg']}; }}"
        )
        QTimer.singleShot(220, lambda: self.set_active(self.property("rncliActive") is True))

    def _on_input(self, data: bytes) -> None:
        self.inputReady.emit(self, bytes(data))

    def _on_directory_drop(self, path: str) -> None:
        self.directoryDropped.emit(self, path)

    def _on_files_drop(self, paths: list) -> None:
        self.filesDropped.emit(self, list(paths))

    def assign_directory(self, path: str) -> None:
        """Cambia el cwd del agente reiniciándolo en la carpeta elegida."""
        if not os.path.isdir(path):
            return
        self.cwd = os.path.realpath(path)
        self._refresh_header()
        self._set_status(f"abriendo · {os.path.basename(self.cwd) or self.cwd}")
        self.restart()

    def _on_osc_title(self, title: str) -> None:
        self.name_label.setToolTip(title)
        drag_hint = "Arrastra para reordenar o soltar en otra pestaña"
        self.header.setToolTip(f"{title}\n\n{drag_hint}" if title else drag_hint)

    # ------------------------------------------------------------------ ajustes
    def apply_settings(self, settings, theme_name: str) -> None:
        self.settings = settings
        if self.terminal is not None:
            self.terminal.settings = settings
            self.terminal.set_font(settings.font_family, settings.font_size)
            self.terminal.set_theme(theme_name)
        self.apply_theme(theme_name)

    def apply_theme(self, theme_name: str) -> None:
        pal = theme(theme_name)
        muted = pal.get("muted", pal["header_fg"])
        surface = pal.get("surface", pal["header_bg"])
        self.header.setStyleSheet(
            f"#PaneHeader {{ background: {surface}; border-top-left-radius: 8px; "
            f"border-top-right-radius: 8px; }}"
            f"#PaneTitle {{ color: {pal['fg']}; font-weight: 600; }}"
            f"#PaneStatus, #PanePath {{ color: {muted}; }}"
            f"#PaneBroadcast {{ color: {pal['accent']}; font-weight: 600; }}"
        )
        self.set_active(self.property("rncliActive") is True)

    def set_broadcast(self, enabled: bool) -> None:
        self.broadcast_label.setVisible(enabled)

    def set_active(self, active: bool) -> None:
        self.setProperty("rncliActive", bool(active))
        self._apply_frame(bool(active))

    def _apply_frame(self, active: bool) -> None:
        pal = theme(self.settings.theme)
        color = pal["accent"] if active else pal["border"]
        drop = self._drop_edge
        if drop in ("left", "right", "top", "bottom"):
            accent = pal["accent"]
            edges = ("top", "right", "bottom", "left")
            parts = [
                f"border-{side}: {'4px' if side == drop else '1px'} solid "
                f"{accent if side == drop else color}"
                for side in edges
            ]
            self.setStyleSheet(
                f"#Pane {{ {'; '.join(parts)}; border-radius: 8px; background: {pal['bg']}; }}"
            )
            return
        self.setStyleSheet(
            f"#Pane {{ border: 1px solid {color}; border-radius: 8px; background: {pal['bg']}; }}"
        )

    def send(self, data: bytes) -> None:
        if self.session is not None:
            self.session.write(data)

    def shell_cwd(self) -> str:
        """Directorio actual del proceso (via /proc) o el de arranque."""
        pid = self.session.pid if self.session else None
        if pid:
            try:
                return os.readlink(f"/proc/{pid}/cwd")
            except OSError:
                pass
        return self.cwd

    def shutdown(self) -> None:
        if self.session is not None:
            self.session.kill_now()
        for session in list(self._grave):
            session.kill_now()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.focusRequested.emit(self)
        self.userFocusRequested.emit(self)
        if self.terminal is not None:
            self.terminal.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)
