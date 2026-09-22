"""Diálogos: elegir agente, ajustes, atajos y utilidades de sudo."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path
from typing import ClassVar, NamedTuple

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, __version__
from .agents import Agent
from .config import ESCAPE_KEY_LABELS, ESCAPE_KEY_MODES, LAYOUTS, Settings
from .layouts import LAYOUT_LABELS
from .theme import THEME_LABELS

MD_GUIDE = Path(__file__).resolve().parents[1] / "sudo-config-strategies.md"


# --------------------------------------------------------------------------- agentes
class AgentChooserDialog(QDialog):
    """Elige qué agente lanzar, en qué carpeta y si en pestaña nueva."""

    def __init__(self, agents: list[Agent], settings: Settings, parent=None, cwd_hint: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · nuevo panel")
        self.setMinimumWidth(600)
        self._agents = agents
        self._selected: Agent | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(12)
        title = QLabel("¿Qué agente quieres lanzar?")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(title)
        hint = QLabel("Pulsa el número del agente o haz clic. Esc para cancelar.")
        hint.setObjectName("Hint")
        root.addWidget(hint)

        grid = QGridLayout()
        grid.setSpacing(10)
        grid.setVerticalSpacing(10)
        for index, agent in enumerate(agents):
            button = QToolButton()
            button.setObjectName("AgentButton")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setText(f"{index + 1}. {agent.emoji}  {agent.name}\n{self._subtitle(agent)}")
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
            grid.addWidget(button, index // 3, index % 3)
        root.addLayout(grid)

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

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._accept_custom)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.custom_edit.returnPressed.connect(self._accept_custom)

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


# --------------------------------------------------------------------------- ajustes
class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, agents: list[Agent], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · ajustes")
        self.setMinimumWidth(520)
        self._agents = agents

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
        self.agent_combo.addItem("Automático (primer agente instalado)", "")
        for agent in agents:
            self.agent_combo.addItem(f"{agent.emoji} {agent.name}", agent.id)
        self.agent_combo.setCurrentIndex(max(0, self.agent_combo.findData(settings.default_agent)))

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
        form.addRow("Agente por defecto", self.agent_combo)
        form.addRow("Carpeta inicial", dir_box)

        self.escape_combo = QComboBox()
        for key in ESCAPE_KEY_MODES:
            self.escape_combo.addItem(ESCAPE_KEY_LABELS[key], key)
        self.escape_combo.setCurrentIndex(max(0, self.escape_combo.findData(settings.escape_key)))
        self.escape_combo.setToolTip(
            "Tab y el resto de teclas van siempre al terminal seleccionado.\n"
            "Escape puede ir al agente o usarse como Host Key (igual que Ctrl derecho)."
        )
        form.addRow("Tecla Escape", self.escape_combo)
        root.addLayout(form)

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
        for widget in (
            self.restore_check,
            self.confirm_check,
            self.blink_check,
            self.copy_check,
            self.hidden_check,
        ):
            box_layout.addWidget(widget)
        root.addWidget(box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

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
            escape_key=str(self.escape_combo.currentData() or "terminal"),
            show_hidden_files=self.hidden_check.isChecked(),
        )


# --------------------------------------------------------------------------- ayuda
class ShortcutsDialog(QDialog):
    SHORTCUTS: ClassVar[list[tuple[str, str | None]]] = [
        ("Pestañas y paneles", None),
        ("Ctrl+T", "Nueva pestaña (elige agente)"),
        ("Ctrl+Shift+T", "Nuevo panel en la pestaña actual"),
        ("Ctrl+W", "Cerrar el panel activo"),
        ("Ctrl+Shift+W", "Cerrar la pestaña"),
        ("F2", "Renombrar la pestaña"),
        ("Ctrl+Tab / Ctrl+Shift+Tab", "Pestaña siguiente / anterior"),
        ("Diseño", None),
        ("Alt+1", "Solo el panel activo (1 visible)"),
        ("Alt+2", "Dos paneles en paralelo"),
        ("Alt+3", "Dos paneles apilados"),
        ("Alt+4", "Rejilla 2×2"),
        ("Alt+5", "Rejilla 3×2"),
        ("Alt+0", "Todos los paneles visibles"),
        ("Alt+→ / Alt+←", "Enfocar el panel siguiente / anterior"),
        ("Ctrl+Shift+M", "Maximizar el panel activo (solo 1 visible)"),
        ("Terminal", None),
        ("Ctrl+Shift+C / Ctrl+Shift+V", "Copiar / pegar"),
        ("Tab / Shift+Tab", "Siempre al terminal seleccionado (cursor-agent, Pi…)"),
        ("Ctrl derecho", "Host Key tipo VirtualBox: libera el foco y activa los atajos de RNCli"),
        ("Escape", "Configurable en Ajustes: al terminal o Host Key de RNCli"),
        ("Shift+PageUp / Shift+PageDown", "Desplazarse por el historial"),
        ("Rueda del ratón", "Historial de la terminal"),
        ("Ctrl+Shift+B", "Activar/desactivar difusión (escribir en todos)"),
        ("Ctrl+Shift+R", "Reiniciar el agente activo"),
        ("Explorador", "Archivos y carpetas: arrastra un archivo a un terminal o usa «Pegar archivo»"),
        ("··· en la barra", "Unir pestañas, reiniciar, sudo y ayuda"),
        ("Ctrl+H", "En el explorador: mostrar u ocultar archivos ocultos"),
        ("Ctrl++ / Ctrl+- / Ctrl+0", "Tamaño de letra"),
        ("F11", "Pantalla completa"),
        ("Ctrl+Q", "Salir"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} · atajos y ayuda")
        self.resize(640, 660)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)
        browser = QTextBrowser()
        rows = []
        for key, description in self.SHORTCUTS:
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
            f"<table cellspacing='0'>{''.join(rows)}</table>"
            "<p style='margin-top:12px'><b>Consejo:</b> activa la difusión (Ctrl+Shift+B) para escribir "
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
