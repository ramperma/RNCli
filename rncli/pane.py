"""Panel: cabecera con el nombre del agente + la terminal."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .agents import Agent
from .pty_session import PtySession
from .terminal import TerminalWidget
from .theme import theme


class PaneWidget(QFrame):
    """Un agente ejecutándose en su propia terminal."""

    closeRequested = Signal(object)
    focusRequested = Signal(object)
    exited = Signal(object)
    inputReady = Signal(object, bytes)
    hostKeyRequested = Signal(object)
    userFocusRequested = Signal(object)
    directoryDropped = Signal(object, str)

    def __init__(self, agent: Agent, settings, cwd: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.agent = agent
        self.settings = settings
        self.cwd = cwd or settings.start_dir or os.path.expanduser("~")
        self.session: PtySession | None = None
        self.terminal: TerminalWidget | None = None
        self.title = agent.name
        self._grave: list[PtySession] = []

        self.setObjectName("Pane")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._build_header()
        self.start()

    # ------------------------------------------------------------------ cabecera
    def _build_header(self) -> None:
        self.header = QWidget(self)
        self.header.setObjectName("PaneHeader")
        self.header.setFixedHeight(26)
        layout = QHBoxLayout(self.header)
        layout.setContentsMargins(6, 0, 4, 0)
        layout.setSpacing(6)

        self.dot = QLabel("●", self.header)
        self.dot.setStyleSheet(f"color: {self.agent.color}; font-size: 12px;")

        self.name_label = QLabel(self.agent.name, self.header)
        self.name_label.setObjectName("PaneTitle")

        self.status_label = QLabel("", self.header)
        self.status_label.setObjectName("PaneStatus")

        self.broadcast_label = QLabel("⇢ difusión", self.header)
        self.broadcast_label.setObjectName("PaneBroadcast")
        self.broadcast_label.setVisible(False)

        self.restart_button = QToolButton(self.header)
        self.restart_button.setText("↻")
        self.restart_button.setToolTip("Reiniciar el agente (Enter en la terminal también lo reinicia)")
        self.restart_button.setAutoRaise(True)
        self.restart_button.clicked.connect(self.restart)

        self.close_button = QToolButton(self.header)
        self.close_button.setText("✕")
        self.close_button.setToolTip("Cerrar este panel (Ctrl+W)")
        self.close_button.setAutoRaise(True)
        self.close_button.clicked.connect(lambda: self.closeRequested.emit(self))

        layout.addWidget(self.dot)
        layout.addWidget(self.name_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.broadcast_label)
        layout.addStretch(1)
        layout.addWidget(self.restart_button)
        layout.addWidget(self.close_button)

        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.header)
        outer.addWidget(self.body, 1)

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
        self.body_layout.addWidget(self.terminal)
        self.session.exited.connect(self._on_exited)
        self._set_status("")
        self.terminal.setFocus(Qt.FocusReason.OtherFocusReason)

    def _teardown(self) -> None:
        old_session, old_terminal = self.session, self.terminal
        self.session, self.terminal = None, None
        if old_terminal is not None:
            try:
                old_session.dataReceived.disconnect(old_terminal._feed)
            except (RuntimeError, TypeError):
                pass
            old_terminal.setParent(None)
            old_terminal.deleteLater()
        if old_session is not None:
            try:
                old_session.exited.disconnect(self._on_exited)
            except (RuntimeError, TypeError):
                pass
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
        self.setStyleSheet(f"#Pane {{ border: 1px solid {pal['brightbrown']}; background: {pal['bg']}; }}")
        QTimer.singleShot(220, lambda: self.set_active(self.property("rncliActive") is True))

    def _on_input(self, data: bytes) -> None:
        self.inputReady.emit(self, bytes(data))

    def _on_directory_drop(self, path: str) -> None:
        self.directoryDropped.emit(self, path)

    def assign_directory(self, path: str) -> None:
        """Cambia el cwd del agente reiniciándolo en la carpeta elegida."""
        if not os.path.isdir(path):
            return
        self.cwd = os.path.realpath(path)
        self._set_status(f"abriendo · {os.path.basename(self.cwd) or self.cwd}")
        self.restart()

    def _on_osc_title(self, title: str) -> None:
        self.name_label.setToolTip(title)

    # ------------------------------------------------------------------ ajustes
    def apply_settings(self, settings, theme_name: str) -> None:
        self.settings = settings
        if self.terminal is not None:
            self.terminal.set_font(settings.font_family, settings.font_size)
            self.terminal.set_theme(theme_name)
        self.apply_theme(theme_name)

    def apply_theme(self, theme_name: str) -> None:
        pal = theme(theme_name)
        self.header.setStyleSheet(
            f"#PaneHeader {{ background: {pal['header_bg']}; }}"
            f"#PaneTitle {{ color: {pal['fg']}; font-weight: 600; }}"
            f"#PaneStatus {{ color: {pal['brightblack']}; }}"
            f"#PaneBroadcast {{ color: {pal['accent']}; font-weight: 600; }}"
        )
        self.setStyleSheet(
            f"#Pane {{ border: 1px solid {pal['border']}; background: {pal['bg']}; }}"
        )

    def set_broadcast(self, enabled: bool) -> None:
        self.broadcast_label.setVisible(enabled)

    def set_active(self, active: bool) -> None:
        self.setProperty("rncliActive", bool(active))
        pal = theme(self.settings.theme)
        color = pal["accent"] if active else pal["border"]
        self.setStyleSheet(
            f"#Pane {{ border: 1px solid {color}; background: {pal['bg']}; }}"
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
