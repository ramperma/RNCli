"""Lanzador de procesos para RNCli.

Se ejecuta como proceso hijo (ver :mod:`rncli.pty_session`) y hace tres cosas
que no se pueden hacer de forma segura desde el proceso Qt:

1. ``setsid()``      -> el hijo pasa a ser líder de sesión.
2. ``TIOCSCTTY``     -> el pty pasa a ser su terminal de control, de forma que
   Ctrl+C/Ctrl+Z y las señales de redimensionado funcionan igual que en una
   terminal normal.
3. ``execvp()``      -> el helper se convierte en el agente, así el PID que
   guarda Qt es el del propio agente (permite terminarlo limpiamente).

Uso interno:
    python _spawn.py [--cwd DIR] [--env K=V]... -- <comando> [args...]
"""

import ctypes
import fcntl
import os
import signal
import sys
import termios

#: prctl(PR_SET_PDEATHSIG): la señal se entrega si el proceso padre desaparece.
_PR_SET_PDEATHSIG = 1


def _die_with_parent() -> None:
    """El agente no debe sobrevivir si RNCli desaparece de golpe (kill -9, cierre del escritorio)."""
    parent = os.getppid()
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(_PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0)
    except (OSError, AttributeError):
        return
    if os.getppid() != parent:  # el padre murió entre el fork y el prctl
        os.kill(os.getpid(), signal.SIGKILL)


def main(argv: list[str]) -> int:
    cwd: str | None = None
    env: dict[str, str] = {}

    while argv and argv[0] != "--":
        flag = argv[0]
        if flag == "--cwd" and len(argv) >= 2:
            cwd = argv[1]
            argv = argv[2:]
        elif flag == "--env" and len(argv) >= 2:
            key, _, value = argv[1].partition("=")
            env[key] = value
            argv = argv[2:]
        else:  # argumento inesperado: no perder el comando
            break

    cmd = argv[1:] if argv and argv[0] == "--" else argv
    if not cmd:
        sys.stderr.write("\r\n[rncli] falta el comando a ejecutar\r\n")
        return 125

    # Nueva sesión + terminal de control (puede fallar si ya somos líderes
    # de sesión, en cuyo caso seguimos igualmente).
    try:
        os.setsid()
    except OSError:
        pass
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    except OSError:
        pass

    _die_with_parent()

    if cwd:
        try:
            os.chdir(cwd)
        except OSError as exc:
            sys.stderr.write(f"\r\n[rncli] no se pudo entrar en {cwd}: {exc}\r\n")

    if env:
        os.environ.update(env)

    try:
        os.execvp(cmd[0], cmd)
    except FileNotFoundError:
        path = os.environ.get("PATH", "")
        sys.stderr.write(
            f"\r\n[rncli] no se encontró el comando '{cmd[0]}'\r\n"
            f"[rncli] PATH usado: {path}\r\n"
            f"[rncli] abre ~/.config/rncli/config.json y pon la ruta absoluta "
            f"en el agente (campo \"command\"), por ejemplo:\r\n"
            f'[rncli]   "command": ["/ruta/completa/{cmd[0]}"]\r\n'
        )
        return 127
    except PermissionError:
        sys.stderr.write(f"\r\n[rncli] sin permisos para ejecutar '{cmd[0]}'\r\n")
        return 126
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
