"""Pruebas del motor nativo (Rust). Se omiten si no está compilado."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rncli.vt_engine import NATIVE, make_engine, spawn_native_pty

failures: list[str] = []


def check(condition: bool, description: str) -> None:
    status = "ok  " if condition else "FALLO"
    print(f"[{status}] {description}")
    if not condition:
        failures.append(description)


def main() -> int:
    check(NATIVE, "el módulo rncli_native está importable")
    if not NATIVE:
        print("motor nativo no compilado; se omite el resto")
        return 0

    engine = make_engine(80, 24, 500)
    engine.feed(b"\x1b[1;32mHOLA-NATIVO\x1b[0m\r\n")
    text = "".join(
        (cell.data or " ") for row in range(engine.lines()) for cell in engine.row(engine.history_len() + row)
    )
    check("HOLA-NATIVO" in text, "el emulador nativo pinta texto con color")
    colored = any(
        cell.fg not in ("default",)
        for row in range(engine.lines())
        for cell in engine.row(engine.history_len() + row)
    )
    check(colored, "el emulador nativo interpreta SGR")

    engine.feed(b"\x1b[>4;1m\x1b[0mSIN-RAYAS\r\n")
    underlined = sum(
        1
        for row in range(engine.lines())
        for cell in engine.row(engine.history_len() + row)
        if cell.underscore
    )
    check(underlined == 0, "CSI privado no activa subrayado")
    text = "".join(
        (cell.data or " ") for row in range(engine.lines()) for cell in engine.row(engine.history_len() + row)
    )
    check("SIN-RAYAS" in text, "el texto posterior al CSI privado se muestra")

    env = dict(os.environ)
    env.setdefault("TERM", "xterm-256color")
    pty = spawn_native_pty(["/bin/echo", "PTY-NATIVO"], "/tmp", env, 80, 24)
    check(pty is not None, "se puede crear un PTY nativo")
    output = b""
    deadline = time.time() + 2
    while time.time() < deadline:
        chunk = pty.read(4096)
        if chunk:
            output += bytes(chunk)
            if b"PTY-NATIVO" in output:
                break
        code = pty.poll()
        if code is not None and not chunk:
            break
        time.sleep(0.05)
    check(b"PTY-NATIVO" in output, f"el PTY nativo ejecuta echo ({output!r})")
    pty.close()

    if failures:
        print("\nFallos:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nMotor nativo: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
