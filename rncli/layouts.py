"""Espacio de trabajo: organiza los paneles en diseños (1, 2, 4, 6, todos)."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .agents import Agent
from .pane import PaneWidget
from .theme import theme

#: Diseño -> número máximo de paneles visibles (None = todos).
LAYOUT_CAPS: dict[str, int | None] = {
    "1": 1,
    "2v": 2,
    "2h": 2,
    "4": 4,
    "6": 6,
    "all": None,
}

LAYOUT_LABELS = {
    "1": "Solo el activo",
    "2v": "Dos en paralelo (izq/der)",
    "2h": "Dos apilados (arr/aba)",
    "4": "Rejilla 2×2",
    "6": "Rejilla 3×2",
    "all": "Todos visibles",
}

LAYOUT_SHORT = {
    "1": "1",
    "2v": "2",
    "2h": "↕2",
    "4": "4",
    "6": "6",
    "all": "Todos",
}

SPLITTER_HANDLE = 8


class WorkspaceWidget(QWidget):
    """Una pestaña: contiene N paneles y decide cuáles se ven."""

    activeChanged = Signal(object)
    panesChanged = Signal()
    titleChanged = Signal(str)
    paneInput = Signal(object, bytes)
    agentExited = Signal(object)
    layoutChanged = Signal(str)
    hostKeyRequested = Signal(object)
    userFocusRequested = Signal(object)
    directoryDropped = Signal(object, str)
    filesDropped = Signal(object, list)

    def __init__(self, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.title = "Sesión"
        self.layout_mode = settings.default_layout if settings.default_layout in LAYOUT_CAPS else "1"
        self.broadcast = False

        self._panes: list[PaneWidget] = []
        self._active = 0
        self._grave: list[PaneWidget] = []

        self._host = QWidget(self)
        self._host.setObjectName("WorkspaceHost")
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(10, 10, 10, 10)
        self._host_layout.setSpacing(0)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(self._host, 1)

        self._placeholder = QLabel(
            "Esta pestaña está vacía\n\nCtrl+Shift+T  ·  nuevo panel", self._host
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setObjectName("Placeholder")
        self._placeholder.setVisible(False)

    # ------------------------------------------------------------------ consultas
    def panes(self) -> list[PaneWidget]:
        return list(self._panes)

    def count(self) -> int:
        return len(self._panes)

    def active_pane(self) -> PaneWidget | None:
        if not self._panes:
            return None
        self._active = max(0, min(self._active, len(self._panes) - 1))
        return self._panes[self._active]

    def visible_panes(self) -> list[PaneWidget]:
        if not self._panes:
            return []
        cap = LAYOUT_CAPS.get(self.layout_mode, 1)
        if cap is None:
            cap = len(self._panes)
        cap = min(cap, len(self._panes))
        # Nunca rotar la lista al cambiar el foco: la posición física es una
        # decisión del usuario, no del programa. Solo el modo de una ventana
        # muestra exclusivamente el panel activo.
        if self.layout_mode == "1":
            active = self.active_pane()
            return [active] if active is not None else []
        return self._panes[:cap]

    # ------------------------------------------------------------------ paneles
    def add_pane(self, agent: Agent, cwd: str = "", focus: bool = True) -> PaneWidget:
        pane = PaneWidget(agent, self.settings, cwd, self._host)
        self._adopt_pane(pane, focus=focus)
        self._rebuild()
        if focus:
            self._focus_terminal()
        self.panesChanged.emit()
        self._update_title()
        return pane

    def _adopt_pane(self, pane: PaneWidget, focus: bool = True) -> None:
        """Añade un panel existente (usado al convertir pestañas en paneles)."""
        pane.setParent(self._host)
        pane.closeRequested.connect(self.close_pane)
        pane.focusRequested.connect(self.focus_pane)
        pane.exited.connect(self._on_pane_exited)
        pane.inputReady.connect(self.on_terminal_input)
        pane.hostKeyRequested.connect(self._on_host_key)
        pane.userFocusRequested.connect(self._on_user_focus)
        pane.directoryDropped.connect(self._on_directory_drop)
        pane.filesDropped.connect(self._on_files_drop)
        self._panes.append(pane)
        if focus:
            self._active = len(self._panes) - 1

    def adopt_panes(self, panes: list[PaneWidget], focus: bool = False) -> None:
        """Mueve paneles vivos desde otra pestaña a esta pestaña."""
        for pane in panes:
            self._adopt_pane(pane, focus=focus)
        if focus:
            self._active = max(0, len(self._panes) - 1)
        self._rebuild()
        self.panesChanged.emit()
        self._update_title()

    def detach_panes(self) -> list[PaneWidget]:
        """Desconecta y entrega los paneles sin terminar sus procesos."""
        panes = list(self._panes)
        self._panes.clear()
        for pane in panes:
            for signal, slot in (
                (pane.closeRequested, self.close_pane),
                (pane.focusRequested, self.focus_pane),
                (pane.exited, self._on_pane_exited),
                (pane.inputReady, self.on_terminal_input),
                (pane.hostKeyRequested, self._on_host_key),
                (pane.userFocusRequested, self._on_user_focus),
                (pane.directoryDropped, self._on_directory_drop),
                (pane.filesDropped, self._on_files_drop),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            pane.hide()
            pane.setParent(None)
        self._rebuild()
        self.panesChanged.emit()
        self._update_title()
        return panes

    def close_pane(self, pane: PaneWidget) -> None:
        if pane not in self._panes:
            return
        index = self._panes.index(pane)
        self._panes.remove(pane)
        pane.hide()
        pane.setParent(self._host)
        if pane.session is not None:
            pane.session.terminate(force_after_ms=600)
        self._grave.append(pane)
        QTimer.singleShot(2600, lambda p=pane: self._drop_grave(p))

        if self._panes:
            self._active = min(index, len(self._panes) - 1)
        else:
            self._active = 0
        self._rebuild()
        self.panesChanged.emit()
        self._update_title()
        self.activeChanged.emit(self.active_pane())

    def _drop_grave(self, pane: PaneWidget) -> None:
        if pane in self._grave:
            self._grave.remove(pane)
        try:
            pane.shutdown()
            pane.setParent(None)
            pane.deleteLater()
        except RuntimeError:
            pass  # el objeto Qt ya se había destruido

    def focus_pane(self, pane: PaneWidget) -> None:
        if pane not in self._panes:
            return
        index = self._panes.index(pane)
        if index != self._active:
            self._active = index
            # En mosaicos no reconstruimos el árbol: hacerlo movería los paneles
            # y destruiría las proporciones elegidas al arrastrar el splitter.
            if self.layout_mode == "1":
                self._rebuild()
            else:
                self._update_active_styles()
        # También se emite cuando ya era el activo: esto informa al chasis de
        # que el usuario volvió a hacer clic en la terminal desde MODO RNCli.
        self.activeChanged.emit(pane)
        self._focus_terminal()

    def focus_next(self) -> None:
        if len(self._panes) < 2:
            return
        self._active = (self._active + 1) % len(self._panes)
        if self.layout_mode == "1":
            self._rebuild()
        else:
            self._update_active_styles()
        self._focus_terminal()
        self.activeChanged.emit(self.active_pane())

    def focus_prev(self) -> None:
        if len(self._panes) < 2:
            return
        self._active = (self._active - 1) % len(self._panes)
        if self.layout_mode == "1":
            self._rebuild()
        else:
            self._update_active_styles()
        self._focus_terminal()
        self.activeChanged.emit(self.active_pane())

    def focus_terminal(self) -> None:
        self._focus_terminal()

    def _focus_terminal(self) -> None:
        pane = self.active_pane()
        if pane is not None and pane.terminal is not None:
            pane.terminal.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_pane_exited(self, pane: PaneWidget) -> None:
        if pane in self._panes:
            self.agentExited.emit(pane)

    def _on_host_key(self, pane: PaneWidget) -> None:
        if pane in self._panes:
            self.hostKeyRequested.emit(pane)

    def _on_user_focus(self, pane: PaneWidget) -> None:
        if pane in self._panes:
            self.userFocusRequested.emit(pane)

    def _on_directory_drop(self, pane: PaneWidget, path: str) -> None:
        if pane in self._panes:
            self.directoryDropped.emit(pane, path)

    def _on_files_drop(self, pane: PaneWidget, paths: list) -> None:
        if pane in self._panes:
            self.filesDropped.emit(pane, list(paths))

    # ------------------------------------------------------------------ diseño
    def set_layout(self, mode: str) -> None:
        if mode not in LAYOUT_CAPS or mode == self.layout_mode:
            return
        self.layout_mode = mode
        self._rebuild()
        self.layoutChanged.emit(mode)

    def _equalize(self, splitter: QSplitter) -> None:
        """Reparte el espacio a partes iguales (si no, QSplitter hereda tamaños viejos)."""
        count = splitter.count()
        if count <= 0:
            return
        horizontal = splitter.orientation() == Qt.Orientation.Horizontal
        total = self._host.width() if horizontal else self._host.height()
        if total <= 0:
            total = 900 if horizontal else 600
        share = max(40, int(total / count))
        splitter.setSizes([share] * count)

    def _make_row(self, panes: list[PaneWidget]) -> QWidget:
        if len(panes) == 1:
            return panes[0]
        splitter = QSplitter(Qt.Orientation.Horizontal, self._host)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(SPLITTER_HANDLE)
        for index, pane in enumerate(panes):
            splitter.addWidget(pane)
            splitter.setStretchFactor(index, 1)
        splitter.splitterMoved.connect(lambda *_: self._refresh_terminals(panes))
        self._equalize(splitter)
        return splitter

    def _rebuild(self) -> None:
        # 1) rescatar todos los paneles del árbol anterior (sin destruirlos)
        for pane in self._panes:
            pane.setParent(self._host)
            pane.hide()

        while self._host_layout.count():
            item = self._host_layout.takeAt(0)
            widget = item.widget()
            if widget is None or widget is self._placeholder:
                continue
            if isinstance(widget, PaneWidget):
                # Los paneles sólo se destruyen desde close_pane/_drop_grave.
                widget.hide()
                continue
            widget.setParent(None)
            widget.deleteLater()

        visible = self.visible_panes()
        pal = theme(self.settings.theme)

        if not self._panes:
            self._placeholder.setVisible(True)
            self._placeholder.setStyleSheet(f"#Placeholder {{ color: {pal['brightblack']}; }}")
            self._host_layout.addWidget(self._placeholder, 1)
            return

        self._placeholder.setVisible(False)
        if not visible:
            return

        cols = self._grid_columns(len(visible))
        if self.layout_mode == "2h":
            root: QWidget = self._make_column(visible)
        elif len(visible) == 1:
            root = visible[0]
        elif cols >= len(visible):
            root = self._make_row(visible)
        else:
            rows = [visible[i : i + cols] for i in range(0, len(visible), cols)]
            if len(rows) == 1:
                root = self._make_row(rows[0])
            else:
                splitter = QSplitter(Qt.Orientation.Vertical, self._host)
                splitter.setChildrenCollapsible(False)
                splitter.setHandleWidth(SPLITTER_HANDLE)
                for index, row in enumerate(rows):
                    splitter.addWidget(self._make_row(row))
                    splitter.setStretchFactor(index, 1)
                splitter.splitterMoved.connect(lambda *_: self._refresh_terminals(visible))
                self._equalize(splitter)
                root = splitter

        self._host_layout.addWidget(root, 1)
        root.show()
        for pane in visible:
            pane.show()
            pane.set_broadcast(self.broadcast)
        self._update_active_styles()
        # Tras añadir el root al layout, Qt calcula su geometría al volver al
        # event loop. Esta segunda pasada evita el primer frame recortado.
        QTimer.singleShot(0, lambda p=list(visible): self._refresh_terminals(p))

    def _update_active_styles(self) -> None:
        active = self.active_pane()
        for pane in self._panes:
            pane.set_active(pane is active)

    @staticmethod
    def _refresh_terminals(panes: list[PaneWidget]) -> None:
        for pane in panes:
            if pane.terminal is not None:
                pane.terminal.refresh_layout()

    def _make_column(self, panes: list[PaneWidget]) -> QWidget:
        if len(panes) == 1:
            return panes[0]
        splitter = QSplitter(Qt.Orientation.Vertical, self._host)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(SPLITTER_HANDLE)
        for index, pane in enumerate(panes):
            splitter.addWidget(pane)
            splitter.setStretchFactor(index, 1)
        splitter.splitterMoved.connect(lambda *_: self._refresh_terminals(panes))
        self._equalize(splitter)
        return splitter

    def _grid_columns(self, count: int) -> int:
        if self.layout_mode == "4":
            return 2
        if self.layout_mode == "6":
            return 3
        if self.layout_mode == "2v":
            return count
        if self.layout_mode == "2h":
            return 1
        return max(1, math.ceil(math.sqrt(count)))

    # ------------------------------------------------------------------ difusión
    def set_broadcast(self, enabled: bool) -> None:
        self.broadcast = bool(enabled)
        for pane in self._panes:
            pane.set_broadcast(self.broadcast)

    def on_terminal_input(self, pane: PaneWidget, data: bytes) -> None:
        """Lo que se teclea en un panel se replica en el resto si hay difusión."""
        if self.broadcast and data:
            for other in self._panes:
                if other is not pane and other.is_alive():
                    other.send(data)
        self.paneInput.emit(pane, data)

    def send_to_all(self, text: str) -> None:
        data = text.replace("\n", "\r").encode("utf-8", "replace")
        for pane in self._panes:
            if pane.is_alive():
                pane.send(data)

    # ------------------------------------------------------------------ ajustes
    def apply_settings(self, settings, theme_name: str) -> None:
        self.settings = settings
        for pane in self._panes:
            pane.apply_settings(settings, theme_name)
        pal = theme(theme_name)
        self._placeholder.setStyleSheet(f"#Placeholder {{ color: {pal['brightblack']}; }}")

    def _update_title(self) -> None:
        active = self.active_pane()
        if active is not None:
            suffix = "" if self.count() == 1 else f"  +{self.count() - 1}"
            self.title = f"{active.agent.name}{suffix}"
        else:
            self.title = "Vacía"
        self.titleChanged.emit(self.title)

    def state(self) -> dict:
        return {
            "title": self.title,
            "layout": self.layout_mode,
            "broadcast": self.broadcast,
            "panes": [{"agent": pane.agent.id, "cwd": pane.cwd} for pane in self._panes],
        }

    def shutdown(self) -> None:
        for pane in list(self._panes):
            pane.shutdown()
        for pane in list(self._grave):
            pane.shutdown()
