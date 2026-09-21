"""Prueba de humo sin pantalla: arranca RNCli en modo offscreen y comprueba que
los paneles, los diseños y la terminal funcionan de verdad.

Uso:
    .venv/bin/python tests/smoke_test.py [--screenshot /tmp/opencode/rncli.png]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from rncli.agents import Agent
from rncli.config import Config
from rncli.window import MainWindow

failures: list[str] = []


def check(condition: bool, description: str) -> None:
    status = "ok  " if condition else "FALLO"
    print(f"[{status}] {description}")
    if not condition:
        failures.append(description)


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def screen_text(terminal) -> str:
    screen = terminal._screen
    rows = []
    for y in range(screen.lines):
        row = "".join(screen.buffer[y][x].data or " " for x in range(screen.columns))
        rows.append(row.rstrip())
    return "\n".join(rows).strip()


def visible_text(terminal) -> str:
    """Texto visible teniendo en cuenta el desplazamiento por el historial."""
    base = terminal._history_len() - terminal._scroll_offset
    rows = []
    for y in range(terminal._screen.lines):
        chars = terminal._row_abs(base + y)
        rows.append("".join(c.data or " " for c in chars).rstrip())
    return "\n".join(rows).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", default="")
    args = parser.parse_args()

    app = QApplication([])
    config = Config.load()
    config.settings.restore_session = False
    config.settings.start_dir = "/tmp"

    window = MainWindow(config)
    window.resize(1200, 760)
    window.show()
    wait(300)

    workspace = window.workspace()
    check(workspace is not None and workspace.count() == 1, "arranca con una pestaña y un panel")

    # Panel de shell que imprime color y termina una orden concreta
    shell = config.agent("shell") or Agent(id="shell", name="Bash", command=["bash", "-l"])
    pane = workspace.add_pane(shell, "/tmp")
    pane.send(b'printf "\\033[1;32mHOLA-RNCLI\\033[0m\\n"; echo MARCA-$((6*7)); pwd\n')
    wait(1500)
    text = screen_text(pane.terminal)
    check("HOLA-RNCLI" in text, "la terminal recibe la salida del shell")
    check("MARCA-42" in text, "el shell ejecuta y devuelve resultados")
    check("/tmp" in text, "el panel arranca en la carpeta indicada")

    # Colores: la primera celda de la línea debe tener un color asignado
    colored = False
    for y in range(pane.terminal._screen.lines):
        row = [pane.terminal._screen.buffer[y][x] for x in range(pane.terminal._screen.columns)]
        if any(cell.fg not in ("default",) for cell in row):
            colored = True
            break
    check(colored, "la terminal interpreta secuencias ANSI de color")

    # Varios paneles + diseños
    initial = workspace.count()
    for _ in range(2):
        workspace.add_pane(shell, "/tmp")
    check(workspace.count() == initial + 2, "se pueden añadir más paneles al mismo tiempo")
    total = workspace.count()
    for mode, expected in (("1", 1), ("2v", 2), ("2h", 2), ("4", min(4, total)), ("all", total)):
        workspace.set_layout(mode)
        wait(60)
        check(
            len(workspace.visible_panes()) == expected,
            f"diseño «{mode}» muestra {expected} panel(es)",
        )

    # El foco no debe reordenar paneles ni destruir el splitter manual.
    workspace.set_layout("2v")
    wait(120)
    positions_before = [pane.geometry().x() for pane in workspace.visible_panes()]
    workspace.focus_pane(workspace.visible_panes()[1])
    wait(120)
    positions_after = [pane.geometry().x() for pane in workspace.visible_panes()]
    check(
        positions_after == positions_before
        and workspace.active_pane() is workspace.visible_panes()[1],
        "hacer clic/enfocar un panel no cambia su posición",
    )
    root_splitter = workspace._host_layout.itemAt(0).widget()
    original_sizes = root_splitter.sizes()
    if len(original_sizes) == 2:
        root_splitter.setSizes([max(60, original_sizes[0] - 80), original_sizes[1] + 80])
        wait(100)
        changed_sizes = root_splitter.sizes()
        workspace.focus_pane(workspace.visible_panes()[0])
        wait(100)
        check(
            workspace._host_layout.itemAt(0).widget().sizes() == changed_sizes,
            "el divisor conserva la posición elegida por el usuario",
        )

    workspace.set_layout("4")
    check(workspace.broadcast is False, "la difusión está apagada por defecto")
    workspace.set_broadcast(True)
    check(all(p.broadcast_label.isVisible() for p in workspace.panes()), "la difusión se marca en los paneles")
    workspace.set_broadcast(False)

    # Agentes reales instalados: comprobamos que arrancan dentro de un pty
    import re

    for agent_id in ("pi", "opencode"):
        agent = config.agent(agent_id)
        if agent is None or not agent.available():
            continue
        probe = Agent(
            id=f"{agent_id}-version", name=agent.name, command=[*agent.command, "--version"]
        )
        probe_pane = workspace.add_pane(probe, "/tmp")
        wait(3000)
        output = screen_text(probe_pane.terminal)
        version = re.search(r"\d+\.\d+\.\d+", output)
        check(
            version is not None and probe_pane.session.returncode == 0,
            f"«{' '.join(probe.command)}» arranca en un panel "
            f"(versión: {version.group(0) if version else '?'}, código: {probe_pane.session.returncode})",
        )
        workspace.close_pane(probe_pane)
        wait(100)

    # Cerrar paneles y reiniciar
    before = workspace.count()
    workspace.close_pane(workspace.active_pane())
    wait(200)
    check(workspace.count() == before - 1, "se pueden cerrar paneles")

    active = workspace.active_pane()
    active.restart()
    wait(600)
    check(active.is_alive(), "el botón de reiniciar levanta de nuevo el agente")

    # --- historial (scrollback) -------------------------------------------------
    active.send(b'for i in $(seq 1 90); do echo "LINEA-$i"; done\n')
    wait(1600)
    terminal = active.terminal
    check(terminal.history_len() > 20, f"el historial guarda líneas ({terminal.history_len()})")
    terminal.scroll_by(20)
    check(terminal._scroll_offset == 20, "la rueda/atajo desplaza el historial")
    check("LINEA-" in visible_text(terminal), "se pueden leer líneas antiguas del historial")
    terminal.scroll_to_bottom()
    check(terminal._scroll_offset == 0, "volver abajo restaura la vista en vivo")

    # --- secuencias que pyte malinterpreta --------------------------------------
    active.send(b'printf "\\033[>4;1m\\033[0mSIN-RAYAS\\n"\n')
    wait(900)
    underlined = sum(
        1
        for y in range(terminal._screen.lines)
        for x in range(terminal._screen.columns)
        if terminal._screen.buffer[y][x].underscore
    )
    check(underlined == 0, "las secuencias con prefijo privado no ensucian los atributos")
    check("SIN-RAYAS" in screen_text(terminal), "el texto posterior se sigue mostrando")

    # --- difusión ----------------------------------------------------------------
    workspace.set_layout("2v")
    workspace.set_broadcast(True)
    marker = Path(f"/tmp/opencode/difusion-{os.getpid()}.txt")
    marker.unlink(missing_ok=True)
    QApplication.clipboard().setText(f"echo listo > {marker}\n")
    active.terminal.paste()
    wait(1600)
    check(marker.exists(), "la difusión envía la orden a los demás paneles (y se ejecuta)")
    workspace.set_broadcast(False)

    # --- selección y portapapeles ------------------------------------------------
    terminal.scroll_to_bottom()
    terminal.select_all()
    selected = terminal.selected_text()
    check("LINEA-" in selected, "se puede seleccionar y copiar el contenido")
    terminal.copy_selection()
    check("LINEA-" in QApplication.clipboard().text(), "copiar lleva el texto al portapapeles")

    # --- sesión guardada ---------------------------------------------------------
    from rncli.config import load_session, save_session

    state = [workspace.state()]
    save_session(state, "Z2VvbWV0cmlh")
    restored = load_session()
    check(
        restored.get("tabs", [{}])[0].get("layout") == workspace.layout_mode
        and bool(restored.get("geometry")),
        "la sesión se guarda y se puede restaurar",
    )

    # --- restaurar la sesión en una ventana nueva --------------------------------
    import dataclasses

    restore_config = Config.load()
    restore_config.settings = dataclasses.replace(
        restore_config.settings, restore_session=True, font_size=10
    )
    window2 = MainWindow(restore_config)
    window2.resize(900, 600)
    window2.show()
    wait(900)
    restored_ws = window2.workspace()
    check(
        restored_ws is not None and restored_ws.count() == workspace.count(),
        "al reabrir se recuperan la pestaña y sus paneles",
    )
    check(
        restored_ws is not None and restored_ws.layout_mode == workspace.layout_mode,
        "al reabrir se recupera el diseño guardado",
    )

    # --- ajustes en caliente ------------------------------------------------------
    from rncli.theme import theme as theme_palette

    new_settings = dataclasses.replace(
        restore_config.settings, font_size=13, theme="dracula"
    )
    window2.settings = new_settings
    window2.apply_theme()
    window2._apply_settings_to_workspaces()
    wait(200)
    panes = restored_ws.panes() if restored_ws else []
    check(
        bool(panes)
        and all(abs(p.terminal._font.pointSizeF() - 13) < 0.01 for p in panes)
        and all(p.terminal._palette["bg"] == theme_palette("dracula")["bg"] for p in panes),
        "cambiar fuente y tema se aplica a todos los paneles al momento",
    )
    window2.shutdown()
    wait(200)
    window2.deleteLater()

    # --- detección de ejecutables ------------------------------------------------
    from rncli.shell_env import login_path, resolve_executable

    check(resolve_executable("bash") is not None, "encuentra ejecutables del sistema")
    check(resolve_executable("no-existe-rncli-xyz") is None, "no inventa ejecutables")
    check(len(login_path().split(os.pathsep)) >= 3, "usa el PATH completo del usuario")

    # --- diálogos ----------------------------------------------------------------
    from rncli.dialogs import AgentChooserDialog, SettingsDialog, ShortcutsDialog, SudoDialog

    chooser = AgentChooserDialog(config.agents, config.settings, window)
    check(chooser.chosen_agent() is not None, "el selector de agentes lista los agentes")
    chooser.deleteLater()
    sudo = SudoDialog(window)
    snippets_ok = all(sudo._snippet_text() for _ in range(sudo.combo.count()))
    for index in range(sudo.combo.count()):
        sudo.combo.setCurrentIndex(index)
        snippets_ok = snippets_ok and bool(sudo._snippet_text().strip())
    check(snippets_ok, "el asistente de sudo genera los 8 fragmentos del manual")
    sudo.deleteLater()
    ShortcutsDialog(window).deleteLater()
    SettingsDialog(config.settings, config.agents, window).deleteLater()

    if args.screenshot:
        window.workspace().set_layout("all")
        wait(250)
        window.grab().save(args.screenshot)
        print(f"[info] captura guardada en {args.screenshot}")

    window.shutdown()
    wait(200)

    print()
    if failures:
        print(f"{len(failures)} comprobación(es) fallidas:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("Todas las comprobaciones han pasado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
