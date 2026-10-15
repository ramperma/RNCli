"""Diálogos: elegir agente, ajustes, atajos y utilidades de sudo."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path
from typing import ClassVar, NamedTuple

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QKeySequenceEdit,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, __version__
from .agents import Agent, KNOWN_AGENTS, catalog_agents, pick_default_agent
from .config import (
    HOST_KEY_LABELS,
    HOST_KEY_MODES,
    LAYOUTS,
    SHORTCUT_CLASSIC,
    SHORTCUT_DEFAULTS,
    SHORTCUT_LABELS,
    SHORTCUT_SECTIONS,
    Config,
    Settings,
    merged_shortcuts,
)
from .layouts import LAYOUT_LABELS
from .pane import PaneWidget
from .shell_env import reset_cache, resolve_executable
from .ssh_hosts import SshHost, ensure_ssh_identity
from .theme import THEME_LABELS

MD_GUIDE = Path(__file__).resolve().parents[1] / "sudo-config-strategies.md"


# --------------------------------------------------------------------------- agentes
class AddAgentDialog(QDialog):
    """Diálogo para configurar y añadir un agente o comando CLI personalizado."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · nuevo agente")
        self.setMinimumWidth(460)
        self._created_agent: Agent | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(12)

        title = QLabel("Añadir nuevo agente o herramienta CLI")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        root.addWidget(title)

        hint = QLabel(
            "Indica el comando y los detalles del agente. "
            "Se comprobará en tu PATH si el ejecutable está disponible."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("p. ej. Goose, Open Interpreter, Bash")
        form.addRow("Nombre *", self.name_edit)

        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("identificador único (ej. mi-agente, se autogenera si se omite)")
        form.addRow("Identificador", self.id_edit)

        self.cmd_edit = QLineEdit()
        self.cmd_edit.setPlaceholderText("comando a ejecutar, p. ej. goose o /usr/local/bin/aider")
        form.addRow("Comando *", self.cmd_edit)

        emoji_color_row = QHBoxLayout()
        self.emoji_edit = QLineEdit("🤖")
        self.emoji_edit.setFixedWidth(50)
        self.color_edit = QLineEdit("#818cf8")
        self.color_edit.setFixedWidth(90)
        emoji_color_row.addWidget(QLabel("Emoji:"))
        emoji_color_row.addWidget(self.emoji_edit)
        emoji_color_row.addSpacing(14)
        emoji_color_row.addWidget(QLabel("Color:"))
        emoji_color_row.addWidget(self.color_edit)
        emoji_color_row.addStretch(1)
        emoji_color_box = QWidget()
        emoji_color_box.setLayout(emoji_color_row)
        form.addRow("Apariencia", emoji_color_box)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("descripción breve para el selector (opcional)")
        form.addRow("Descripción", self.desc_edit)

        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        cmd_text = self.cmd_edit.text().strip()
        if not name or not cmd_text:
            QMessageBox.warning(
                self,
                "Campos obligatorios",
                "Debes introducir obligatoriamente un nombre y un comando.",
            )
            return

        command = shlex.split(cmd_text)
        if not command:
            QMessageBox.warning(self, "Comando no válido", "Introduce un comando válido.")
            return

        raw_id = self.id_edit.text().strip()
        if not raw_id:
            import re

            raw_id = re.sub(r"[^a-zA-Z0-9_\-]+", "-", name.lower()).strip("-") or command[0]

        self._created_agent = Agent(
            id=raw_id,
            name=name,
            command=command,
            emoji=self.emoji_edit.text().strip() or "🤖",
            color=self.color_edit.text().strip() or "#818cf8",
            description=self.desc_edit.text().strip(),
        )
        self.accept()

    def created_agent(self) -> Agent | None:
        return self._created_agent


class AgentManagerDialog(QDialog):
    """Asistente para escanear, seleccionar y activar agentes de IA y shells."""

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · asistente de agentes")
        self.resize(740, 680)
        self.config = config
        self._all_agents: list[Agent] = catalog_agents(config.agents)
        self._active_ids: set[str] = {a.id for a in config.agents}

        self._checkboxes: dict[str, QCheckBox] = {}
        self._cards: dict[str, QFrame] = {}
        self._badge_labels: dict[str, QLabel] = {}
        self._cmd_labels: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(12)

        title = QLabel("Asistente y gestor de agentes")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        root.addWidget(title)

        subtitle = QLabel(
            "Escanea tu equipo para detectar qué agentes de IA y shells están instalados en tu PATH. "
            "Marca los agentes que quieres ver activos en RNCli; los desmarcados desaparecerán "
            "automáticamente del selector."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("Hint")
        root.addWidget(subtitle)

        # Barra de acciones
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.btn_rescan = QPushButton("🔄 Volver a escanear")
        self.btn_rescan.setToolTip("Limpiar caché de ejecutables y volver a buscar en PATH.")
        self.btn_rescan.clicked.connect(self._rescan)
        toolbar.addWidget(self.btn_rescan)

        self.btn_select_installed = QPushButton("⚡ Seleccionar instalados")
        self.btn_select_installed.setToolTip("Marcar únicamente los agentes detectados en el sistema.")
        self.btn_select_installed.clicked.connect(self._select_installed)
        toolbar.addWidget(self.btn_select_installed)

        self.btn_all = QPushButton("✔ Todos")
        self.btn_all.clicked.connect(self._select_all)
        toolbar.addWidget(self.btn_all)

        self.btn_none = QPushButton("✖ Ninguno")
        self.btn_none.clicked.connect(self._select_none)
        toolbar.addWidget(self.btn_none)

        self.btn_add = QPushButton("➕ Añadir agente…")
        self.btn_add.setToolTip("Configurar un agente o CLI propio.")
        self.btn_add.clicked.connect(self._add_custom_agent)
        toolbar.addWidget(self.btn_add)

        toolbar.addStretch(1)
        root.addLayout(toolbar)

        # Filtro de búsqueda
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Filtrar por nombre, comando o estado…")
        self.search_edit.textChanged.connect(self._apply_filter)
        root.addWidget(self.search_edit)

        # Scroll área con tarjetas de agentes
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 4, 0, 4)
        self.cards_layout.setSpacing(8)

        self.scroll_area.setWidget(self.cards_container)
        root.addWidget(self.scroll_area, 1)

        for agent in self._all_agents:
            self.cards_layout.addWidget(self._create_agent_card(agent))

        self.cards_layout.addStretch(1)

        # Estado y resumen
        self.status_label = QLabel()
        self.status_label.setObjectName("Hint")
        root.addWidget(self.status_label)
        self._rescan()

        # Botones de pie
        buttons_box = QHBoxLayout()
        buttons_box.addStretch(1)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        buttons_box.addWidget(btn_cancel)

        btn_save = QPushButton("Guardar y aplicar")
        btn_save.setDefault(True)
        btn_save.setStyleSheet("font-weight: 600;")
        btn_save.clicked.connect(self._save_and_apply)
        buttons_box.addWidget(btn_save)

        root.addLayout(buttons_box)

    def _create_agent_card(self, agent: Agent) -> QFrame:
        card = QFrame()
        card.setObjectName("AgentCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        cb = QCheckBox(f"{agent.emoji}  {agent.name}")
        cb.setStyleSheet("font-size: 13px; font-weight: 600;")
        cb.setChecked(agent.id in self._active_ids)
        cb.toggled.connect(lambda _checked: self._update_summary())
        self._checkboxes[agent.id] = cb
        top_row.addWidget(cb, 1)

        badge = QLabel()
        self._badge_labels[agent.id] = badge
        top_row.addWidget(badge)

        known_ids = {a.id for a in KNOWN_AGENTS}
        if agent.id not in known_ids:
            del_btn = QPushButton("🗑")
            del_btn.setFixedSize(28, 26)
            del_btn.setToolTip("Eliminar agente personalizado")
            del_btn.clicked.connect(lambda _=False, a=agent: self._remove_custom_agent(a))
            top_row.addWidget(del_btn)

        layout.addLayout(top_row)

        info_row = QHBoxLayout()
        cmd_text = " ".join(agent.command)
        cmd_lbl = QLabel(f"Comando: {cmd_text}")
        cmd_lbl.setStyleSheet("font-family: monospace; font-size: 11px;")
        cmd_lbl.setObjectName("Hint")
        self._cmd_labels[agent.id] = cmd_lbl
        info_row.addWidget(cmd_lbl)

        if agent.description:
            info_row.addSpacing(16)
            desc_lbl = QLabel(agent.description)
            desc_lbl.setObjectName("Hint")
            desc_lbl.setStyleSheet("font-size: 11px;")
            info_row.addWidget(desc_lbl, 1)
        else:
            info_row.addStretch(1)

        layout.addLayout(info_row)
        self._cards[agent.id] = card
        return card

    def _update_badge(self, agent: Agent) -> None:
        badge = self._badge_labels.get(agent.id)
        if badge is None:
            return
        path = resolve_executable(agent.executable)
        if path:
            badge.setObjectName("AgentBadgeInstalled")
            badge.setText(f"● Instalado ({path})")
            badge.setToolTip(f"Ejecutable disponible en {path}")
        else:
            badge.setObjectName("AgentBadgeMissing")
            badge.setText("○ No instalado en PATH")
            badge.setToolTip(f"No se encontró «{agent.executable}» en el PATH del sistema.")
        badge.style().unpolish(badge)
        badge.style().polish(badge)

    def _rescan(self) -> None:
        reset_cache()
        for agent in self._all_agents:
            self._update_badge(agent)
        self._update_summary()

    def _select_installed(self) -> None:
        reset_cache()
        for agent in self._all_agents:
            is_installed = bool(resolve_executable(agent.executable))
            cb = self._checkboxes.get(agent.id)
            if cb is not None:
                cb.setChecked(is_installed)
            self._update_badge(agent)
        self._update_summary()

    def _select_all(self) -> None:
        for cb in self._checkboxes.values():
            cb.setChecked(True)
        self._update_summary()

    def _select_none(self) -> None:
        for cb in self._checkboxes.values():
            cb.setChecked(False)
        self._update_summary()

    def _apply_filter(self, query: str) -> None:
        q = query.strip().lower()
        for agent in self._all_agents:
            card = self._cards.get(agent.id)
            if card is None:
                continue
            if not q:
                card.setVisible(True)
                continue
            is_installed = bool(resolve_executable(agent.executable))
            status_text = "instalado" if is_installed else "no instalado"
            match = (
                q in agent.name.lower()
                or q in agent.id.lower()
                or q in " ".join(agent.command).lower()
                or q in agent.description.lower()
                or q in status_text
            )
            card.setVisible(match)

    def _add_custom_agent(self) -> None:
        dialog = AddAgentDialog(self)
        if dialog.exec() != AddAgentDialog.DialogCode.Accepted:
            return
        agent = dialog.created_agent()
        if agent is None:
            return
        existing = next((a for a in self._all_agents if a.id == agent.id), None)
        if existing is not None:
            QMessageBox.information(
                self,
                "Agente existente",
                f"Ya existe un agente con el identificador «{agent.id}».",
            )
            return
        self._all_agents.append(agent)
        self._active_ids.add(agent.id)
        card = self._create_agent_card(agent)
        self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
        self._update_badge(agent)
        self._update_summary()
        self.scroll_area.ensureWidgetVisible(card)

    def _remove_custom_agent(self, agent: Agent) -> None:
        card = self._cards.pop(agent.id, None)
        if card is not None:
            card.deleteLater()
        self._checkboxes.pop(agent.id, None)
        self._badge_labels.pop(agent.id, None)
        self._cmd_labels.pop(agent.id, None)
        self._all_agents = [a for a in self._all_agents if a.id != agent.id]
        self._active_ids.discard(agent.id)
        self._update_summary()

    def _update_summary(self) -> None:
        selected_count = sum(1 for cb in self._checkboxes.values() if cb.isChecked())
        installed_count = sum(1 for a in self._all_agents if resolve_executable(a.executable))
        total = len(self._all_agents)
        self.status_label.setText(
            f"Seleccionados: {selected_count} de {total} agentes  ·  "
            f"{installed_count} detectados en el sistema"
        )

    def _save_and_apply(self) -> None:
        selected_agents: list[Agent] = [
            agent
            for agent in self._all_agents
            if self._checkboxes.get(agent.id) and self._checkboxes[agent.id].isChecked()
        ]
        if not selected_agents:
            QMessageBox.warning(
                self,
                "Sin agentes seleccionados",
                "Debes seleccionar al menos un agente para poder usar RNCli.",
            )
            return

        self.config.agents = selected_agents
        selected_ids = {a.id for a in selected_agents}
        if (
            self.config.settings.default_agent
            and self.config.settings.default_agent not in selected_ids
        ):
            self.config.settings.default_agent = ""

        self.config.save()
        self.accept()


class AgentChooserDialog(QDialog):
    """Elige qué agente lanzar, en qué carpeta y si en pestaña nueva."""

    def __init__(
        self,
        agents: list[Agent],
        settings: Settings,
        parent=None,
        cwd_hint: str = "",
        config: Config | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · nuevo panel")
        self.setMinimumWidth(620)
        self._agents = list(agents)
        self._settings = settings
        self._config = config
        self._selected: Agent | None = None
        self._ssh = False

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        header_text = QVBoxLayout()
        title = QLabel("¿Qué agente quieres lanzar?")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        header_text.addWidget(title)
        hint = QLabel("Pulsa el número del agente o haz clic. Esc para cancelar.")
        hint.setObjectName("Hint")
        header_text.addWidget(hint)
        header_row.addLayout(header_text, 1)

        self.manage_button = QPushButton("⚙ Asistente de agentes…")
        self.manage_button.setToolTip(
            "Escanear el sistema en busca de agentes instalados, seleccionar y activar cuáles mostrar."
        )
        self.manage_button.clicked.connect(self._open_manager)
        header_row.addWidget(self.manage_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header_row)

        self._grid = QGridLayout()
        self._grid.setSpacing(10)
        self._grid.setVerticalSpacing(10)
        root.addLayout(self._grid)
        self._reload_grid()

        self.ssh_button = QToolButton()
        self.ssh_button.setObjectName("AgentButton")
        self.ssh_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.ssh_button.setText("⇄  Conexión SSH\nA un equipo remoto")
        self.ssh_button.setToolTip(
            "Abre una terminal remota por SSH: usuario, host, puerto, clave y opciones."
        )
        self.ssh_button.setMinimumHeight(52)
        self.ssh_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ssh_button.clicked.connect(self._choose_ssh)
        root.addWidget(self.ssh_button)

        form = QFormLayout()
        self.cwd_edit = QLineEdit(cwd_hint or settings.start_dir or os.path.expanduser("~"))
        browse = QPushButton("…")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse)
        cwd_row = QHBoxLayout()
        cwd_row.addWidget(self.cwd_edit, 1)
        cwd_row.addWidget(browse)
        cwd_box = QWidget()
        cwd_box.setLayout(cwd_row)
        form.addRow("Carpeta de trabajo", cwd_box)

        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("p.ej. opencode --model sonnet   (opcional)")
        form.addRow("Comando propio", self.custom_edit)
        self.new_tab_check = QCheckBox("Abrir en una pestaña nueva")
        form.addRow("", self.new_tab_check)
        root.addLayout(form)

        note = QLabel(
            "Los agentes marcados como «no instalado» se lanzarán igualmente: "
            "verás el aviso del sistema en el panel."
        )
        note.setWordWrap(True)
        note.setObjectName("Hint")
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self._accept_custom)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.custom_edit.returnPressed.connect(self._accept_custom)

    def _reload_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, agent in enumerate(self._agents):
            button = QToolButton()
            button.setObjectName("AgentButton")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            prefix = f"{index + 1}. " if index < 9 else ""
            button.setText(f"{prefix}{agent.emoji}  {agent.name}\n{self._subtitle(agent)}")
            if agent.available():
                button.setToolTip(agent.description or " ".join(agent.command))
            else:
                button.setToolTip(
                    f"No se encontró «{agent.executable}» en tu PATH.\n"
                    "Si lo tienes instalado, abre ⚙ → «Abrir config.json» y pon la ruta "
                    "absoluta en el campo \"command\"."
                )
            button.setMinimumHeight(64)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _=False, a=agent: self._choose(a))
            if not agent.available():
                button.setProperty("missing", True)
            self._grid.addWidget(button, index // 3, index % 3)

    def _open_manager(self) -> None:
        cfg = self._config
        if cfg is None:
            cfg = Config.load()
        dialog = AgentManagerDialog(cfg, self)
        if dialog.exec() == AgentManagerDialog.DialogCode.Accepted:
            self._config = cfg
            self._agents = list(cfg.agents)
            self._reload_grid()

    @staticmethod
    def _subtitle(agent: Agent) -> str:
        from .shell_env import resolve_executable

        path = resolve_executable(agent.executable)
        if path:
            return f"{path} · instalado"
        return f"{' '.join(agent.command)} · no encontrado"

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Carpeta de trabajo", self.cwd_edit.text())
        if chosen:
            self.cwd_edit.setText(chosen)

    def _choose(self, agent: Agent) -> None:
        self._selected = agent
        self.accept()

    def _choose_ssh(self) -> None:
        self._ssh = True
        self.accept()

    def _accept_custom(self) -> None:
        text = self.custom_edit.text().strip()
        if text:
            agent = Agent(
                id="custom",
                name=text.split()[0],
                command=text.split(),
                emoji="✎",
                color="#f0b429",
                description="Comando personalizado",
            )
            self._choose(agent)
            return
        if self._selected is None:
            # sin selección: usa el primer agente instalado
            self._selected = next((a for a in self._agents if a.available()), self._agents[0])
        self.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if Qt.Key.Key_1 <= event.key() <= Qt.Key.Key_9:
            index = event.key() - Qt.Key.Key_1
            if 0 <= index < len(self._agents):
                self._choose(self._agents[index])
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ salida
    def chosen_agent(self) -> Agent:
        return self._selected or self._agents[0]

    def chosen_cwd(self) -> str:
        return os.path.expanduser(self.cwd_edit.text().strip() or "~")

    def wants_new_tab(self) -> bool:
        return self.new_tab_check.isChecked()

    def wants_ssh(self) -> bool:
        return self._ssh


# ---------------------------------------------------------------------- move pane
class MovePaneDialog(QDialog):
    """Move a panel from the current tab to another tab (or to a new one)."""

    def __init__(
        self,
        panes: list,
        tabs: list[tuple[int, str]],
        parent=None,
        active=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · move panel")
        self.setMinimumWidth(560)
        self._panes = list(panes)
        self._tabs = list(tabs)
        self._selected: PaneWidget | None = active if active in self._panes else None
        if self._selected is None and self._panes:
            self._selected = self._panes[0]
        self._target: int = self._tabs[0][0] if self._tabs else -1

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(14)

        header = QLabel("¿Which panel to move, and where?")
        header.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(header)
        hint = QLabel(
            "Choose a panel and a tab (the ● is the active one). "
            "The process stays alive during the move. Esc to cancel."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addWidget(self._section("Panel to move"))
        self._pane_grid = QGridLayout()
        self._pane_grid.setSpacing(10)
        root.addLayout(self._pane_grid)
        self._reload_pane_grid()

        root.addWidget(self._section("Move to"))
        self._tab_grid = QGridLayout()
        self._tab_grid.setSpacing(10)
        root.addLayout(self._tab_grid)
        self._reload_tab_grid()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight: 600;")
        return label

    def _reload_pane_grid(self) -> None:
        while self._pane_grid.count():
            item = self._pane_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, pane in enumerate(self._panes):
            button = QToolButton()
            button.setObjectName("AgentButton")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            prefix = f"{index + 1}. " if index < 9 else ""
            mark = "  ·  active" if pane is self._selected else ""
            folder = os.path.basename((pane.shell_cwd() or pane.cwd).rstrip(os.sep))
            button.setText(f"{prefix}{pane.agent.emoji}  {pane.agent.name}\n{folder}{mark}")
            button.setToolTip(
                f"{pane.agent.name} · {pane.shell_cwd() or pane.cwd}\n"
                "Haz clic to choose the panel to move."
            )
            button.setMinimumHeight(56)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _=False, p=pane: self._choose_pane(p))
            self._pane_grid.addWidget(button, index // 3, index % 3)

    def _reload_tab_grid(self) -> None:
        while self._tab_grid.count():
            item = self._tab_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, (tab_index, label) in enumerate(self._tabs):
            button = QToolButton()
            button.setObjectName("AgentButton")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            letter = chr(ord("A") + index) if index < 8 else ""
            prefix = f"{letter}. " if letter else ""
            button.setText(f"{prefix}{label}")
            button.setToolTip(f"Tab «{label}»\nHaz clic to choose the destination.")
            button.setMinimumHeight(56)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _=False, i=tab_index: self._choose_target(i))
            self._tab_grid.addWidget(button, index // 3, index % 3)
        new_tab = QToolButton()
        new_tab.setObjectName("AgentButton")
        new_tab.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        new_tab.setText("＋  New tab")
        new_tab.setToolTip("Move the panel to a new tab (a new session).")
        new_tab.setMinimumHeight(56)
        new_tab.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        new_tab.clicked.connect(lambda: self._choose_target(-1))
        count = len(self._tabs)
        self._tab_grid.addWidget(new_tab, count // 3, count % 3)

    def _choose_pane(self, pane: PaneWidget) -> None:
        self._selected = pane
        self._refresh_marks()

    def _choose_target(self, index: int) -> None:
        self._target = int(index)

    def _refresh_marks(self) -> None:
        """Repaint the ● so the chosen panel is visible in its button."""
        self._reload_pane_grid()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            index = key - Qt.Key.Key_1
            if 0 <= index < len(self._panes):
                self._choose_pane(self._panes[index])
                return
        if Qt.Key.Key_A <= key <= Qt.Key.Key_H:
            index = key - Qt.Key.Key_A
            if index < len(self._tabs):
                self._choose_target(self._tabs[index][0])
                return
            if index == len(self._tabs):
                self._choose_target(-1)  # next letter after the tabs: new tab
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ salida
    def chosen_pane(self) -> PaneWidget | None:
        return self._selected

    def chosen_target(self) -> int:
        """Index of the destination tab, or -1 for a new tab."""
        return self._target


# --------------------------------------------------------------------------- SSH
class SshDialog(QDialog):
    """Configura (y opcionalmente guarda) una conexión SSH a un equipo remoto."""

    def __init__(
        self,
        hosts: list[SshHost],
        parent=None,
        preset: str = "",
        agents: list[Agent] | None = None,
        default_agent: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · conexión SSH")
        self.setMinimumWidth(560)
        self._hosts = list(hosts)
        self._agents = list(agents or [])
        self._default_agent = (default_agent or "").strip()
        self._removed: list[SshHost] = []
        self._result: SshHost | None = None
        self._provision = False

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(12)
        title = QLabel("Conectar por SSH a un equipo remoto")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(title)
        hint = QLabel(
            "Elige el agente que quieres abrir en el equipo remoto. "
            "«Provisionar clave SSH» copia tu clave pública (ssh-copy-id) para "
            "entrar sin contraseña y, al terminar, lanza ese agente."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        self.saved: QComboBox | None = None
        if self._hosts:
            self.saved = QComboBox()
            self.saved.currentIndexChanged.connect(self._load_saved)
            form.addRow("Equipos guardados", self.saved)
            self._reload_saved()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("p. ej. «Servidor de producción» (opcional)")

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("usuario (opcional)")

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("host o IP, p. ej. 192.168.1.20")

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)

        self.identity_edit = QLineEdit()
        self.identity_edit.setPlaceholderText("~/.ssh/id_ed25519 (opcional)")
        identity_browse = QPushButton("…")
        identity_browse.setFixedWidth(32)
        identity_browse.setToolTip("Elegir la clave privada")
        identity_browse.clicked.connect(self._browse_identity)
        identity_row = QHBoxLayout()
        identity_row.addWidget(self.identity_edit, 1)
        identity_row.addWidget(identity_browse)
        identity_box = QWidget()
        identity_box.setLayout(identity_row)

        self.options_edit = QLineEdit()
        self.options_edit.setPlaceholderText("p. ej. -L 8080:localhost:80   (opcional)")

        self.keepalive_check = QCheckBox("Mantener viva la conexión (ServerAliveInterval)")
        self.keepalive_check.setChecked(True)
        self.keepalive_check.setToolTip("Envía un latido cada 30 s para detectar caídas de red.")

        self.agent_combo = QComboBox()
        self.agent_combo.setToolTip(
            "Tras conectar (o al terminar de copiar la clave) se lanza este agente "
            "en la máquina remota. «Solo shell» deja una sesión de login."
        )
        self._reload_agent_combo(self._default_agent)

        form.addRow("Nombre", self.name_edit)
        form.addRow("Usuario", self.user_edit)
        form.addRow("Host", self.host_edit)
        form.addRow("Puerto", self.port_spin)
        form.addRow("Clave privada", identity_box)
        form.addRow("Agente remoto", self.agent_combo)
        form.addRow("Opciones de ssh", self.options_edit)
        form.addRow("", self.keepalive_check)
        root.addLayout(form)

        self.save_check = QCheckBox("Guardar este equipo para reutilizarlo")
        self.save_check.setChecked(not self._hosts)
        root.addWidget(self.save_check)

        if preset:
            self._apply_preset(preset)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Conectar")
        buttons.accepted.connect(self._connect)
        buttons.rejected.connect(self.reject)

        self.status = QLabel("")
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        row = QHBoxLayout()
        self.delete_button = QPushButton("Eliminar guardado")
        self.delete_button.setToolTip("Quita el equipo seleccionado de la lista")
        self.delete_button.clicked.connect(self._delete_saved)
        self.delete_button.setEnabled(bool(self._hosts))
        row.addWidget(self.delete_button)
        self.provision_button = QPushButton("🔑 Provisionar clave SSH")
        self.provision_button.setToolTip(
            "Crea la clave si no existe, la copia al equipo (ssh-copy-id) y, "
            "cuando acepte la contraseña, abre el agente seleccionado."
        )
        self.provision_button.clicked.connect(self._provision_key)
        row.addWidget(self.provision_button)
        row.addStretch(1)
        row.addWidget(buttons)
        root.addLayout(row)

        self.host_edit.returnPressed.connect(self._connect)
        self.user_edit.returnPressed.connect(self._connect)
        self.port_spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.host_edit.setFocus(Qt.FocusReason.OtherFocusReason)

    # ------------------------------------------------------------------ equipos guardados
    def _reload_saved(self) -> None:
        if self.saved is None:
            return
        self.saved.blockSignals(True)
        self.saved.clear()
        self.saved.addItem("— Nuevo equipo —", -1)
        for index, host in enumerate(self._hosts):
            self.saved.addItem(f"{host.label}  ({host.target}:{int(host.port)})", index)
        self.saved.setCurrentIndex(0)
        self.saved.blockSignals(False)
        delete_button = getattr(self, "delete_button", None)
        if delete_button is not None:
            delete_button.setEnabled(bool(self._hosts))

    def _load_saved(self, index: int) -> None:
        if self.saved is None:
            return
        data = self.saved.itemData(index)
        if data is None or int(data) < 0 or int(data) >= len(self._hosts):
            return
        self._fill(self._hosts[int(data)])

    def _fill(self, host: SshHost) -> None:
        self.name_edit.setText(host.name)
        self.user_edit.setText(host.user)
        self.host_edit.setText(host.host)
        self.port_spin.setValue(int(host.port))
        self.identity_edit.setText(host.identity)
        self.options_edit.setText(" ".join(host.options))
        self.keepalive_check.setChecked(host.keepalive)
        self._select_remote_agent(host.remote_agent or self._default_agent)

    def _apply_preset(self, preset: str) -> None:
        host = SshHost.parse(preset)
        if host is not None:
            self._fill(host)

    def _delete_saved(self) -> None:
        if self.saved is None:
            return
        data = self.saved.currentData()
        if data is None or int(data) < 0 or int(data) >= len(self._hosts):
            return
        host = self._hosts.pop(int(data))
        self._removed.append(host)
        # Se conserva lo que haya en el formulario para poder reconectar igualmente.
        self._reload_saved()

    # ------------------------------------------------------------------ formulario
    def _browse_identity(self) -> None:
        start = os.path.expanduser(self.identity_edit.text().strip() or "~/.ssh")
        chosen, _ = QFileDialog.getOpenFileName(self, "Clave privada", start)
        if chosen:
            self.identity_edit.setText(chosen)

    def _reload_agent_combo(self, selected_id: str = "") -> None:
        self.agent_combo.blockSignals(True)
        self.agent_combo.clear()
        self.agent_combo.addItem("— Solo shell (login remoto) —", "")
        for agent in self._agents:
            self.agent_combo.addItem(f"{agent.emoji} {agent.name}", agent.id)
        self.agent_combo.blockSignals(False)
        self._select_remote_agent(selected_id)

    def _select_remote_agent(self, agent_id: str) -> None:
        key = (agent_id or "").strip()
        index = self.agent_combo.findData(key)
        self.agent_combo.setCurrentIndex(max(0, index))

    def _build_host(self) -> SshHost | None:
        host = self.host_edit.text().strip()
        if not host:
            return None
        options = shlex.split(self.options_edit.text().strip()) if self.options_edit.text().strip() else []
        return SshHost(
            host=host,
            user=self.user_edit.text().strip(),
            port=int(self.port_spin.value()),
            identity=self.identity_edit.text().strip(),
            options=options,
            name=self.name_edit.text().strip(),
            keepalive=self.keepalive_check.isChecked(),
            remote_agent=str(self.agent_combo.currentData() or ""),
        )

    def _connect(self) -> None:
        host = self._build_host()
        if host is None:
            self.host_edit.setFocus(Qt.FocusReason.OtherFocusReason)
            self.status.setText("Indica el host al que conectar.")
            return
        self._provision = False
        self._result = host
        self.accept()

    def _provision_key(self) -> None:
        host = self._build_host()
        if host is None:
            self.host_edit.setFocus(Qt.FocusReason.OtherFocusReason)
            self.status.setText("Indica el host al que copiar la clave.")
            return
        try:
            path, message = ensure_ssh_identity(host.identity)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Clave SSH",
                f"No se pudo crear o localizar la clave privada:\n{exc}",
            )
            return
        self.identity_edit.setText(path)
        host.identity = path
        self._provision = True
        self._result = host
        if message:
            self.status.setText(message)
        self.accept()

    # ------------------------------------------------------------------ salida
    def result_host(self) -> SshHost | None:
        return self._result

    def wants_save(self) -> bool:
        return self.save_check.isChecked() and self._result is not None

    def wants_provision(self) -> bool:
        return self._provision and self._result is not None

    def chosen_remote_agent(self) -> Agent | None:
        agent_id = str(self.agent_combo.currentData() or "")
        if not agent_id:
            return None
        for agent in self._agents:
            if agent.id == agent_id:
                return agent
        return None

    def removed_hosts(self) -> list[SshHost]:
        return list(self._removed)


# --------------------------------------------------------------------------- ajustes
class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        agents: list[Agent],
        parent=None,
        config: Config | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · ajustes")
        self.setMinimumWidth(520)
        self._settings = settings
        self._agents = list(agents)
        self._config = config

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(14)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        self.font_combo = QFontComboBox()
        self.font_combo.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        self.font_combo.setCurrentFont(QFont(settings.font_family))

        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 40)
        self.size_spin.setValue(int(settings.font_size))

        self.theme_combo = QComboBox()
        for key, label in THEME_LABELS.items():
            self.theme_combo.addItem(label, key)
        index = self.theme_combo.findData(settings.theme)
        self.theme_combo.setCurrentIndex(max(0, index))

        self.scroll_spin = QSpinBox()
        self.scroll_spin.setRange(200, 200000)
        self.scroll_spin.setSingleStep(500)
        self.scroll_spin.setValue(int(settings.scrollback))

        self.layout_combo = QComboBox()
        for key in LAYOUTS:
            self.layout_combo.addItem(LAYOUT_LABELS.get(key, key), key)
        self.layout_combo.setCurrentIndex(max(0, self.layout_combo.findData(settings.default_layout)))

        self.agent_combo = QComboBox()
        self._reload_agent_combo(settings.default_agent)

        agent_row = QHBoxLayout()
        agent_row.addWidget(self.agent_combo, 1)
        self.manage_agents_btn = QPushButton("Asistente…")
        self.manage_agents_btn.setToolTip(
            "Abrir el asistente de agentes para escanear y seleccionar agentes."
        )
        self.manage_agents_btn.clicked.connect(self._open_agent_manager)
        agent_row.addWidget(self.manage_agents_btn)
        agent_box = QWidget()
        agent_box.setLayout(agent_row)

        self.start_dir_edit = QLineEdit(settings.start_dir)
        browse = QPushButton("…")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.start_dir_edit, 1)
        dir_row.addWidget(browse)
        dir_box = QWidget()
        dir_box.setLayout(dir_row)

        form.addRow("Fuente", self.font_combo)
        form.addRow("Tamaño", self.size_spin)
        form.addRow("Tema", self.theme_combo)
        form.addRow("Líneas de historial", self.scroll_spin)
        form.addRow("Diseño al abrir", self.layout_combo)
        form.addRow("Agente por defecto", agent_box)
        form.addRow("Carpeta inicial", dir_box)

        self.host_combo = QComboBox()
        for key in HOST_KEY_MODES:
            self.host_combo.addItem(HOST_KEY_LABELS[key], key)
        self.host_combo.setCurrentIndex(max(0, self.host_combo.findData(settings.host_key)))
        self.host_combo.setToolTip(
            "La Host Key libera el teclado del agente y alterna el MODO AGENTE.\n"
            "Escape nunca es Host Key: los agentes (vim, OpenCode, TUIs) la usan y "
            "siempre va al terminal seleccionado.\n"
            "Ctrl izquierdo y Alt derecha no están en la lista porque sus pulsaciones "
            "aisladas interrumpirían Ctrl+C, AltGr y demás atajos del agente."
        )
        form.addRow("Tecla Host", self.host_combo)

        box = QGroupBox("Comportamiento")
        box_layout = QVBoxLayout(box)
        self.restore_check = QCheckBox("Recordar la sesión (pestañas y paneles) al reiniciar")
        self.restore_check.setChecked(settings.restore_session)
        self.confirm_check = QCheckBox("Pedir confirmación al cerrar con agentes activos")
        self.confirm_check.setChecked(settings.confirm_exit)
        self.blink_check = QCheckBox("Cursor parpadeante")
        self.blink_check.setChecked(settings.cursor_blink)
        self.copy_check = QCheckBox("Copiar automáticamente al seleccionar")
        self.copy_check.setChecked(settings.copy_on_select)
        self.hidden_check = QCheckBox("Mostrar archivos ocultos en el explorador")
        self.hidden_check.setChecked(settings.show_hidden_files)
        self.hidden_check.setToolTip(
            "Archivos y carpetas que empiezan por «.». También se cambia con .* o Ctrl+H en el explorador."
        )
        self.toolbar_check = QCheckBox("Mostrar la barra de herramientas")
        self.toolbar_check.setChecked(settings.show_toolbar)
        self.toolbar_check.setToolTip(
            "En pantallas pequeñas puedes ocultarla desde Ver → Barra de herramientas."
        )
        for widget in (
            self.restore_check,
            self.confirm_check,
            self.blink_check,
            self.copy_check,
            self.hidden_check,
            self.toolbar_check,
        ):
            box_layout.addWidget(widget)

        tabs = QTabWidget()
        general = QWidget()
        general_layout = QVBoxLayout(general)
        general_layout.setContentsMargins(4, 10, 4, 4)
        general_layout.setSpacing(12)
        general_layout.addLayout(form)
        general_layout.addWidget(box)
        general_layout.addStretch(1)
        tabs.addTab(general, "General")
        tabs.addTab(self._build_shortcuts_tab(settings), "Atajos")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---------------------------------------------------------------- atajos
    def _build_shortcuts_tab(self, settings: Settings) -> QWidget:
        """Editor de atajos del chasis: la tabla vive en config.SHORTCUT_DEFAULTS."""
        merged = merged_shortcuts(settings)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(10)

        hint = QLabel(
            "Pulsa la combinación en cada campo para reasignarla. Los atajos del chasis "
            "están siempre activos; el esquema por defecto usa Ctrl+Shift+letra, "
            "Alt+dígito y F para no coincidir con los atajos de los agentes."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Esquema"))
        self.shortcut_preset = QComboBox()
        self.shortcut_preset.addItem("Moderno (sin colisiones con agentes)", "moderno")
        self.shortcut_preset.addItem("Clásico (RNCli antiguo)", "clasico")
        self.shortcut_preset.setToolTip(
            "El esquema Clásico usa Ctrl+T/Ctrl+W/Ctrl+Q y Alt+flechas, que coinciden "
            "con atajos de los agentes: con él, dentro de una TUI hay que usar la "
            "Host Key (Ctrl derecho) para los atajos del chasis."
        )
        self.shortcut_preset.currentIndexChanged.connect(self._apply_shortcut_preset)
        preset_row.addWidget(self.shortcut_preset, 1)
        restore = QPushButton("Restaurar por defecto")
        restore.clicked.connect(lambda: self._fill_shortcuts(SHORTCUT_DEFAULTS))
        preset_row.addWidget(restore)
        layout.addLayout(preset_row)

        self.shortcut_edits: dict[str, QKeySequenceEdit] = {}
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        row = 0
        for section, action_ids in SHORTCUT_SECTIONS:
            grid.addWidget(QLabel(f"<b>{section}</b>"), row, 0, 1, 2)
            row += 1
            for action_id in action_ids:
                grid.addWidget(QLabel(SHORTCUT_LABELS.get(action_id, action_id)), row, 0)
                edit = QKeySequenceEdit(QKeySequence(merged.get(action_id, "")))
                edit.setMaximumSequenceLength(1)
                self.shortcut_edits[action_id] = edit
                grid.addWidget(edit, row, 1)
                row += 1
        grid.setRowStretch(row, 1)
        grid.setColumnStretch(1, 1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        return page

    def _apply_shortcut_preset(self) -> None:
        preset = str(self.shortcut_preset.currentData() or "moderno")
        table = dict(SHORTCUT_DEFAULTS)
        if preset == "clasico":
            table.update(SHORTCUT_CLASSIC)
        self._fill_shortcuts(table)

    def _fill_shortcuts(self, table: dict[str, str]) -> None:
        for action_id, edit in self.shortcut_edits.items():
            edit.setKeySequence(QKeySequence(table.get(action_id, "")))

    def _result_shortcuts(self) -> dict:
        shortcuts = dict(SHORTCUT_DEFAULTS)
        for action_id, edit in self.shortcut_edits.items():
            sequence = edit.keySequence().toString()
            if sequence:
                shortcuts[action_id] = sequence
        return shortcuts

    def _reload_agent_combo(self, selected_id: str | None = None) -> None:
        current_data = (
            selected_id
            if selected_id is not None
            else (self.agent_combo.currentData() if self.agent_combo.count() else "")
        )
        self.agent_combo.clear()
        self.agent_combo.addItem("Automático (primer agente instalado)", "")
        for agent in self._agents:
            self.agent_combo.addItem(f"{agent.emoji} {agent.name}", agent.id)
        idx = self.agent_combo.findData(current_data)
        self.agent_combo.setCurrentIndex(max(0, idx))

    def _open_agent_manager(self) -> None:
        cfg = self._config
        if cfg is None:
            cfg = Config.load()
        dialog = AgentManagerDialog(cfg, self)
        if dialog.exec() == AgentManagerDialog.DialogCode.Accepted:
            self._config = cfg
            self._agents = list(cfg.agents)
            self._reload_agent_combo()

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Carpeta inicial", self.start_dir_edit.text())
        if chosen:
            self.start_dir_edit.setText(chosen)

    def result_settings(self, base: Settings) -> Settings:
        return Settings(
            font_family=self.font_combo.currentFont().family(),
            font_size=int(self.size_spin.value()),
            theme=str(self.theme_combo.currentData()),
            scrollback=int(self.scroll_spin.value()),
            default_layout=str(self.layout_combo.currentData()),
            default_agent=str(self.agent_combo.currentData() or ""),
            restore_session=self.restore_check.isChecked(),
            confirm_exit=self.confirm_check.isChecked(),
            cursor_blink=self.blink_check.isChecked(),
            copy_on_select=self.copy_check.isChecked(),
            bell_flash=base.bell_flash,
            start_dir=self.start_dir_edit.text().strip() or os.path.expanduser("~"),
            host_key=str(self.host_combo.currentData() or "right_ctrl"),
            show_hidden_files=self.hidden_check.isChecked(),
            show_toolbar=self.toolbar_check.isChecked(),
            shortcuts=self._result_shortcuts(),
        )


# --------------------------------------------------------------------------- ayuda
class ShortcutsDialog(QDialog):
    """Ayuda F1: la tabla de atajos del chasis se genera desde la configuración."""

    STATIC_ROWS: ClassVar[list[tuple[str, str | None]]] = [
        ("Paneles", None),
        ("Arrastrar cabecera del panel", "Reordenar en la pestaña o soltar en otra pestaña (el proceso sigue vivo)"),
        ("Terminal", None),
        ("Ctrl+Shift+C / Ctrl+Shift+V / Ctrl+Shift+A", "Copiar / pegar / seleccionar todo (apagados en MODO AGENTE)"),
        ("Tab / Shift+Tab", "Siempre al terminal seleccionado (cursor-agent, Pi…)"),
        ("Host Key (por defecto Ctrl derecho)", "Alterna el MODO AGENTE (atajos del chasis "
         "apagados, todas las teclas al agente); en MODO RNCli, sale de él. Se cambia en "
         "Ajustes → Tecla Host"),
        ("Escape", "Siempre al terminal seleccionado: los agentes y TUIs la usan (vim, OpenCode…)"),
        ("Shift+PageUp / Shift+PageDown", "Desplazarse por el historial (apagado en MODO AGENTE)"),
        ("Rueda del ratón", "Desplaza la TUI si pide el ratón (OpenCode); si no, el historial"),
        ("Shift + rueda", "Historial de la terminal aunque la TUI use el ratón"),
        ("Ctrl+H", "En el explorador: mostrar u ocultar archivos ocultos"),
        ("··· en la barra", "Unir pestañas, reiniciar, sudo y ayuda"),
    ]

    def __init__(self, parent=None, shortcuts: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · atajos y ayuda")
        self.resize(640, 660)
        table = dict(SHORTCUT_DEFAULTS)
        if isinstance(shortcuts, dict):
            for action_id, sequence in shortcuts.items():
                if action_id in table and isinstance(sequence, str) and sequence:
                    table[action_id] = sequence
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)
        browser = QTextBrowser()
        rows = []
        for section, action_ids in SHORTCUT_SECTIONS:
            rows.append(f"<tr><td colspan='2' style='padding-top:10px'><b>{section}</b></td></tr>")
            for action_id in action_ids:
                rows.append(
                    f"<tr><td style='padding-right:14px'><code>{table.get(action_id, '')}</code>"
                    f"</td><td>{SHORTCUT_LABELS.get(action_id, action_id)}</td></tr>"
                )
        for key, description in self.STATIC_ROWS:
            if description is None:
                rows.append(f"<tr><td colspan='2' style='padding-top:10px'><b>{key}</b></td></tr>")
            else:
                rows.append(
                    f"<tr><td style='padding-right:14px'><code>{key}</code></td><td>{description}</td></tr>"
                )
        browser.setHtml(
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>Multiplexor de terminales para agentes de IA: varios agentes a la vez, "
            "en pestañas y diseños, cada uno en su propia terminal real.</p>"
            "<p>Los atajos del chasis son configurables en Ajustes → Atajos.</p>"
            f"<table cellspacing='0'>{''.join(rows)}</table>"
            "<p style='margin-top:12px'><b>Consejo:</b> activa la difusión "
            f"({table.get('broadcast', 'Ctrl+Shift+B')}) para escribir "
            "la misma orden en todos los paneles del diseño a la vez.</p>"
        )
        browser.setOpenExternalLinks(True)
        root.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        root.addWidget(buttons)


# --------------------------------------------------------------------------- sudo
class SudoStrategy(NamedTuple):
    title: str
    description: str
    snippet: str
    kind: str = "sudoers"  # sudoers | shell | note
    dropin: str = ""


SUDO_STRATEGIES: list[SudoStrategy] = [
    SudoStrategy(
        "1. Timeout largo del cache (solo alarga el cache)",
        "Tras escribir la contraseña UNA vez en esa misma terminal, sudo no la vuelve a pedir "
        "durante 90 minutos. No hace falta cerrar sesión. Los agentes en otros paneles SÍ "
        "seguirán pidiendo contraseña: para ellos usa la estrategia 2 (NOPASSWD).",
        "Defaults timestamp_timeout=90\n",
        "sudoers",
        "rncli-timeout",
    ),
    SudoStrategy(
        "2. NOPASSWD para comandos concretos (recomendada para agentes)",
        "Los agentes pueden ejecutar solo esos comandos sin contraseña (sudo -n). "
        "No hace falta cerrar sesión: sudoers se aplica en el siguiente sudo.",
        "# RNCli / agentes — comandos sin contraseña\n"
        "{user} ALL=(root) NOPASSWD: /usr/bin/apt update\n"
        "{user} ALL=(root) NOPASSWD: /usr/bin/apt update *\n"
        "{user} ALL=(root) NOPASSWD: /usr/bin/apt upgrade *\n"
        "{user} ALL=(root) NOPASSWD: /usr/bin/apt install *\n"
        "{user} ALL=(root) NOPASSWD: /usr/bin/apt-get update\n"
        "{user} ALL=(root) NOPASSWD: /usr/bin/apt-get update *\n"
        "{user} ALL=(root) NOPASSWD: /usr/bin/apt-get upgrade *\n"
        "{user} ALL=(root) NOPASSWD: /usr/bin/apt-get install *\n"
        "{user} ALL=(root) NOPASSWD: /usr/bin/systemctl restart *\n"
        "{user} ALL=(root) NOPASSWD: /usr/bin/systemctl status *\n"
        "{user} ALL=(root) NOPASSWD: /usr/bin/docker *\n",
        "sudoers",
        "rncli-nopasswd-cmds",
    ),
    SudoStrategy(
        "3. NOPASSWD para tus scripts",
        "Automatizaciones propias (en una carpeta que controles tú).",
        "{user} ALL=(root) NOPASSWD: /home/{user}/scripts/*\n",
        "sudoers",
        "rncli-nopasswd-scripts",
    ),
    SudoStrategy(
        "4. Extensión con whitelist en código (máximo control)",
        "El agente usa una herramienta propia que valida los comandos y deja log de auditoría.",
        "# Ver la extensión completa en sudo-config-strategies.md (sección 4):\n"
        "# ~/.pi/agent/extensions/sudo-helper.ts  -> herramienta sudo_run + sudo_check\n",
        "note",
        "",
    ),
    SudoStrategy(
        "5. sudoedit para archivos de sistema",
        "Editar configuración como root sin ejecutar código arbitrario.",
        "{user} ALL=(root) NOPASSWD: /usr/bin/sudoedit /etc/nginx/*\n"
        "{user} ALL=(root) NOPASSWD: /usr/bin/sudoedit /etc/hosts\n",
        "sudoers",
        "rncli-sudoedit",
    ),
    SudoStrategy(
        "6. runas_spec restringido",
        "Ejecutar como otro usuario (no root) con el mínimo privilegio.",
        "{user} ALL=(www-data) NOPASSWD: ALL\n"
        "{user} ALL=(postgres) NOPASSWD: /usr/bin/psql\n",
        "sudoers",
        "rncli-runas",
    ),
    SudoStrategy(
        "7. Contraseña en disco (RIESGO ALTO)",
        "Funciona con cualquier comando, pero deja la contraseña en disco. Solo para pruebas.",
        "umask 077\n"
        "read -s -p 'Contraseña sudo: ' p; echo\n"
        "printf '%s\\n' \"$p\" > \"$HOME/.sudo_pass\"\n"
        "chmod 600 \"$HOME/.sudo_pass\"\n"
        "unset p\n"
        "echo 'Uso: cat ~/.sudo_pass | sudo -S <comando>'\n",
        "shell",
        "",
    ),
    SudoStrategy(
        "8. Contraseña en variable de entorno (RIESGO ALTO)",
        "Rápida de configurar, pero visible con 'env' o /proc/self/environ.",
        "read -s -p 'Contraseña sudo: ' SUDO_ASKPASS_PASSWORD; echo\n"
        "export SUDO_ASKPASS_PASSWORD\n"
        "echo 'Uso: printf %s \"$SUDO_ASKPASS_PASSWORD\" | sudo -S <comando>'\n",
        "shell",
        "",
    ),
]


def install_sudoers_bash(dropin: str, body: str) -> str:
    """Un solo comando bash: autentica en la TTY y luego escribe /etc/sudoers.d/.

    Empieza por ``sudo -v`` para que la contraseña se pida *antes* del pipe a
    ``tee``. Si no, sudo ve el fichero por stdin y responde «a password is required».
    """
    path = f"/etc/sudoers.d/{dropin}"
    lines = body.rstrip("\n").split("\n")
    printf_args = " ".join(shlex.quote(line) for line in lines)
    dest = shlex.quote(path)
    return (
        f"sudo -v && "
        f"{{ test -f {dest} && sudo cp {dest} {dest}.bak; "
        f"printf '%s\\n' {printf_args} | sudo tee {dest} >/dev/null; }} && "
        f"sudo chmod 440 {dest} && "
        f"sudo visudo -cf {dest} && "
        f"echo && echo 'RNCli: sudoers OK → {path}' && "
        f"sudo -l"
    )


class SudoDialog(QDialog):
    """Genera el comando bash completo para configurar sudo (cópialo o envíalo a un panel)."""

    sendRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · sudo para agentes")
        self.setMinimumWidth(720)
        self._user = os.environ.get("USER") or os.environ.get("LOGNAME") or "usuario"

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(12)
        intro = QLabel(
            "Elige una estrategia. RNCli monta <b>el comando bash entero</b> "
            "(<code>sudo -v</code> pide la contraseña en la terminal; luego escribe "
            "<code>/etc/sudoers.d/</code>). <b>No hace falta cerrar sesión ni reiniciar.</b> "
            "Para que los agentes no se queden esperando una contraseña usa la "
            "<b>estrategia 2 (NOPASSWD)</b>. La 1 solo alarga el cache en esa misma terminal."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(intro)

        self.combo = QComboBox()
        for strategy in SUDO_STRATEGIES:
            self.combo.addItem(strategy.title)
        self.combo.currentIndexChanged.connect(self._refresh)
        root.addWidget(self.combo)

        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setObjectName("Hint")
        root.addWidget(self.description)

        command_label = QLabel("Comando bash (editable: revísalo y copia o envía)")
        command_label.setObjectName("FileBrowserTitle")
        root.addWidget(command_label)

        self.snippet = QPlainTextEdit()
        self.snippet.setFont(QFont("monospace", 10))
        self.snippet.setMinimumHeight(220)
        self.snippet.setPlaceholderText("Aquí aparece el comando completo…")
        root.addWidget(self.snippet, 1)

        row = QHBoxLayout()
        copy_cmd = QPushButton("Copiar comando bash")
        copy_cmd.setObjectName("PrimaryButton")
        copy_cmd.setToolTip("Copia el comando entero al portapapeles para pegarlo en Bash")
        copy_cmd.clicked.connect(self._copy_command)
        send_btn = QPushButton("Enviar a un Bash")
        send_btn.setToolTip(
            "Abre (o reutiliza) un panel Bash en RNCli y pega el comando.\n"
            "Escribe tu contraseña en esa terminal cuando sudo la pida."
        )
        send_btn.clicked.connect(self._send_to_bash)
        test_button = QPushButton("Comprobar sudo")
        test_button.setToolTip("Ejecuta sudo -n true para ver si ya no pide contraseña")
        test_button.clicked.connect(self._test_sudo)
        row.addWidget(copy_cmd)
        row.addWidget(send_btn)
        row.addWidget(test_button)
        row.addStretch(1)
        if MD_GUIDE.exists():
            open_guide = QPushButton("Guía completa")
            open_guide.clicked.connect(lambda: QProcess.startDetached("xdg-open", [str(MD_GUIDE)]))
            row.addWidget(open_guide)
        root.addLayout(row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        root.addWidget(buttons)

        self._process: QProcess | None = None
        self._refresh()

    # ------------------------------------------------------------------ utilidades
    def _current(self) -> SudoStrategy:
        return SUDO_STRATEGIES[self.combo.currentIndex()]

    def _snippet_text(self) -> str:
        return self._current().snippet.format(user=self._user)

    def _command_text(self) -> str:
        return self.snippet.toPlainText().strip()

    def _bash_command(self) -> str:
        strategy = self._current()
        body = self._snippet_text()
        header = (
            f"# {strategy.title}\n"
            f"# Usuario: {self._user}\n"
            "# Revisa el comando. Pégalo en un Bash de RNCli o pulsa «Enviar a un Bash».\n"
        )
        if strategy.kind == "sudoers" and strategy.dropin:
            header += (
                f"# Escribe /etc/sudoers.d/{strategy.dropin} (no toca /etc/sudoers).\n"
                "# sudo -v pedirá la contraseña UNA vez en esta terminal; no hace falta relogin.\n\n"
            )
            return header + install_sudoers_bash(strategy.dropin, body)
        if strategy.kind == "shell":
            header += "# RIESGO ALTO: la contraseña la pides tú en el Bash; RNCli no la guarda.\n\n"
            return header + body.rstrip() + "\n"
        guide = str(MD_GUIDE) if MD_GUIDE.exists() else "sudo-config-strategies.md"
        return (
            header
            + "# Esta estrategia no es un drop-in de sudoers.\n"
            + f"echo {shlex.quote(strategy.description)}\n"
            + f"mkdir -p \"$HOME/.pi/agent/extensions\"\n"
            + f"echo {shlex.quote('Copia sudo-helper.ts de la guía a ~/.pi/agent/extensions/')}\n"
            + f"test -f {shlex.quote(guide)} && xdg-open {shlex.quote(guide)} || true\n"
        )

    def _refresh(self) -> None:
        strategy = self._current()
        self.description.setText(strategy.description)
        self.snippet.setPlainText(self._bash_command())
        if strategy.kind == "shell":
            self.status.setText(
                "⚠ Esta opción trata la contraseña en disco o en el entorno: "
                "úsalo solo en una máquina de confianza, nunca en producción."
            )
        elif strategy.kind == "note":
            self.status.setText("Esta opción abre la guía: no cambia sudoers.")
        elif self.combo.currentIndex() == 0:
            self.status.setText(
                f"Usuario: {self._user}  ·  /etc/sudoers.d/{strategy.dropin}  ·  "
                "sigue pidiendo contraseña a los agentes; para eso usa la estrategia 2."
            )
        else:
            self.status.setText(
                f"Usuario detectado: {self._user}  ·  archivo: /etc/sudoers.d/{strategy.dropin}  ·  "
                "se aplica al siguiente sudo, sin relogin."
            )

    def _copy_command(self) -> None:
        from PySide6.QtWidgets import QApplication

        text = self._command_text()
        if not text:
            self.status.setText("No hay comando que copiar.")
            return
        QApplication.clipboard().setText(text + "\n")
        self.status.setText(
            "Comando copiado. Pégalo en un Bash (panel de RNCli o una terminal) y pulsa Enter."
        )

    def _copy_snippet(self) -> None:
        """Compatibilidad: el fragmento sudoers crudo (lo usan las pruebas)."""
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._snippet_text())
        self.status.setText("Fragmento sudoers copiado.")

    def _copy_instructions(self) -> None:
        self._copy_command()

    def _send_to_bash(self) -> None:
        text = self._command_text()
        if not text:
            self.status.setText("No hay comando que enviar.")
            return
        self.sendRequested.emit(text)
        self.status.setText(
            "Enviado a un panel Bash. Escribe tu contraseña ahí si sudo la pide. "
            "Luego puedes cerrar este diálogo."
        )
        self.accept()

    def _test_sudo(self) -> None:
        if not shutil.which("sudo"):
            self.status.setText("No se encontró el comando sudo en este sistema.")
            return
        self.status.setText("Comprobando «sudo -n true»…")
        self._process = QProcess(self)
        self._process.finished.connect(self._test_done)
        self._process.start("sudo", ["-n", "true"])

    def _test_done(self, code: int, _status) -> None:
        if code == 0:
            self.status.setText(
                "✓ sudo funciona sin contraseña (NOPASSWD o cache activo). Los agentes no se bloquearán."
            )
        else:
            self.status.setText(
                "✗ sudo -n sigue pidiendo contraseña. Eso es normal con la estrategia 1 "
                "(solo cache). Instala la 2 (NOPASSWD), pega el comando nuevo y no hace "
                "falta cerrar sesión: el siguiente sudo ya usa el drop-in."
            )
