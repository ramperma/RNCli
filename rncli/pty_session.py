"""Sesión de pseudo-terminal: lanza un proceso y lo comunica con la interfaz."""

from __future__ import annotations

import fcntl
import os
import pty
import signal
import struct
import subprocess
import sys
import termios

from PySide6.QtCore import QObject, QSocketNotifier, QTimer, Signal

from .shell_env import login_path, resolve_executable

_SPAWN_HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_spawn.py")


def _python() -> str:
    """Intérprete con el que ejecutar el helper (siempre el del venv)."""
    return sys.executable or "python3"


class PtySession(QObject):
    """Proceso ejecutándose dentro de un pty, con E/S no bloqueante."""

    dataReceived = Signal(bytes)
    exited = Signal(int)

    def __init__(
        self,
        argv: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        cols: int = 80,
        rows: int = 24,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        # La ruta absoluta evita depender del PATH que tenga el proceso.
        resolved = resolve_executable(argv[0]) if argv else None
        self.argv = [resolved or argv[0], *argv[1:]] if argv else []
        self.requested = list(argv)
        self.cwd = cwd or os.path.expanduser("~")
        self.cols = max(2, int(cols))
        self.rows = max(2, int(rows))
        self.pid: int | None = None
        self.returncode: int | None = None
        self._proc: subprocess.Popen | None = None

        self._master: int = -1
        self._read_notifier: QSocketNotifier | None = None
        self._write_notifier: QSocketNotifier | None = None
        self._pending: bytearray = bytearray()
        self._dead = False
        self._reap_timer: QTimer | None = None
        self._kill_timer: QTimer | None = None

        self._start(env or {})

    # ------------------------------------------------------------------ arranque
    def _start(self, env: dict[str, str]) -> None:
        master, slave = pty.openpty()
        self._set_winsize(master, self.cols, self.rows)

        command = [_python(), _SPAWN_HELPER, "--cwd", self.cwd]
        env = {"PATH": login_path(), **env}  # el agente ve el PATH del usuario
        for key, value in env.items():
            command += ["--env", f"{key}={value}"]
        command += ["--", *self.argv]

        child_env = os.environ.copy()
        child_env.setdefault("TERM", "xterm-256color")
        child_env.setdefault("COLORTERM", "truecolor")
        child_env.setdefault("TERM_PROGRAM", "rncli")

        try:
            self._proc = subprocess.Popen(
                command,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=self.cwd if os.path.isdir(self.cwd) else None,
                env=child_env,
                close_fds=True,
            )
        except OSError as exc:
            os.close(master)
            os.close(slave)
            self._fail(str(exc))
            return

        os.close(slave)
        self.pid = self._proc.pid
        self._master = master
        os.set_blocking(master, False)

        self._read_notifier = QSocketNotifier(master, QSocketNotifier.Type.Read, self)
        self._read_notifier.activated.connect(self._on_readable)
        self._write_notifier = QSocketNotifier(master, QSocketNotifier.Type.Write, self)
        self._write_notifier.activated.connect(self._on_writable)
        self._write_notifier.setEnabled(False)

    def _fail(self, message: str) -> None:
        """No se pudo ni arrancar el proceso: avisa como si hubiese salido."""
        self.returncode = 127
        QTimer.singleShot(
            0,
            lambda: (
                self.dataReceived.emit(
                    f"\r\n[rncli] no se pudo iniciar {' '.join(self.argv)}: {message}\r\n".encode()
                ),
                self.exited.emit(127),
            ),
        )

    # ------------------------------------------------------------------ lectura
    def _on_readable(self) -> None:
        if self._master < 0:
            return
        while True:
            try:
                chunk = os.read(self._master, 65536)
            except BlockingIOError:
                return
            except OSError:
                chunk = b""
            if not chunk:
                self._shutdown_io()
                self._schedule_reap()
                return
            self.dataReceived.emit(chunk)

    def _shutdown_io(self) -> None:
        for attribute in ("_read_notifier", "_write_notifier"):
            notifier = getattr(self, attribute)
            if notifier is None:
                continue
            setattr(self, attribute, None)
            try:
                notifier.setEnabled(False)
                notifier.deleteLater()
            except RuntimeError:
                pass  # el objeto C++ ya había sido destruido
        if self._master >= 0:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = -1

    def _schedule_reap(self) -> None:
        """Espera (sin bloquear la interfaz) a que el proceso termine."""
        if self._reap_timer is None:
            self._reap_timer = QTimer(self)
            self._reap_timer.setInterval(120)
            self._reap_timer.timeout.connect(self._reap)
        self._reap_timer.start()

    def _reap(self) -> None:
        if self._proc is None or self._proc.poll() is None:
            return
        if self._reap_timer is not None:
            self._reap_timer.stop()
        self._dead = True
        self.returncode = self._proc.returncode
        self.exited.emit(int(self._proc.returncode if self._proc.returncode is not None else 0))

    # ------------------------------------------------------------------ escritura
    def write(self, data: bytes) -> None:
        if self._master < 0 or not data:
            return
        self._pending += data
        self._flush()

    def _flush(self) -> None:
        while self._pending and self._master >= 0:
            try:
                written = os.write(self._master, bytes(self._pending))
            except BlockingIOError:
                self._enable_write_notifier(True)
                return
            except OSError:
                self._pending.clear()
                self._shutdown_io()
                self._schedule_reap()
                return
            del self._pending[:written]
        if not self._pending:
            self._enable_write_notifier(False)

    def _enable_write_notifier(self, enabled: bool) -> None:
        notifier = self._write_notifier
        if notifier is None:
            return
        try:
            notifier.setEnabled(enabled)
        except RuntimeError:
            self._write_notifier = None

    def _on_writable(self) -> None:
        self._flush()

    # ------------------------------------------------------------------ control
    def _set_winsize(self, fd: int, cols: int, rows: int) -> None:
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def resize(self, cols: int, rows: int) -> None:
        cols, rows = max(2, int(cols)), max(2, int(rows))
        if (cols, rows) == (self.cols, self.rows):
            return
        self.cols, self.rows = cols, rows
        if self._master >= 0:
            self._set_winsize(self._master, cols, rows)  # el kernel envía SIGWINCH

    def is_alive(self) -> bool:
        return self._proc is not None and not self._dead and self._proc.poll() is None

    def terminate(self, force_after_ms: int = 900) -> None:
        """SIGTERM al grupo de procesos y, si se resiste, SIGKILL."""
        pid = self.pid
        if pid is None or self._dead:
            return
        try:
            pgid = os.getpgid(pid)
        except OSError:
            pgid = pid
        for sig in (signal.SIGTERM, signal.SIGHUP):
            try:
                os.killpg(pgid, sig)
                break
            except OSError:
                try:
                    os.kill(pid, sig)
                    break
                except OSError:
                    return
        self._pending.clear()
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(lambda: self._force_kill(pgid))
        self._kill_timer.start(force_after_ms)

    def _force_kill(self, pgid: int) -> None:
        if self._proc is None or self._proc.poll() is not None:
            return
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            try:
                os.kill(self.pid or pgid, signal.SIGKILL)
            except OSError:
                pass

    def kill_now(self) -> None:
        """Cierre inmediato (al cerrar la aplicación)."""
        pid = self.pid
        if pid is None:
            return
        try:
            pgid = os.getpgid(pid)
        except OSError:
            pgid = pid
        for _ in range(3):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    break
            try:
                if self._proc is not None:
                    self._proc.wait(timeout=0.4)
                break
            except Exception:
                continue
        self._shutdown_io()
