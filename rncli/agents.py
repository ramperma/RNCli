"""Agentes CLI que RNCli puede lanzar."""

from __future__ import annotations

from dataclasses import dataclass, field

from .shell_env import resolve_executable


@dataclass
class Agent:
    """Perfil de un agente de terminal."""

    id: str
    name: str
    command: list[str]
    emoji: str = ">"
    color: str = "#58a6ff"
    description: str = ""
    cwd: str = ""            # vacío = directorio del panel actual / HOME
    env: dict[str, str] = field(default_factory=dict)   # p.ej. GEMINI_API_KEY

    # ------------------------------------------------------------------ utils
    @property
    def executable(self) -> str:
        return self.command[0] if self.command else ""

    def available(self) -> bool:
        """¿Está el ejecutable disponible (PATH del usuario incluido)?"""
        return resolve_executable(self.executable) is not None

    def resolved_command(self) -> list[str]:
        """Comando con la ruta absoluta del ejecutable, si se encuentra."""
        if not self.command:
            return []
        path = resolve_executable(self.command[0])
        if path is None:
            return list(self.command)
        return [path, *self.command[1:]]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "command": list(self.command),
            "emoji": self.emoji,
            "color": self.color,
            "description": self.description,
            "cwd": self.cwd,
            "env": dict(self.env),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Agent:
        command = data.get("command") or [data.get("executable", "")]
        if isinstance(command, str):
            command = command.split()
        return cls(
            id=str(data.get("id") or (command[0] if command else "custom")),
            name=str(data.get("name") or (command[0] if command else "Custom")),
            command=[str(part) for part in command if str(part)],
            emoji=str(data.get("emoji", ">")),
            color=str(data.get("color", "#58a6ff")),
            description=str(data.get("description", "")),
            cwd=str(data.get("cwd", "")),
            env={str(k): str(v) for k, v in (data.get("env") or {}).items()},
        )


#: Agentes predefinidos. `command` se puede editar en ~/.config/rncli/config.json
DEFAULT_AGENTS: list[Agent] = [
    Agent(
        id="opencode",
        name="OpenCode",
        command=["opencode"],
        emoji="◆",
        color="#4ade80",
        description="Agente de código OpenCode (TUI).",
    ),
    Agent(
        id="pi",
        name="Pi Agent",
        command=["pi"],
        emoji="π",
        color="#60a5fa",
        description="Pi Coding Agent.",
    ),
    Agent(
        id="cursor",
        name="Cursor CLI",
        command=["cursor-agent"],
        emoji="⌘",
        color="#c084fc",
        description="Cursor Agent CLI (cursor-agent).",
    ),
    Agent(
        id="claude",
        name="Claude Code",
        command=["claude"],
        emoji="✳",
        color="#fb923c",
        description="Claude Code CLI de Anthropic.",
    ),
    Agent(
        id="gemini",
        name="Gemini CLI",
        command=["gemini"],
        emoji="✦",
        color="#38bdf8",
        description="Gemini CLI de Google (usa GEMINI_API_KEY).",
    ),
    Agent(
        id="shell",
        name="Bash",
        command=["bash", "-l"],
        emoji="$",
        color="#9ca3af",
        description="Shell de login normal.",
    ),
]

#: Alias aceptados al buscar un agente por id.
AGENT_ALIASES = {
    "google": "gemini",
    "gemini-cli": "gemini",
    "claude-code": "claude",
    "cursor-agent": "cursor",
    "sh": "shell",
    "terminal": "shell",
}


def default_agents() -> list[Agent]:
    return [Agent.from_dict(agent.to_dict()) for agent in DEFAULT_AGENTS]


def find_agent(agents: list[Agent], agent_id: str) -> Agent | None:
    key = (agent_id or "").strip().lower()
    key = AGENT_ALIASES.get(key, key)
    for agent in agents:
        if agent.id.lower() == key:
            return agent
    return None


def pick_default_agent(agents: list[Agent]) -> Agent:
    """Primer agente instalado, priorizando opencode/pi/shell."""
    for agent in agents:
        if agent.available():
            return agent
    return agents[-1] if agents else default_agents()[-1]
