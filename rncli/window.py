"""Ventana principal: pestañas, paneles, diseños y atajos."""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, __version__
from .agents import Agent, pick_default_agent
from .config import LAYOUTS, Config, Settings, load_session, save_session
from .dialogs import (
    AgentChooserDialog,
    SettingsDialog,
    ShortcutsDialog,
    SudoDialog,
)
from .file_browser import FileBrowserWidget
from .layouts import LAYOUT_LABELS, LAYOUT_SHORT, WorkspaceWidget
from .terminal import TerminalWidget, is_host_key, tab_sequence
from .theme import app_stylesheet


class PromptBar(QLineEdit):
    """Barra inferior para enviar un texto al panel activo (o a todos)."""

    submitted = Signal(str, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._normal_placeholder = "Escribe y pulsa Enter para enviarlo al panel activo"
        self._host_placeholder = "MODO RNCli · atajos del chasis activos · Host Key para volver"
        self.setPlaceholderText(
            self._normal_placeholder
        )

    def set_host_mode(self, enabled: bool) -> None:
        self.setProperty("hostMode", bool(enabled))
        self.setPlaceholderText(self._host_placeholder if enabled else self._normal_placeholder)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            to_all = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            text = self.text()
            if text.strip():
                self.submitted.emit(text, to_all)
                self.clear()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.settings: Settings = config.settings
        self._zoom_applied = 0
        self._host_mode = False
        self._shortcut_actions: list[QAction] = []

        self.setWindowTitle(APP_NAME)
        self.resize(1400, 900)
        self.setWindowIcon(QGuiApplication.windowIcon())

        self._build_actions()
        self._build_toolbar()
        self._build_tabs()
        self._build_file_browser()
        self._build_statusbar()
        self._build_prompt()
        # Mientras una terminal tiene el foco, Ctrl+T/Ctrl+W/etc. pertenecen
        # al agente. Los atajos del chasis se habilitan con Ctrl derecho.
        self._set_app_shortcuts(False)
        self._restore_geometry()

        self._restore_or_create_session()
        self.apply_theme()
        self._update_status()

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        """Tab al agente; resto al terminal seleccionado; Host Key al chasis."""
        if event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(watched, event)

        focus = QApplication.focusWidget()
        data = tab_sequence(event)
        if data is not None and isinstance(focus, TerminalWidget) and not self._host_mode:
            # Qt usa Tab/Backtab para el foco. cursor-agent (y Pi con Shift+Tab)
            # necesitan esas teclas; el resto sigue yendo al terminal seleccionado.
            focus.send_special(data)
            event.accept()
            return True
        if self._host_mode and is_host_key(event, self.settings):
            self._return_keyboard_to_terminal()
            event.accept()
            return True
        if self._host_mode:
            action = self._host_action(event)
            if action is not None:
                action.trigger()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _host_key_hint(self) -> str:
        if self.settings.escape_key == "host":
            return "Ctrl derecho o Escape"
        return "Ctrl derecho"

    def _host_action(self, event) -> QAction | None:
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)

        if ctrl and shift and key == Qt.Key.Key_T:
            return self.act_new_pane
        if ctrl and not shift and key == Qt.Key.Key_T:
            return self.act_new_tab
        if ctrl and shift and key == Qt.Key.Key_W:
            return self.act_close_tab
        if ctrl and not shift and key == Qt.Key.Key_W:
            return self.act_close_pane
        if ctrl and shift and key == Qt.Key.Key_B:
            return self.act_broadcast
        if ctrl and shift and key == Qt.Key.Key_R:
            return self.act_restart
        if ctrl and shift and key == Qt.Key.Key_M:
            return self.act_maximize
        if ctrl and shift and key == Qt.Key.Key_C:
            return self._host_copy_action
        if ctrl and shift and key == Qt.Key.Key_V:
            return self._host_paste_action
        if ctrl and shift and key == Qt.Key.Key_A:
            return self._host_select_action
        if ctrl and key == Qt.Key.Key_Tab:
            return self.act_prev_tab if shift else self.act_next_tab
        if ctrl and key in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
            return self.act_zoom_in
        if ctrl and key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            return self.act_zoom_out
        if ctrl and key == Qt.Key.Key_0:
            return self.act_zoom_reset
        if ctrl and key == Qt.Key.Key_Q:
            return self.act_quit
        if alt:
            modes = {
                Qt.Key.Key_1: "1", Qt.Key.Key_2: "2v", Qt.Key.Key_3: "2h",
                Qt.Key.Key_4: "4", Qt.Key.Key_5: "6", Qt.Key.Key_0: "all",
            }
            if key in modes:
                return self.act_layouts[modes[key]]
            if key == Qt.Key.Key_Right:
                return self.act_focus_next
            if key == Qt.Key.Key_Left:
                return self.act_focus_prev
        if key == Qt.Key.Key_F1:
            return self.act_help
        if key == Qt.Key.Key_F2:
            return self.act_rename_tab
        if key == Qt.Key.Key_F11:
            return self.act_fullscreen
        return None

    # ------------------------------------------------------------------ acciones
    def _act(self, text: str, shortcut: str | None, slot, *, checkable: bool = False) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setProperty("rncliShortcut", shortcut)
            self._shortcut_actions.append(action)
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        self.addAction(action)
        return action

    def _set_app_shortcuts(self, enabled: bool) -> None:
        """Activa/desactiva atajos del chasis sin desactivar sus acciones de menú."""
        for action in self._shortcut_actions:
            shortcut = action.property("rncliShortcut")
            action.setShortcut(QKeySequence(str(shortcut)) if enabled and shortcut else QKeySequence())

    def _build_actions(self) -> None:
        self.act_new_tab = self._act("Nueva pestaña", "Ctrl+T", lambda: self.choose_agent(new_tab=True))
        self.act_new_pane = self._act(
            "Nuevo panel", "Ctrl+Shift+T", lambda: self.choose_agent(new_tab=False)
        )
        self.act_close_pane = self._act("Cerrar panel", "Ctrl+W", self.close_pane)
        self.act_close_tab = self._act("Cerrar pestaña", "Ctrl+Shift+W", self.close_tab)
        self.act_rename_tab = self._act("Renombrar pestaña", "F2", self.rename_tab)
        self.act_next_tab = self._act("Pestaña siguiente", "Ctrl+Tab", lambda: self._cycle_tab(1))
        self.act_prev_tab = self._act("Pestaña anterior", "Ctrl+Shift+Tab", lambda: self._cycle_tab(-1))
        self.act_quit = self._act("Salir", "Ctrl+Q", self.close)
        self.act_restart = self._act("Reiniciar agente", "Ctrl+Shift+R", self.restart_active)
        self.act_focus_next = self._act("Panel siguiente", "Alt+Right", lambda: self._focus(1))
        self.act_focus_prev = self._act("Panel anterior", "Alt+Left", lambda: self._focus(-1))
        self.act_zoom_in = self._act("Aumentar letra", "Ctrl+=", lambda: self.zoom(+1))
        self.act_zoom_in.setShortcuts([QKeySequence("Ctrl+="), QKeySequence("Ctrl++")])
        self.act_zoom_out = self._act("Reducir letra", "Ctrl+-", lambda: self.zoom(-1))
        self.act_zoom_reset = self._act("Tamaño normal", "Ctrl+0", lambda: self.zoom(reset=True))
        self.act_maximize = self._act(
            "Maximizar panel activo", "Ctrl+Shift+M", self.maximize_active
        )
        self.act_fullscreen = self._act("Pantalla completa", "F11", self.toggle_fullscreen, checkable=True)
        self.act_broadcast = self._act(
            "Difusión (escribir en todos)", "Ctrl+Shift+B", self.toggle_broadcast, checkable=True
        )
        self.act_settings = self._act("Ajustes…", None, self.open_settings)
        self.act_open_config = self._act("Abrir config.json", None, self.open_config)
        self.act_sudo = self._act("Sudo para agentes…", None, self.open_sudo)
        self.act_help = self._act("Atajos y ayuda", "F1", self.open_help)

        # Acciones internas que se disparan desde el Host Key aunque el foco
        # esté temporalmente en la barra inferior.
        self._host_copy_action = QAction("Copiar", self)
        self._host_copy_action.triggered.connect(lambda: self._terminal_call("copy_selection"))
        self._host_paste_action = QAction("Pegar", self)
        self._host_paste_action.triggered.connect(lambda: self._terminal_call("paste"))
        self._host_select_action = QAction("Seleccionar todo", self)
        self._host_select_action.triggered.connect(lambda: self._terminal_call("select_all"))

        self.layout_group = QActionGroup(self)
        self.layout_group.setExclusive(True)
        self.act_layouts: dict[str, QAction] = {}
        for index, mode in enumerate(LAYOUTS):
            shortcut = "Alt+0" if mode == "all" else f"Alt+{index + 1}"
            action = self._act(
                f"Diseño: {LAYOUT_LABELS[mode]}", shortcut, lambda _=False, m=mode: self.set_layout(m), checkable=True
            )
            self.layout_group.addAction(action)
            self.act_layouts[mode] = action

        self._build_menus()

    def _chrome_button(
        self,
        text: str,
        tooltip: str,
        slot=None,
        *,
        checkable: bool = False,
        object_name: str = "ChromeButton",
    ) -> QToolButton:
        button = QToolButton()
        button.setObjectName(object_name)
        button.setText(text)
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoRaise(False)
        if slot is not None:
            button.clicked.connect(slot)
        return button

    def _build_menus(self) -> None:
        bar = self.menuBar()

        session_menu = bar.addMenu("&Sesión")
        session_menu.addAction(self.act_new_tab)
        session_menu.addAction(self.act_new_pane)
        session_menu.addSeparator()
        session_menu.addAction(self.act_close_pane)
        session_menu.addAction(self.act_close_tab)
        session_menu.addAction(self.act_rename_tab)
        session_menu.addSeparator()
        session_menu.addAction(self.act_next_tab)
        session_menu.addAction(self.act_prev_tab)
        session_menu.addSeparator()
        self.act_merge_tabs = session_menu.addAction("Convertir pestañas en paneles")
        self.act_merge_tabs.setToolTip(
            "Mueve sus terminales a la pestaña actual para poder verlas juntas"
        )
        self.act_merge_tabs.triggered.connect(self.merge_tabs_into_current)
        session_menu.addSeparator()
        session_menu.addAction(self.act_quit)

        edit_menu = bar.addMenu("&Editar")
        copy_action = QAction("Copiar selección  (Ctrl+Shift+C)", self)
        copy_action.triggered.connect(lambda: self._terminal_call("copy_selection"))
        paste_action = QAction("Pegar  (Ctrl+Shift+V)", self)
        paste_action.triggered.connect(lambda: self._terminal_call("paste"))
        select_all = QAction("Seleccionar todo  (Ctrl+Shift+A)", self)
        select_all.triggered.connect(lambda: self._terminal_call("select_all"))
        send_all = QAction("Escribir a todos los paneles", self)
        send_all.triggered.connect(self.focus_prompt)
        for action in (copy_action, paste_action, select_all, send_all):
            edit_menu.addAction(action)

        view_menu = bar.addMenu("&Ver")
        layout_menu = view_menu.addMenu("Diseño")
        for mode in LAYOUTS:
            layout_menu.addAction(self.act_layouts[mode])
        view_menu.addSeparator()
        view_menu.addAction(self.act_focus_next)
        view_menu.addAction(self.act_focus_prev)
        view_menu.addAction(self.act_maximize)
        view_menu.addSeparator()
        view_menu.addAction(self.act_broadcast)
        view_menu.addSeparator()
        view_menu.addAction(self.act_zoom_in)
        view_menu.addAction(self.act_zoom_out)
        view_menu.addAction(self.act_zoom_reset)
        view_menu.addSeparator()
        view_menu.addAction(self.act_fullscreen)

        tools_menu = bar.addMenu("&Herramientas")
        tools_menu.addAction(self.act_restart)
        tools_menu.addSeparator()
        tools_menu.addAction(self.act_sudo)
        tools_menu.addAction(self.act_open_config)
        tools_menu.addAction(self.act_settings)

        help_menu = bar.addMenu("A&yuda")
        help_menu.addAction(self.act_help)
        about = QAction(f"Acerca de {APP_NAME} {__version__}", self)
        about.triggered.connect(self.open_about)
        help_menu.addAction(about)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Principal", self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        new_pane = self._chrome_button(
            "+ Panel",
            "Nuevo panel en esta pestaña (Ctrl+Shift+T)",
            lambda: self.choose_agent(new_tab=False),
        )
        new_tab = self._chrome_button(
            "Pestaña",
            "Nueva pestaña (Ctrl+T)",
            lambda: self.choose_agent(new_tab=True),
        )
        toolbar.addWidget(new_pane)
        toolbar.addWidget(new_tab)
        toolbar.addSeparator()

        caption = QLabel("DISEÑO")
        caption.setObjectName("LayoutCaption")
        toolbar.addWidget(caption)

        segment = QWidget()
        segment.setObjectName("LayoutSegment")
        row = QHBoxLayout(segment)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        self.layout_button_group = QButtonGroup(self)
        self.layout_button_group.setExclusive(True)
        self.layout_buttons: dict[str, QToolButton] = {}
        for mode in LAYOUTS:
            button = QToolButton()
            button.setObjectName("SegmentButton")
            button.setText(LAYOUT_SHORT[mode])
            shortcut = self.act_layouts[mode].property("rncliShortcut") or ""
            button.setToolTip(f"{LAYOUT_LABELS[mode]}  ({shortcut})")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _=False, m=mode: self.set_layout(m))
            self.layout_button_group.addButton(button)
            self.layout_buttons[mode] = button
            row.addWidget(button)
        toolbar.addWidget(segment)

        broadcast = self._chrome_button(
            "Difusión",
            "Lo que escribas se envía a todos los paneles de la pestaña (Ctrl+Shift+B)",
            checkable=True,
        )
        broadcast.toggled.connect(self._on_broadcast_button)
        self.broadcast_button = broadcast
        toolbar.addWidget(broadcast)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        files = self._chrome_button(
            "Explorador",
            "Mostrar u ocultar el explorador de archivos",
            self._toggle_file_browser,
            checkable=True,
        )
        self.file_button = files
        toolbar.addWidget(files)

        settings_button = self._chrome_button("Ajustes", "Ajustes de RNCli", self.open_settings)
        toolbar.addWidget(settings_button)

        more = self._chrome_button("···", "Más acciones")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(more)
        more_menu.addAction(self.act_merge_tabs)
        more_menu.addAction(self.act_restart)
        more_menu.addSeparator()
        more_menu.addAction(self.act_sudo)
        more_menu.addAction(self.act_help)
        more.setMenu(more_menu)
        toolbar.addWidget(more)

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabCloseRequested.connect(self.close_tab_at)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        plus = QToolButton()
        plus.setObjectName("IconButton")
        plus.setText("＋")
        plus.setToolTip("Nueva pestaña (Ctrl+T)")
        plus.setFixedSize(28, 28)
        plus.setAutoRaise(True)
        plus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        plus.clicked.connect(lambda: self.choose_agent(new_tab=True))
        self.tabs.setCornerWidget(plus, Qt.Corner.TopRightCorner)

        holder = QWidget(self)
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(0)
        holder_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(holder)

    def _build_file_browser(self) -> None:
        self.file_dock = QDockWidget("Explorador", self)
        self.file_dock.setObjectName("FileBrowserDock")
        self.file_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.file_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.file_browser = FileBrowserWidget(
            self.settings.start_dir,
            self.file_dock,
            show_hidden=self.settings.show_hidden_files,
        )
        self.file_browser.assignRequested.connect(self.assign_directory_to_active)
        self.file_browser.filesRequested.connect(self.insert_files_into_active)
        self.file_browser.newPanelRequested.connect(
            lambda path: self.choose_agent(new_tab=False, cwd_hint=path)
        )
        self.file_browser.showHiddenChanged.connect(self._on_show_hidden_changed)
        self.file_dock.setWidget(self.file_browser)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.file_dock)
        self.file_dock.setMinimumWidth(260)
        self.file_dock.resize(280, self.height())
        self.file_dock.visibilityChanged.connect(self.file_button.setChecked)
        self.file_button.setChecked(self.file_dock.isVisible())
        self.act_show_hidden = QAction("Mostrar archivos ocultos", self)
        self.act_show_hidden.setCheckable(True)
        self.act_show_hidden.setChecked(self.settings.show_hidden_files)
        self.act_show_hidden.setToolTip(
            "Archivos y carpetas que empiezan por «.» · Ctrl+H con el explorador enfocado"
        )
        self.act_show_hidden.triggered.connect(self._on_show_hidden_action)
        for menu_action in self.menuBar().actions():
            if menu_action.text().replace("&", "") == "Ver" and menu_action.menu() is not None:
                menu_action.menu().addSeparator()
                menu_action.menu().addAction(self.file_dock.toggleViewAction())
                menu_action.menu().addAction(self.act_show_hidden)
                break

    def _toggle_file_browser(self, visible: bool) -> None:
        self.file_dock.setVisible(visible)

    def _on_show_hidden_action(self, checked: bool) -> None:
        self.file_browser.set_show_hidden(bool(checked))

    def _on_show_hidden_changed(self, show: bool) -> None:
        show = bool(show)
        if self.act_show_hidden.isChecked() != show:
            self.act_show_hidden.blockSignals(True)
            self.act_show_hidden.setChecked(show)
            self.act_show_hidden.blockSignals(False)
        if self.settings.show_hidden_files == show:
            return
        self.settings.show_hidden_files = show
        self.config.settings = self.settings
        self.config.save()

    def assign_directory_to_active(self, path: str) -> None:
        workspace = self.workspace()
        pane = workspace.active_pane() if workspace else None
        if pane is not None:
            self.assign_directory_to_pane(pane, path)

    def assign_directory_to_pane(self, pane, path: str) -> None:
        if pane is None or not os.path.isdir(path):
            return
        pane.assign_directory(path)
        self.file_browser.set_root(path)
        self.statusBar().showMessage(
            f"{pane.agent.name} → {path} · reiniciando en esa carpeta", 5000
        )

    def insert_files_into_active(self, paths: list) -> None:
        workspace = self.workspace()
        pane = workspace.active_pane() if workspace else None
        if pane is None or pane.terminal is None:
            return
        pane.terminal.insert_paths(list(paths))
        pane.terminal.setFocus(Qt.FocusReason.OtherFocusReason)
        self._announce_files(pane, list(paths))

    def _on_files_dropped(self, pane, paths: list) -> None:
        self._announce_files(pane, list(paths))

    def _announce_files(self, pane, paths: list) -> None:
        names = ", ".join(os.path.basename(path) for path in paths[:4])
        extra = f" (+{len(paths) - 4})" if len(paths) > 4 else ""
        self.statusBar().showMessage(f"{pane.agent.name} ← {names}{extra}", 5000)

    def _build_statusbar(self) -> None:
        self.status_left = QLabel("", self)
        self.status_right = QLabel("", self)
        bar = self.statusBar()
        bar.addWidget(self.status_left, 1)
        bar.addPermanentWidget(self.status_right)

    def _build_prompt(self) -> None:
        container = QWidget(self)
        container.setObjectName("PromptContainer")
        container.setFixedHeight(52)
        self.prompt_container = container
        layout = QHBoxLayout(container)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)

        self.prompt_icon = QLabel("❯", container)
        self.prompt_icon.setObjectName("PromptIcon")
        layout.addWidget(self.prompt_icon)

        self.prompt = PromptBar(container)
        self.prompt.setObjectName("PromptBar")
        self.prompt.submitted.connect(self._on_prompt)
        layout.addWidget(self.prompt, 1)

        self.prompt_hint = QLabel("Enter  ·  panel activo", container)
        self.prompt_hint.setObjectName("PromptHint")
        layout.addWidget(self.prompt_hint)

        holder = self.centralWidget()
        holder.layout().addWidget(container)

    def _restore_geometry(self) -> None:
        geometry = (load_session() or {}).get("geometry") if self.settings.restore_session else None
        if isinstance(geometry, str) and geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
            except Exception:
                pass

    # ------------------------------------------------------------------ sesión
    def _restore_or_create_session(self) -> None:
        tabs = load_session().get("tabs", []) if self.settings.restore_session else []
        created = False
        for tab in tabs if isinstance(tabs, list) else []:
            panes = tab.get("panes") or []
            if not panes:
                continue
            workspace = self.add_workspace(str(tab.get("title") or "Sesión"))
            workspace.set_layout(str(tab.get("layout") or self.settings.default_layout))
            for pane in panes:
                agent = self.config.agent(str(pane.get("agent", "")))
                if agent is None:
                    continue
                workspace.add_pane(agent, str(pane.get("cwd") or self.settings.start_dir), focus=False)
            if workspace.count():
                created = True
                if tab.get("broadcast"):
                    workspace.set_broadcast(True)
            else:
                self._remove_workspace(workspace)
        if not created:
            self.new_tab()

    def _workspaces(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def workspace(self) -> WorkspaceWidget | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, WorkspaceWidget) else None

    def add_workspace(self, title: str = "Sesión") -> WorkspaceWidget:
        workspace = WorkspaceWidget(self.settings)
        workspace.titleChanged.connect(lambda text, w=workspace: self._on_title_changed(w, text))
        workspace.activeChanged.connect(self._on_workspace_active)
        workspace.panesChanged.connect(self._update_status)
        workspace.agentExited.connect(self._on_agent_exited)
        workspace.layoutChanged.connect(self._on_layout_changed)
        workspace.hostKeyRequested.connect(self._enter_host_mode)
        workspace.userFocusRequested.connect(self._exit_host_mode)
        workspace.directoryDropped.connect(self.assign_directory_to_pane)
        workspace.filesDropped.connect(self._on_files_dropped)
        index = self.tabs.addTab(workspace, title)
        self.tabs.setCurrentIndex(index)
        return workspace

    def _remove_workspace(self, workspace: WorkspaceWidget) -> None:
        index = self.tabs.indexOf(workspace)
        if index >= 0:
            self.tabs.removeTab(index)
        workspace.shutdown()
        workspace.setParent(None)
        workspace.deleteLater()

    def new_tab(self, agent: Agent | None = None, cwd: str = "") -> WorkspaceWidget:
        workspace = self.add_workspace("Sesión")
        agent = agent or self.default_agent()
        workspace.add_pane(agent, cwd or self.settings.start_dir)
        self._update_status()
        return workspace

    def default_agent(self) -> Agent:
        if self.settings.default_agent:
            found = self.config.agent(self.settings.default_agent)
            if found is not None:
                return found
        return pick_default_agent(self.config.agents)

    def choose_agent(self, *, new_tab: bool, cwd_hint: str = "") -> None:
        workspace = self.workspace()
        hint = cwd_hint or (
            workspace.active_pane().shell_cwd() if workspace and workspace.active_pane() else ""
        )
        dialog = AgentChooserDialog(self.config.agents, self.settings, self, cwd_hint=hint)
        if dialog.exec() != AgentChooserDialog.DialogCode.Accepted:
            return
        agent = dialog.chosen_agent()
        cwd = dialog.chosen_cwd()
        make_new_tab = new_tab or dialog.wants_new_tab()
        if make_new_tab or self.workspace() is None:
            workspace = self.new_tab(agent, cwd)
        else:
            workspace.add_pane(agent, cwd)
        self._update_status()

    def close_pane(self) -> None:
        workspace = self.workspace()
        pane = workspace.active_pane() if workspace else None
        if workspace is not None and pane is not None:
            workspace.close_pane(pane)

    def close_tab(self) -> None:
        self.close_tab_at(self.tabs.currentIndex())

    def close_tab_at(self, index: int) -> None:
        workspace = self.tabs.widget(index)
        if isinstance(workspace, WorkspaceWidget):
            self._remove_workspace(workspace)
        if self.tabs.count() == 0:
            self.new_tab()

    def merge_tabs_into_current(self) -> None:
        """Convierte las pestañas en paneles de la pestaña actual.

        Es el puente entre los dos conceptos que suelen confundirse: una pestaña
        es una sesión independiente; un panel es una terminal que se puede ver
        junto a otra. Los procesos siguen vivos durante el traslado.
        """
        target = self.workspace()
        if target is None or self.tabs.count() < 2:
            return

        current_index = self.tabs.currentIndex()
        others = [
            self.tabs.widget(index)
            for index in range(self.tabs.count())
            if index != current_index
        ]
        moved = 0
        for workspace in others:
            if not isinstance(workspace, WorkspaceWidget):
                continue
            panes = workspace.detach_panes()
            moved += len(panes)
            target.adopt_panes(panes, focus=False)
            index = self.tabs.indexOf(workspace)
            if index >= 0:
                self.tabs.removeTab(index)
            workspace.setParent(None)
            workspace.deleteLater()

        if moved:
            target.title = "Mosaico"
            target.set_layout("all" if target.count() > 2 else "2v")
            self._update_status()
            self.statusBar().showMessage(
                f"{moved} terminal(es) añadida(s) al mosaico. Ahora usa Diseño para elegir 1, 2 o todas.",
                6000,
            )

    def rename_tab(self) -> None:
        workspace = self.workspace()
        if workspace is None:
            return
        from PySide6.QtWidgets import QInputDialog

        title, ok = QInputDialog.getText(self, "Renombrar pestaña", "Nombre:", text=workspace.title)
        if ok and title.strip():
            workspace.title = title.strip()
            self._on_title_changed(workspace, title.strip())

    def _cycle_tab(self, step: int) -> None:
        count = self.tabs.count()
        if count:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % count)

    def _on_tab_changed(self, _index: int) -> None:
        workspace = self.workspace()
        if not self._host_mode:
            self._set_app_shortcuts(False)
        if workspace is not None:
            if not self._host_mode:
                workspace.focus_terminal()
            else:
                self.prompt.setFocus(Qt.FocusReason.ShortcutFocusReason)
            for mode, action in self.act_layouts.items():
                action.setChecked(mode == workspace.layout_mode)
            self.broadcast_button.blockSignals(True)
            self.broadcast_button.setChecked(workspace.broadcast)
            self.broadcast_button.blockSignals(False)
            self.act_broadcast.setChecked(workspace.broadcast)
        self._update_status()

    def _on_workspace_active(self, _pane) -> None:
        if not self._host_mode:
            self._set_app_shortcuts(False)
        self._update_status()

    def _exit_host_mode(self, _pane) -> None:
        """El usuario hizo clic en una terminal: devolverle el teclado."""
        self._host_mode = False
        self._set_app_shortcuts(False)
        self._set_prompt_host_mode(False)
        self._update_status()

    def _return_keyboard_to_terminal(self) -> None:
        """Host Key otra vez: sale de MODO RNCli y escribe en el panel seleccionado."""
        workspace = self.workspace()
        pane = workspace.active_pane() if workspace else None
        self._exit_host_mode(pane)
        if pane is not None and pane.terminal is not None:
            pane.terminal.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _enter_host_mode(self, pane) -> None:
        """VirtualBox-style Host Key: libera el foco de la TUI."""
        self._host_mode = True
        self._set_app_shortcuts(True)
        self._set_prompt_host_mode(True)
        self.prompt.setFocus(Qt.FocusReason.ShortcutFocusReason)
        hint = self._host_key_hint()
        self.statusBar().showMessage(
            "MODO RNCli: atajos activos. Ctrl+W, Ctrl+Shift+T, Alt+1… funcionan aquí. "
            f"Haz clic en una terminal o pulsa {hint} para escribir.",
            8000,
        )

    def _on_title_changed(self, workspace: WorkspaceWidget, text: str) -> None:
        index = self.tabs.indexOf(workspace)
        if index >= 0:
            self.tabs.setTabText(index, text)
            agents = ", ".join(pane.agent.name for pane in workspace.panes())
            self.tabs.setTabToolTip(index, f"{text}\n{agents}")
        self._update_title()

    def _update_title(self) -> None:
        workspace = self.workspace()
        if workspace is None:
            self.setWindowTitle(APP_NAME)
            return
        extra = f"  ·  {workspace.count()} paneles" if workspace.count() > 1 else ""
        self.setWindowTitle(f"{APP_NAME} — {workspace.title}{extra}")

    # ------------------------------------------------------------------ vistas
    def set_layout(self, mode: str) -> None:
        workspace = self.workspace()
        if workspace is None:
            return
        # Si el usuario creó agentes como pestañas y ahora pide un mosaico,
        # ofrecer la conversión explícita en vez de dejarle una vista que parece
        # no funcionar.
        if mode != "1" and workspace.count() <= 1 and self.tabs.count() > 1:
            answer = QMessageBox.question(
                self,
                "Ver terminales juntas",
                "Tienes terminales en pestañas separadas. ¿Quieres convertirlas en "
                "paneles de esta sesión para verlas juntas?\n\n"
                "Los agentes seguirán ejecutándose; solo cambia la organización visual.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.merge_tabs_into_current()
                workspace = self.workspace()
        workspace.set_layout(mode)
        self.act_layouts[mode].setChecked(True)
        self._update_status()

    def _on_layout_changed(self, mode: str) -> None:
        action = self.act_layouts.get(mode)
        if action is not None and not action.isChecked():
            action.setChecked(True)
        self._update_status()

    def _focus(self, step: int) -> None:
        workspace = self.workspace()
        if workspace is None:
            return
        workspace.focus_next() if step > 0 else workspace.focus_prev()

    def maximize_active(self) -> None:
        """Alterna entre ver solo el panel activo y verlos todos."""
        if self.act_layouts["1"].isChecked():
            self.set_layout("all")
        else:
            self.set_layout("1")

    def toggle_broadcast(self) -> None:
        self.set_broadcast(self.act_broadcast.isChecked())

    def _on_broadcast_button(self, checked: bool) -> None:
        if self.act_broadcast.isChecked() != checked:
            self.act_broadcast.setChecked(checked)
        self.set_broadcast(checked)

    def set_broadcast(self, enabled: bool) -> None:
        workspace = self.workspace()
        if workspace is not None:
            workspace.set_broadcast(enabled)
        self.broadcast_button.blockSignals(True)
        self.broadcast_button.setChecked(enabled)
        self.broadcast_button.blockSignals(False)
        self.act_broadcast.setChecked(enabled)
        self._update_status()

    def restart_active(self) -> None:
        workspace = self.workspace()
        pane = workspace.active_pane() if workspace else None
        if pane is not None:
            pane.restart()
            self._update_status()

    def zoom(self, delta: int = 0, *, reset: bool = False) -> None:
        base = self.config.settings.font_size
        if reset:
            size = base
        else:
            size = max(6, min(40, self.settings.font_size + delta))
        if size == self.settings.font_size and not reset:
            return
        self.settings.font_size = size
        self._apply_settings_to_workspaces()
        self.config.save()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _terminal_call(self, method: str) -> None:
        workspace = self.workspace()
        pane = workspace.active_pane() if workspace else None
        if pane is not None and pane.terminal is not None:
            getattr(pane.terminal, method)()

    def focus_prompt(self) -> None:
        self.prompt.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _set_prompt_host_mode(self, enabled: bool) -> None:
        self.prompt.set_host_mode(enabled)
        self.prompt_container.setProperty("hostMode", bool(enabled))
        self.prompt_container.style().unpolish(self.prompt_container)
        self.prompt_container.style().polish(self.prompt_container)
        self.prompt_container.update()
        self._update_prompt_hint()

    def _sync_layout_buttons(self) -> None:
        workspace = self.workspace()
        mode = workspace.layout_mode if workspace is not None else "1"
        for key, button in self.layout_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == mode)
            button.blockSignals(False)

    def _update_prompt_hint(self) -> None:
        if self._host_mode:
            self.prompt_hint.setText(f"{self._host_key_hint()}  ·  salir")
            return
        workspace = self.workspace()
        pane = workspace.active_pane() if workspace else None
        if pane is None:
            self.prompt_hint.setText("Enter  ·  enviar")
            return
        if workspace is not None and workspace.broadcast:
            self.prompt_hint.setText("Enter  ·  todos")
        else:
            self.prompt_hint.setText(f"Enter  ·  {pane.agent.name}")

    # ------------------------------------------------------------------ ajustes
    def apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyle("Fusion")
            app.setStyleSheet(app_stylesheet(self.settings.theme))

    def _apply_settings_to_workspaces(self) -> None:
        for workspace in self._workspaces():
            if isinstance(workspace, WorkspaceWidget):
                workspace.apply_settings(self.settings, self.settings.theme)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.config.agents, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        self.settings = dialog.result_settings(self.settings)
        self.config.settings = self.settings
        self.config.save()
        self.apply_theme()
        self._apply_settings_to_workspaces()
        self.file_browser.set_show_hidden(self.settings.show_hidden_files)
        self._update_status()

    def open_config(self) -> None:
        from .config import CONFIG_PATH

        if not CONFIG_PATH.exists():
            self.config.save()
        QApplication.clipboard().setText(str(CONFIG_PATH))
        QMessageBox.information(
            self,
            "config.json",
            f"Ruta copiada al portapapeles:\n\n{CONFIG_PATH}\n\n"
            "Edítala para añadir agentes, comandos y variables de entorno (por ejemplo claves de API). "
            "Los cambios se aplican al reiniciar RNCli.",
        )

    def open_sudo(self) -> None:
        dialog = SudoDialog(self)
        dialog.sendRequested.connect(self._run_sudo_bash)
        dialog.exec()

    def _run_sudo_bash(self, command: str) -> None:
        """Pega el comando de sudo en un panel Bash de esta ventana."""
        command = (command or "").strip()
        if not command:
            return
        workspace = self.workspace()
        if workspace is None:
            workspace = self.new_tab()
        pane = next((item for item in workspace.panes() if item.agent.id == "shell"), None)
        if pane is None:
            agent = self.config.agent("shell")
            if agent is None:
                from .agents import Agent

                agent = Agent(id="shell", name="Bash", command=["bash", "-l"])
            pane = workspace.add_pane(agent, self.settings.start_dir)
            if workspace.count() > 1 and workspace.layout_mode == "1":
                workspace.set_layout("2v")
            self.statusBar().showMessage(
                "Abriendo un Bash. El comando de sudo se pega en un momento…", 6000
            )
            QTimer.singleShot(900, lambda p=pane, c=command: self._send_bash_command(p, c))
            return
        workspace.focus_pane(pane)
        self._send_bash_command(pane, command)

    def _send_bash_command(self, pane, command: str) -> None:
        if pane is None or pane.session is None or not pane.is_alive():
            self.statusBar().showMessage(
                "El Bash aún no está listo. Copia el comando y pégalo cuando veas el prompt.",
                7000,
            )
            return
        payload = command.replace("\n", "\r")
        if not payload.endswith("\r"):
            payload += "\r"
        pane.send(payload.encode("utf-8", "replace"))
        if pane.terminal is not None:
            pane.terminal.setFocus(Qt.FocusReason.OtherFocusReason)
        self.statusBar().showMessage(
            f"{pane.agent.name}: comando de sudo enviado. Escribe la contraseña si la pide.",
            8000,
        )

    def open_help(self) -> None:
        ShortcutsDialog(self).exec()

    def open_about(self) -> None:
        QMessageBox.about(
            self,
            f"Acerca de {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>Multiplexor de terminales para agentes de IA.</p>"
            "<p>Lanza opencode, pi, cursor-agent, claude o gemini en paralelo, "
            "organízalos en pestañas y diseños (1, 2, 4, 6 o todos visibles) y "
            "muéstrales la misma orden con la difusión activada.</p>"
            "<p>Cada panel es una terminal real (pty + VT100 con pyte), así que las "
            "TUI funcionan tal cual.</p>"
            "<p style='color:gray'>Iconos: el tema del escritorio · Atajos: F1</p>",
        )

    # ------------------------------------------------------------------ eventos
    def _on_agent_exited(self, pane) -> None:
        self.statusBar().showMessage(
            f"«{pane.agent.name}» terminó (código {pane.session.returncode if pane.session else '?'}). "
            "Pulsa Enter en su panel o Ctrl+Shift+R para reiniciarlo.",
            8000,
        )
        self._update_status()

    def _on_prompt(self, text: str, to_all: bool) -> None:
        workspace = self.workspace()
        if workspace is None:
            return
        if to_all:
            workspace.send_to_all(text)
            self.statusBar().showMessage("Enviado a todos los paneles.", 3000)
        else:
            pane = workspace.active_pane()
            if pane is not None:
                pane.send(text.replace("\n", "\r").encode("utf-8", "replace"))
                if not pane.is_alive():
                    self.statusBar().showMessage(
                        "El panel no está vivo; pulsa Enter en la terminal para reiniciar.", 4000
                    )

    def _update_status(self) -> None:
        workspace = self.workspace()
        self._sync_layout_buttons()
        self._update_prompt_hint()
        if workspace is None:
            self.status_left.setText("Sin sesión")
            self.status_right.setText("")
            return
        pane = workspace.active_pane()
        if pane is None:
            left = "Pestaña vacía  ·  Ctrl+Shift+T añade un panel"
        else:
            state = "activo" if pane.is_alive() else "finalizado"
            left = f"{pane.agent.emoji}  {pane.agent.name}  ·  {pane.shell_cwd()}  ·  {state}"
        if self._host_mode:
            left = f"MODO RNCli  ·  {left}"
        self.status_left.setText(left)
        layout = LAYOUT_LABELS.get(workspace.layout_mode, workspace.layout_mode)
        extra = "  ·  difusión" if workspace.broadcast else ""
        self.status_right.setText(f"{workspace.count()} panel(es)  ·  {layout}{extra}")
        self._update_title()

    def closeEvent(self, event) -> None:  # noqa: N802
        alive = sum(
            1
            for workspace in self._workspaces()
            if isinstance(workspace, WorkspaceWidget)
            for pane in workspace.panes()
            if pane.is_alive()
        )
        if self.settings.confirm_exit and alive:
            answer = QMessageBox.question(
                self,
                "Cerrar RNCli",
                f"Hay {alive} agente(s) en marcha. ¿Cerrar de todas formas?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        if self.settings.restore_session:
            tabs = [workspace.state() for workspace in self._workspaces()]
            save_session(tabs, bytes(self.saveGeometry().toBase64()).decode())
        self._shutdown()
        event.accept()

    def _shutdown(self) -> None:
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        for workspace in self._workspaces():
            if isinstance(workspace, WorkspaceWidget):
                workspace.shutdown()
        self.config.save()

    def shutdown(self) -> None:
        """Cierre ordenado (lo usa también el manejador de señales)."""
        self._shutdown()
