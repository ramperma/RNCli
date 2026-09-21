"""Punto de entrada: python -m rncli"""

from __future__ import annotations

import argparse
import signal
import socket
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QSocketNotifier, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__
from .config import LOG_PATH, Config
from .window import MainWindow

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def _install_signal_handlers(app: QApplication, shutdown) -> None:
    """Ctrl+C / SIGTERM cierran la aplicación (y con ella los agentes)."""
    read_sock, write_sock = socket.socketpair()
    read_sock.setblocking(False)

    notifier = QSocketNotifier(read_sock.fileno(), QSocketNotifier.Type.Read, app)

    def _drain() -> None:
        try:
            read_sock.recv(4096)
        except OSError:
            pass
        # `app.quit()` no siempre dispara `closeEvent`; apagar los ptys aquí
        # evita dejar agentes vivos cuando el escritorio manda SIGTERM.
        shutdown()
        app.quit()

    notifier.activated.connect(_drain)

    def _handler(_signum, _frame) -> None:
        try:
            write_sock.send(b"x")
        except OSError:
            pass

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass


def _log_exception(exc_type, exc_value, exc_tb) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write("\n--- excepción no controlada ---\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=handle)
    except OSError:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rncli",
        description=f"{APP_NAME}: varias terminales de agentes de IA en una sola ventana.",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--agent",
        default=None,
        help="agente a lanzar en la primera pestaña (id: opencode, pi, cursor, claude, gemini, shell)",
    )
    parser.add_argument("--cwd", default=None, help="carpeta de trabajo inicial")
    parser.add_argument(
        "--no-restore",
        action="store_true",
        help="ignora la sesión guardada en este arranque",
    )
    args = parser.parse_args(argv)

    sys.excepthook = _log_exception

    # Un solo sondeo del shell del usuario: el escritorio no hereda su PATH.
    from .shell_env import login_path

    detected_path = login_path()
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"[{APP_NAME} {__version__}] PATH detectado: {detected_path}\n")
    except OSError:
        pass

    app = QApplication(["rncli"])  # argv[0] fijo: define un WM_CLASS estable ("rncli")
    app.setApplicationName("rncli")
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("rncli")
    app.setDesktopFileName("rncli")
    icon_path = ASSETS / "rncli.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    config = Config.load()
    if args.no_restore:
        config.settings.restore_session = False
    if args.cwd:
        config.settings.start_dir = str(Path(args.cwd).expanduser())

    window = MainWindow(config)
    if args.agent:
        agent = config.agent(args.agent)
        if agent is not None:
            window.new_tab(agent, args.cwd or config.settings.start_dir)
    _install_signal_handlers(app, window.shutdown)
    app.aboutToQuit.connect(window.shutdown)

    window.show()
    QTimer.singleShot(120, window._update_status)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
