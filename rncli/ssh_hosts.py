"""Conexiones SSH a equipos remotos.

Un panel de RNCli es una terminal real; para conectarse a otra máquina basta
con lanzar ``ssh`` dentro de ella. Aquí se modela ese destino para poder
guardarlo en ``config.json`` y reutilizarlo, y para construir el ``argv``
completo de ``ssh`` con puerto, identidad y opciones.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field

from .agents import Agent

DEFAULT_PORT = 22


def _clean(value: str) -> str:
    return (value or "").strip()


@dataclass
class SshHost:
    """Datos de una conexión SSH reutilizable."""

    host: str = ""
    user: str = ""
    port: int = DEFAULT_PORT
    identity: str = ""                 # ruta a la clave privada (-i)
    options: list[str] = field(default_factory=list)  # opciones extra
    name: str = ""                     # etiqueta visible
    keepalive: bool = True             # ServerAliveInterval para detectar caídas

    # ------------------------------------------------------------------ utilidades
    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    @property
    def label(self) -> str:
        return self.name or self.target

    @property
    def id(self) -> str:
        return f"{self.target}:{int(self.port)}"

    def command(self) -> list[str]:
        """argv de ``ssh`` listo para lanzar dentro de un pty."""
        argv = ["ssh"]
        port = int(self.port or DEFAULT_PORT)
        if port and port != DEFAULT_PORT:
            argv += ["-p", str(port)]
        if self.keepalive:
            argv += [
                "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=4",
            ]
        identity = _clean(self.identity)
        if identity:
            argv += ["-i", os.path.expanduser(identity)]
        for option in self.options:
            option = _clean(option)
            if not option:
                continue
            if option.startswith("-"):
                argv += shlex.split(option)
            else:
                argv += ["-o", option]
        # ``--`` evita que un host que empiece por "-" se confunda con una opción.
        argv += ["--", self.target]
        return argv

    def to_agent(self) -> Agent:
        return Agent(
            id=f"ssh:{self.target}",
            name=self.label,
            command=self.command(),
            emoji="⇄",
            color="#2dd4bf",
            description=f"Conexión SSH a {self.target} (puerto {int(self.port)})",
        )

    # ------------------------------------------------------------------ persistencia
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "host": self.host,
            "user": self.user,
            "port": int(self.port),
            "identity": self.identity,
            "options": list(self.options),
            "keepalive": bool(self.keepalive),
        }

    @classmethod
    def from_dict(cls, data: dict) -> SshHost:
        data = data or {}
        try:
            port = int(data.get("port") or DEFAULT_PORT)
        except (TypeError, ValueError):
            port = DEFAULT_PORT
        return cls(
            host=_clean(str(data.get("host", ""))),
            user=_clean(str(data.get("user", ""))),
            port=port if port > 0 else DEFAULT_PORT,
            identity=_clean(str(data.get("identity", ""))),
            options=[str(item) for item in (data.get("options") or []) if str(item).strip()],
            name=_clean(str(data.get("name", ""))),
            keepalive=bool(data.get("keepalive", True)),
        )

    # ------------------------------------------------------------------ atajos
    @classmethod
    def parse(cls, text: str) -> SshHost | None:
        """Interpreta ``[user@]host[:puerto]`` (para la línea de órdenes)."""
        text = _clean(text)
        if not text:
            return None
        user = ""
        if "@" in text:
            user, text = text.split("@", 1)
        host, port = text, DEFAULT_PORT
        if text.startswith("[") and "]" in text:  # IPv6: [::1] o [::1]:2222
            closing = text.find("]")
            host = text[1:closing]
            rest = text[closing + 1:]
            if rest.startswith(":") and rest[1:].isdigit():
                port = int(rest[1:])
        elif text.count(":") == 1:  # host:puerto (IPv4 o nombre)
            candidate, _, raw_port = text.rpartition(":")
            if raw_port.isdigit():
                host, port = candidate, int(raw_port)
        host = _clean(host)
        if not host:
            return None
        return cls(host=host, user=_clean(user), port=port)
