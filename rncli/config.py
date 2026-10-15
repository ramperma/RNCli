"""Carga y guardado de configuración y sesión (~/.config/rncli/)."""

from __future__ import annotations

import json
import os
from dataclasses import MISSING, asdict, dataclass, field, fields
from pathlib import Path

from .agents import Agent, default_agents
from .ssh_hosts import SshHost

CONFIG_DIR = Path(os.environ.get("RNCLI_CONFIG_DIR") or (Path.home() / ".config" / "rncli"))
CONFIG_PATH = CONFIG_DIR / "config.json"
SESSION_PATH = CONFIG_DIR / "session.json"
LOG_PATH = CONFIG_DIR / "rncli.log"

LAYOUTS = ["1", "2v", "2h", "4", "6", "all"]

# Tecla Host Key (la que libera el teclado hacia el chasis). Escape NO es una
# opción: vim, OpenCode y casi cualquier TUI la usan, y si RNCli la captura el
# agente se queda sin ella. Las alternativas son teclas que los agentes no usan.
HOST_KEY_MODES = ["right_ctrl", "caps_lock", "menu", "none"]
HOST_KEY_LABELS = {
    "right_ctrl": "Ctrl derecho (por defecto)",
    "caps_lock": "Bloq Mayús",
    "menu": "Tecla Menú (Applications / Compose)",
    "none": "Ninguna (solo MODO RNCli con Ctrl+Shift+Space)",
}
HOST_KEY_HINTS = {
    "right_ctrl": "Ctrl derecho",
    "caps_lock": "Bloq Mayús",
    "menu": "tecla Menú",
    "none": "Ctrl+Shift+Space",
}

# ---------------------------------------------------------------- atajos chasis
# Única fuente de verdad: action_id -> secuencia. El esquema por defecto vive en
# el espacio Ctrl+Shift+letra / Alt+dígito / F, que los agentes no usan, para que
# los atajos del chasis estén siempre activos sin robarles teclas.
SHORTCUT_DEFAULTS: dict[str, str] = {
    "new_tab": "Ctrl+Shift+T",
    "new_pane": "Ctrl+Shift+D",
    "new_ssh": "Ctrl+Shift+S",
    "close_pane": "Ctrl+Shift+W",
    "close_tab": "Ctrl+Shift+X",
    "rename_tab": "F2",
    "move_pane": "Ctrl+Shift+G",
    "next_tab": "Ctrl+Tab",
    "prev_tab": "Ctrl+Shift+Tab",
    "quit": "Ctrl+Shift+Q",
    "restart": "Ctrl+Shift+R",
    "focus_next": "Ctrl+Shift+Right",
    "focus_prev": "Ctrl+Shift+Left",
    "maximize": "Ctrl+Shift+M",
    "broadcast": "Ctrl+Shift+B",
    "zoom_in": "Ctrl+=",
    "zoom_out": "Ctrl+-",
    "zoom_reset": "Ctrl+0",
    "fullscreen": "F11",
    "help": "F1",
    "toggle_files": "Ctrl+Shift+E",
    "toggle_toolbar": "Ctrl+Shift+H",
    "host_mode": "Ctrl+Shift+Space",
    "layout_1": "Alt+1",
    "layout_2v": "Alt+2",
    "layout_2h": "Alt+3",
    "layout_4": "Alt+4",
    "layout_6": "Alt+5",
    "layout_all": "Alt+0",
}

# Preset con los atajos simples del RNCli clásico. Ojo: Ctrl+T/Ctrl+W/Ctrl+Q y
# Alt+flechas coinciden con atajos de los agentes; con este preset hay que entrar
# en MODO RNCli (Ctrl+Shift+Space) para que el chasis funcione dentro de una TUI.
SHORTCUT_CLASSIC: dict[str, str] = {
    "new_tab": "Ctrl+T",
    "new_pane": "Ctrl+Shift+T",
    "close_pane": "Ctrl+W",
    "close_tab": "Ctrl+Shift+W",
    "quit": "Ctrl+Q",
    "focus_next": "Alt+Right",
    "focus_prev": "Alt+Left",
}

SHORTCUT_LABELS: dict[str, str] = {
    "new_tab": "Nueva pestaña (elige agente)",
    "new_pane": "Nuevo panel en la pestaña actual",
    "new_ssh": "Nueva conexión SSH",
    "close_pane": "Cerrar el panel activo",
    "close_tab": "Cerrar la pestaña",
    "rename_tab": "Renombrar la pestaña",
    "move_pane": "Mover un panel a otra pestaña (o a una nueva)",
    "next_tab": "Pestaña siguiente",
    "prev_tab": "Pestaña anterior",
    "quit": "Salir",
    "restart": "Reiniciar el agente activo",
    "focus_next": "Enfocar el panel siguiente",
    "focus_prev": "Enfocar el panel anterior",
    "maximize": "Maximizar el panel activo",
    "broadcast": "Difusión (escribir en todos)",
    "zoom_in": "Aumentar letra",
    "zoom_out": "Reducir letra",
    "zoom_reset": "Tamaño de letra normal",
    "fullscreen": "Pantalla completa",
    "help": "Atajos y ayuda",
    "toggle_files": "Mostrar u ocultar el explorador",
    "toggle_toolbar": "Mostrar u ocultar la barra de herramientas",
    "host_mode": "MODO RNCli: teclado para el chasis (menús y barra)",
    "layout_1": "Diseño: solo el panel activo",
    "layout_2v": "Diseño: dos paneles en paralelo",
    "layout_2h": "Diseño: dos paneles apilados",
    "layout_4": "Diseño: rejilla 2×2",
    "layout_6": "Diseño: rejilla 3×2",
    "layout_all": "Diseño: todos los paneles",
}

