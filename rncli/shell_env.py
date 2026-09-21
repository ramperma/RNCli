"""Entorno real del usuario y localización de ejecutables.

Cuando RNCli se lanza desde el menú de aplicaciones (o desde cualquier proceso sin
terminal), hereda el PATH básico del escritorio y **no** ve los directorios que el
usuario añade en ``~/.bashrc`` (``~/.opencode/bin``, ``~/.pi/agent/bin``...).

Aquí pedimos ese PATH a un shell interactivo de login y lo cacheamos, de forma que
``opencode``, ``pi``, ``cursor-agent``... se encuentren igual que en su terminal.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

_MARK_START = "__RNCLI_PATH__"
_MARK_END = "__RNCLI_END__"
_TIMEOUT = 8

_lock = threading.Lock()
_cached_path: str | None = None

#: Directorios donde suelen instalarse los agentes CLI, por si el shell tampoco
#: los tiene en el PATH (por ejemplo si se instalaron después de abrir la sesión).
EXTRA_DIRS = [
    ".opencode/bin",
    ".pi/agent/bin",
    ".local/bin",
    ".local/share/pi-node/current/bin",
    ".bun/bin",
    ".cargo/bin",
    "bin",
    ".local/share/pnpm",
    ".npm-global/bin",
    ".volta/bin",
    ".deno/bin",
    "go/bin",
]


def _merge(*chunks: str) -> str:
    """Une varios PATH sin repetir entradas."""
    seen: list[str] = []
    for chunk in chunks:
        for part in (chunk or "").split(os.pathsep):
            part = part.strip()
            if part and part not in seen:
                seen.append(part)
    return os.pathsep.join(seen)


def _ask_shell(shell: str, flags: tuple[str, ...]) -> str | None:
    command = f'printf "%s%s%s" "{_MARK_START}" "$PATH" "{_MARK_END}"'
    try:
        proc = subprocess.run(
            [shell, *flags, command],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = proc.stdout or ""
    if _MARK_START not in output or _MARK_END not in output:
        return None
    value = output.split(_MARK_START, 1)[1].split(_MARK_END, 1)[0].strip()
    return value or None


#: Combinaciones de flags probadas en orden (bash/zsh primero, luego fish).
SHELL_FLAGS: tuple[tuple[str, ...], ...] = (
    ("-lic",),
    ("-lc",),
    ("-ic",),
    ("-c",),
    ("-i", "-l", "-c"),
    ("-l", "-i", "-c"),
)


def login_path() -> str:
    """PATH del usuario (con ~/.bashrc, ~/.profile...) cacheado en el proceso."""
    global _cached_path
    with _lock:
        if _cached_path is not None:
            return _cached_path

        current = os.environ.get("PATH", "")
        shell = os.environ.get("SHELL") or "/bin/bash"
        if not os.path.exists(shell):
            shell = "/bin/bash"

        # Un shell interactivo de login es el único que lee .bashrc (donde suelen
        # estar los PATH de opencode/pi). Si falla, probamos alternativas.
        for flags in SHELL_FLAGS:
            value = _ask_shell(shell, flags)
            if value:
                current = _merge(value, current)
                break

        _cached_path = current or os.defpath
        return _cached_path


def search_dirs() -> list[str]:
    home = Path.home()
    dirs = [home / relative for relative in EXTRA_DIRS]
    dirs += [Path("/usr/local/bin"), Path("/snap/bin"), Path("/usr/bin"), Path("/bin")]
    return [str(directory) for directory in dirs]


def resolve_executable(name: str) -> str | None:
    """Ruta absoluta del ejecutable, o None si no se encuentra."""
    name = (name or "").strip()
    if not name:
        return None
    if os.sep in name:
        candidate = os.path.expanduser(name)
        return candidate if os.access(candidate, os.X_OK) else None

    found = shutil.which(name, path=login_path())
    if found:
        return found

    for directory in search_dirs():
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Variables que se pasan al agente (PATH del usuario incluido)."""
    env = dict(extra or {})
    env.setdefault("PATH", login_path())
    return env


def reset_cache() -> None:
    """Solo para pruebas: olvida el PATH cacheado."""
    global _cached_path
    with _lock:
        _cached_path = None
