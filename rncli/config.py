"""Carga y guardado de configuración y sesión (~/.config/rncli/)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .agents import Agent, default_agents

CONFIG_DIR = Path(os.environ.get("RNCLI_CONFIG_DIR") or (Path.home() / ".config" / "rncli"))
CONFIG_PATH = CONFIG_DIR / "config.json"
SESSION_PATH = CONFIG_DIR / "session.json"
LOG_PATH = CONFIG_DIR / "rncli.log"

LAYOUTS = ["1", "2v", "2h", "4", "6", "all"]
ESCAPE_KEY_MODES = ["terminal", "host"]
ESCAPE_KEY_LABELS = {
    "terminal": "Al terminal seleccionado (agentes, vim…)",
    "host": "Host Key de RNCli (como Ctrl derecho)",
}


@dataclass
class Settings:
    font_family: str = "monospace"
    font_size: int = 11
    theme: str = "oscuro"
    scrollback: int = 5000
    default_layout: str = "1"
    default_agent: str = ""            # vacío = autodetectado
    restore_session: bool = False
    confirm_exit: bool = True
    cursor_blink: bool = True
    copy_on_select: bool = False
    bell_flash: bool = True
    start_dir: str = str(Path.home())
    escape_key: str = "terminal"       # terminal | host
    show_hidden_files: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        known = {f.name: f for f in fields(cls)}
        clean: dict = {}
        for key, value in (data or {}).items():
            if key not in known:
                continue
            default = known[key].default
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
        if clean.get("escape_key") not in ESCAPE_KEY_MODES:
            clean["escape_key"] = "terminal"
        return cls(**clean)


@dataclass
class Config:
    agents: list[Agent] = field(default_factory=default_agents)
    settings: Settings = field(default_factory=Settings)

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
        return cls(agents=agents, settings=Settings.from_dict(data.get("settings", {})))

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "agents": [agent.to_dict() for agent in self.agents],
            "settings": self.settings.to_dict(),
        }
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CONFIG_PATH)

    # ------------------------------------------------------------------ utils
    def agent(self, agent_id: str) -> Agent | None:
        from .agents import find_agent

        return find_agent(self.agents, agent_id)


def save_session(tabs: list[dict], geometry: str | None = None) -> None:
    """Guarda la disposición actual (pestañas, paneles, agentes, geometría)."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload: dict = {"tabs": tabs}
        if geometry:
            payload["geometry"] = geometry
        SESSION_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def load_session() -> dict:
    """Devuelve {'tabs': [...], 'geometry': '...'} (vacío si no hay sesión)."""
    try:
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    tabs = data.get("tabs")
    if not isinstance(tabs, list):
        tabs = []
    return {"tabs": tabs, "geometry": data.get("geometry")}