# Orden para la ayuda (F1) y la pestaña de atajos de Ajustes.
SHORTCUT_SECTIONS: list[tuple[str, list[str]]] = [
    ("Pestañas y paneles", ["new_tab", "new_pane", "new_ssh", "close_pane", "close_tab",
                            "rename_tab", "move_pane", "next_tab", "prev_tab"]),
    ("Diseño y paneles", ["layout_1", "layout_2v", "layout_2h", "layout_4", "layout_6",
                          "layout_all", "focus_next", "focus_prev", "maximize"]),
    ("Agente", ["restart", "broadcast"]),
    ("Vista y salida", ["zoom_in", "zoom_out", "zoom_reset", "fullscreen", "toggle_files",
                        "toggle_toolbar", "host_mode", "help", "quit"]),
]


def merged_shortcuts(settings: "Settings") -> dict[str, str]:
    """Tabla completa: defaults cubiertos por lo que el usuario haya cambiado."""
    custom = getattr(settings, "shortcuts", None)
    if not isinstance(custom, dict):
        custom = {}
    merged = dict(SHORTCUT_DEFAULTS)
    for action_id, sequence in custom.items():
        if action_id in SHORTCUT_DEFAULTS and isinstance(sequence, str) and sequence:
            merged[action_id] = sequence
    return merged


@dataclass
class Settings:
    font_family: str = "monospace"
    font_size: int = 11
    theme: str = "oscuro"
    scrollback: int = 5000
    default_layout: str = "1"
    default_agent: str = ""            # vacío = autodetectado
    restore_session: bool = True
    confirm_exit: bool = True
    cursor_blink: bool = True
    copy_on_select: bool = False
    bell_flash: bool = True
    start_dir: str = str(Path.home())
    host_key: str = "right_ctrl"       # right_ctrl | caps_lock | menu | none
    show_hidden_files: bool = False
    show_toolbar: bool = True
    shortcuts: dict = field(default_factory=lambda: dict(SHORTCUT_DEFAULTS))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        known = {f.name: f for f in fields(cls)}
        clean: dict = {}
        for key, value in (data or {}).items():
            if key not in known:
                continue
            spec = known[key]
            if spec.default_factory not in (None, MISSING):
                # campos dict (shortcuts): solo cadenas no vacías para ids conocidos
                if isinstance(value, dict):
                    clean[key] = {
                        action_id: str(sequence)
                        for action_id, sequence in value.items()
                        if action_id in SHORTCUT_DEFAULTS and isinstance(sequence, str) and sequence
                    }
                continue
            default = spec.default
            try:
                if isinstance(default, bool):
                    value = bool(value)
                elif isinstance(default, int):
                    value = int(value)
                else:
                    value = str(value)
            except (TypeError, ValueError):
                continue
            clean[key] = value
        if clean.get("default_layout") not in LAYOUTS:
            clean["default_layout"] = "1"
        if clean.get("theme") not in {"oscuro", "dracula", "claro", "modern_dark"}:
            clean["theme"] = "oscuro"
        if clean.get("host_key") not in HOST_KEY_MODES:
            clean["host_key"] = "right_ctrl"
        if "shortcuts" in clean:
            clean["shortcuts"] = {**SHORTCUT_DEFAULTS, **clean["shortcuts"]}
        return cls(**clean)


@dataclass
class Config:
    agents: list[Agent] = field(default_factory=default_agents)
    settings: Settings = field(default_factory=Settings)
    ssh_hosts: list[SshHost] = field(default_factory=list)

    # ------------------------------------------------------------------ load/-
    @classmethod
    def load(cls) -> Config:
        if not CONFIG_PATH.exists():
            config = cls()
            config.save()
            return config
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()

        agents = [Agent.from_dict(item) for item in data.get("agents", []) if isinstance(item, dict)]
        if not agents:
            agents = default_agents()
        ssh_hosts = [
            SshHost.from_dict(item) for item in data.get("ssh_hosts", []) if isinstance(item, dict)
        ]
        config = cls(
            agents=agents,
            settings=Settings.from_dict(data.get("settings", {})),
            ssh_hosts=ssh_hosts,
        )
        # Migración: «escape_key» era la opción con la que Escape actuaba como
        # Host Key. Ya no existe (los agentes la necesitan), así que se limpia del
        # config.json para que no confunda al editarlo a mano.
        legacy = data.get("settings")
        if isinstance(legacy, dict) and "escape_key" in legacy:
            config.save()
        return config

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "agents": [agent.to_dict() for agent in self.agents],
            "settings": self.settings.to_dict(),
            "ssh_hosts": [host.to_dict() for host in self.ssh_hosts],
        }
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CONFIG_PATH)

    # ------------------------------------------------------------------ utils
    def agent(self, agent_id: str) -> Agent | None:
        from .agents import find_agent

        return find_agent(self.agents, agent_id)


def save_session(
    tabs: list[dict],
    geometry: str | None = None,
    extra: dict | None = None,
) -> None:
    """Guarda la disposición actual (pestañas, paneles, agentes, geometría)."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload: dict = {"tabs": tabs}
        if geometry:
            payload["geometry"] = geometry
        if extra:
            payload.update(extra)
        SESSION_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def load_session() -> dict:
    """Devuelve la sesión guardada (vacío si no hay)."""
    try:
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    tabs = data.get("tabs")
    if not isinstance(tabs, list):
        tabs = []
    data["tabs"] = tabs
    return data
