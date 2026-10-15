"""Conexiones SSH a equipos remotos.

Un panel de RNCli es una terminal real; para conectarse a otra máquina basta
con lanzar ``ssh`` dentro de ella. Aquí se modela ese destino para poder
guardarlo en ``config.json`` y reutilizarlo, y para construir el ``argv``
completo de ``ssh`` con puerto, identidad y opciones.

También se puede **provisionar la clave** (``ssh-copy-id``) para entrar sin
contraseña y lanzar un agente concreto en la máquina remota.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field

from .agents import Agent

DEFAULT_PORT = 22
DEFAULT_IDENTITY = "~/.ssh/id_ed25519"
CANDIDATE_IDENTITIES = (
    "~/.ssh/id_ed25519",
    "~/.ssh/id_ecdsa",
    "~/.ssh/id_rsa",
)
_LOGIN_SHELLS = {"bash", "zsh", "fish", "sh"}


def _clean(value: str) -> str:
    return (value or "").strip()


def resolve_identity(identity: str = "") -> str:
    """Ruta absoluta de la clave privada: la indicada, o la primera que exista."""
    text = _clean(identity)
    if text:
        return os.path.expanduser(text)
    for candidate in CANDIDATE_IDENTITIES:
        path = os.path.expanduser(candidate)
        if os.path.isfile(path):
            return path
    return os.path.expanduser(DEFAULT_IDENTITY)


def public_key_path(identity: str = "") -> str:
    return resolve_identity(identity) + ".pub"


def ensure_ssh_identity(identity: str = "") -> tuple[str, str]:
    """Crea la clave (ed25519) si no existe. Devuelve ``(ruta_privada, aviso)``.

    El aviso es un texto para el usuario cuando se ha generado algo; vacío si
    la clave ya estaba lista. Lanza ``RuntimeError`` si ``ssh-keygen`` falla.
    """
    private = resolve_identity(identity)
    public = private + ".pub"
    ssh_dir = os.path.dirname(private) or os.path.expanduser("~/.ssh")
    os.makedirs(ssh_dir, mode=0o700, exist_ok=True)

    if os.path.isfile(private) and os.path.isfile(public):
        return private, ""

    if os.path.isfile(private) and not os.path.isfile(public):
        proc = subprocess.run(
            ["ssh-keygen", "-y", "-f", private],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "ssh-keygen -y falló").strip())
        with open(public, "w", encoding="utf-8") as handle:
            handle.write(proc.stdout if proc.stdout.endswith("\n") else proc.stdout + "\n")
        os.chmod(public, 0o644)
        return private, f"Se ha generado la clave pública {public}."

    if shutil.which("ssh-keygen") is None:
        raise RuntimeError("No se encontró «ssh-keygen». Instala openssh-client.")

    key_type = "rsa" if os.path.basename(private).endswith("rsa") else "ed25519"
    extra: list[str] = []
    if key_type == "rsa":
        extra = ["-b", "4096"]
    proc = subprocess.run(
        ["ssh-keygen", "-t", key_type, *extra, "-N", "", "-f", private, "-C", "rncli", "-q"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0 or not os.path.isfile(private):
        raise RuntimeError((proc.stderr or proc.stdout or "ssh-keygen falló").strip())
    os.chmod(private, 0o600)
    if os.path.isfile(public):
        os.chmod(public, 0o644)
    return private, f"Se ha creado una clave {key_type} en {private}."


def _is_plain_shell(command: list[str]) -> bool:
    if not command:
        return True
    name = os.path.basename(command[0])
    if name not in _LOGIN_SHELLS:
        return False
    flags = [part for part in command[1:] if part]
    return flags in ([], ["-l"], ["-il"], ["-li"], ["--login"])


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
    remote_agent: str = ""             # id del agente a lanzar en remoto (vacío = shell)

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

    def _ssh_flags(self) -> list[str]:
        """Opciones comunes de ``ssh`` / ``ssh-copy-id`` (puerto, identidad, keepalive)."""
        argv: list[str] = []
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
        return argv

    def command(self, remote_command: list[str] | None = None) -> list[str]:
        """argv de ``ssh`` listo para lanzar dentro de un pty.

        Si ``remote_command`` no está vacío, se fuerza TTY (``-t``) y se ejecuta
        ese comando en el equipo remoto (a través de ``bash -lc`` para heredar
        el PATH de login, salvo que ya sea un shell).
        """
        argv = ["ssh", *self._ssh_flags()]
        if remote_command:
            argv.append("-t")
        # ``--`` evita que un host que empiece por "-" se confunda con una opción.
        argv += ["--", self.target]
        if remote_command:
            if _is_plain_shell(remote_command):
                argv += list(remote_command)
            else:
                inner = " ".join(shlex.quote(part) for part in remote_command)
                argv += ["bash", "-lc", inner]
        return argv

    def provision_command(self) -> list[str]:
        """argv para copiar la clave pública al equipo (``ssh-copy-id`` o equivalente)."""
        public = public_key_path(self.identity)
        target = self.target
        port = int(self.port or DEFAULT_PORT)
        copy_id = shutil.which("ssh-copy-id")
        if copy_id:
            argv = [copy_id, "-i", public]
            if port and port != DEFAULT_PORT:
                argv += ["-p", str(port)]
            if self.keepalive:
                argv += [
                    "-o", "ServerAliveInterval=30",
                    "-o", "ServerAliveCountMax=4",
                ]
            for option in self.options:
                option = _clean(option)
                if not option:
                    continue
                if option.startswith("-o"):
                    argv += shlex.split(option)
                elif option.startswith("-"):
                    argv += shlex.split(option)
                else:
                    argv += ["-o", option]
            argv.append(target)
            return argv

        remote = (
            "umask 077; mkdir -p ~/.ssh; "
            "touch ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; "
            "key=$(cat); grep -qxF \"$key\" ~/.ssh/authorized_keys "
            "|| printf '%s\\n' \"$key\" >> ~/.ssh/authorized_keys"
        )
        ssh = " ".join(shlex.quote(part) for part in self.command())
        return [
            "bash",
            "-lc",
            f"cat {shlex.quote(public)} | {ssh} {shlex.quote(remote)}",
        ]

    def to_agent(self, remote: Agent | None = None) -> Agent:
        remote_command: list[str] | None = None
        if remote is not None and remote.command and remote.id != "shell":
            remote_command = list(remote.command)
        if remote is not None and remote.id and remote.id != "shell":
            return Agent(
                id=f"ssh:{self.target}:{remote.id}",
                name=f"{self.label} · {remote.name}",
                command=self.command(remote_command),
                emoji=remote.emoji or "⇄",
                color=remote.color or "#2dd4bf",
                description=(
                    f"{remote.name} en {self.target} por SSH (puerto {int(self.port)})"
                ),
            )
        return Agent(
            id=f"ssh:{self.target}",
            name=self.label,
            command=self.command(),
            emoji="⇄",
            color="#2dd4bf",
            description=f"Conexión SSH a {self.target} (puerto {int(self.port)})",
        )

    def provision_agent(self) -> Agent:
        return Agent(
            id=f"ssh-copy-id:{self.id}",
            name=f"Clave SSH · {self.label}",
            command=self.provision_command(),
            emoji="🔑",
            color="#fbbf24",
            description=f"Copia la clave pública a {self.target} (ssh-copy-id).",
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
            "remote_agent": self.remote_agent,
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
            remote_agent=_clean(str(data.get("remote_agent", ""))),
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
