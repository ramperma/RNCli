"""Comprueba que RNCli encuentra los agentes aunque se lance SIN el PATH del usuario.

Es el caso del menú de aplicaciones: el escritorio arranca los programas con un entorno
mínimo, así que ``~/.opencode/bin`` y ``~/.pi/agent/bin`` (que se añaden desde
``~/.bashrc``) no están en el PATH. RNCli debe preguntar su PATH a un shell interactivo
de login y resolver los ejecutables igualmente.

Uso:
    .venv/bin/python tests/desktop_env_test.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Entorno equivalente al que da un lanzador de escritorio (XFCE, GNOME...).
MINIMAL_ENV = {
    "HOME": os.environ.get("HOME", ""),
    "USER": os.environ.get("USER", ""),
    "SHELL": os.environ.get("SHELL", "/bin/bash"),
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": os.environ.get("LANG", "C.UTF-8"),
    "QT_QPA_PLATFORM": "offscreen",
}

INNER = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from rncli.config import Config
from rncli.shell_env import login_path, resolve_executable
from rncli.window import MainWindow

problems = []
print("PATH del proceso :", os.environ.get("PATH"))
print("PATH del usuario :", login_path()[:120], "...")

for name in ("opencode", "pi", "git", "bash"):
    path = resolve_executable(name)
    print(f"  {name:9s} -> {path}")
    if path is None:
        problems.append(f"no se resolvió {name}")

def wait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

app = QApplication(["rncli-test"])
config = Config.load()
config.settings.restore_session = False
config.settings.start_dir = "/tmp"
window = MainWindow(config)
window.resize(1000, 640)
window.show()
wait(500)

workspace = window.workspace()
agent = config.agent("opencode")
if agent is None:
    problems.append("no hay agente opencode en la configuración")
else:
    pane = workspace.add_pane(agent, "/tmp")
    wait(9000)
    screen = "\n".join(
        "".join(pane.terminal._screen.buffer[y][x].data or " " for x in range(pane.terminal._screen.columns))
        for y in range(pane.terminal._screen.lines)
    )
    if pane.session.returncode == 127 or "no se encontró el comando" in screen:
        problems.append("el panel de opencode falló con 127")
    elif "opencode" not in screen.lower() and "ask anything" not in screen.lower():
        problems.append(f"el panel de opencode no muestra su interfaz: {screen.strip()[:200]!r}")
    else:
        print("opencode arrancó dentro del panel correctamente")
        print("   ", " | ".join(line.strip() for line in screen.splitlines() if line.strip())[:160])

window.shutdown()
wait(200)
print("RESULTADO:", "OK" if not problems else "FALLO " + "; ".join(problems))
sys.exit(0 if not problems else 1)
"""


def main() -> int:
    script = ROOT / "tests" / "_desktop_env_inner.py"
    script.write_text(INNER, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(ROOT)],
            env=MINIMAL_ENV,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        print(proc.stdout)
        if proc.stderr.strip():
            print("--- stderr ---")
            print("\n".join(line for line in proc.stderr.splitlines() if "propagateSize" not in line))
        return proc.returncode
    finally:
        script.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
