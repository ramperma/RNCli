"""Prueba de humo sin pantalla: arranca RNCli en modo offscreen y comprueba que
los paneles, los diseños y la terminal funcionan de verdad.

Uso:
    .venv/bin/python tests/smoke_test.py [--screenshot /tmp/opencode/rncli.png]
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if "RNCLI_CONFIG_DIR" not in os.environ:
    os.environ["RNCLI_CONFIG_DIR"] = tempfile.mkdtemp(prefix="rncli-config-")
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
    from PySide6.QtGui import QFont

    strategy = terminal._font.styleStrategy()
    no_lcd = getattr(QFont.StyleStrategy, "NoSubpixelAntialias")
    has_no_lcd = (
        strategy == no_lcd
        or getattr(strategy, "name", "") == "NoSubpixelAntialias"
        or no_lcd.name in str(strategy)
    )
    check(has_no_lcd, "la fuente evita el antialias LCD que deja manchas azules")

    from rncli.terminal import PAD_X, PAD_Y

    marker_line = "COPIA-FINAL-XY"
    active.send(f'printf "%s\\n" "{marker_line}"\n'.encode())
    wait(500)
    found_row = found_col = None
    for abs_row in range(terminal._history_len() + terminal._screen.lines):
        row_text = "".join(ch.data or " " for ch in terminal._row_abs(abs_row))
        idx = row_text.find(marker_line)
        if idx >= 0:
            found_row, found_col = abs_row, idx
            break
    check(found_row is not None, "la línea de prueba de copia está en pantalla")
    if found_row is not None:
        last_col = found_col + len(marker_line) - 1
        terminal._sel_anchor = (found_row, found_col)
        terminal._sel_focus = (found_row, last_col)
        terminal._sel_visible = True
        check(
            terminal.selected_text() == marker_line,
            "copiar incluye los dos últimos caracteres de la selección",
        )
        visible_row = found_row - (terminal._history_len() - terminal._scroll_offset)
        if 0 <= visible_row < terminal._screen.lines:
            click_x = PAD_X + last_col * terminal._cell_w + terminal._cell_w / 2
            click_y = PAD_Y + visible_row * terminal._cell_h + terminal._cell_h / 2
            cell = terminal._cell_at(click_x, click_y)
            check(
                cell == (found_row, last_col),
                "el clic en la última letra cae en esa misma celda",
            )
            edge = terminal._cell_at(
                PAD_X + terminal._screen.columns * terminal._cell_w + 12,
                click_y,
            )
            check(
                edge is not None and edge[1] == terminal._screen.columns - 1,
                "arrastrar al margen selecciona la última columna",
            )
        else:
            check(False, "el clic en la última letra cae en esa misma celda")
            check(False, "arrastrar al margen selecciona la última columna")
        terminal._clear_selection()
        check(terminal.selected_text() == "", "un clic no deja un cuadrado de selección")
    else:
        check(False, "copiar incluye los dos últimos caracteres de la selección")
        check(False, "el clic en la última letra cae en esa misma celda")
        check(False, "arrastrar al margen selecciona la última columna")
        check(False, "un clic no deja un cuadrado de selección")

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
    snippets_ok = True
    bash_ok = True
    for index in range(sudo.combo.count()):
        sudo.combo.setCurrentIndex(index)
        snippets_ok = snippets_ok and bool(sudo._snippet_text().strip())
        bash_ok = bash_ok and bool(sudo._bash_command().strip())
    check(sudo.combo.count() == 8 and snippets_ok, "el asistente de sudo genera los 8 fragmentos del manual")
    check(bash_ok, "el asistente de sudo genera el comando bash completo")
    sudo.combo.setCurrentIndex(0)
    cmd = sudo._bash_command()
    check(
        "sudo -v" in cmd and "sudo tee" in cmd and "chmod 440" in cmd and "visudo -cf" in cmd,
        "el comando instala un drop-in en /etc/sudoers.d y lo valida",
    )
    sudo.combo.setCurrentIndex(1)
    check(
        sudo._user in sudo._bash_command(),
        "el comando NOPASSWD incluye el usuario detectado",
    )
    sent: list[str] = []
    sudo.sendRequested.connect(sent.append)
    sudo.snippet.setPlainText("echo RNCLI-SUDO-BASH\n")
    sudo._send_to_bash()
    check(sent == ["echo RNCLI-SUDO-BASH"], "enviar a Bash emite el comando entero")
    sudo.deleteLater()
    ShortcutsDialog(window).deleteLater()

    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from rncli.terminal import is_host_key, tab_sequence

    settings_ui = SettingsDialog(config.settings, config.agents, window)
    check(settings_ui.escape_combo.count() == 2, "ajustes permite configurar la tecla Escape")
    settings_ui.escape_combo.setCurrentIndex(max(0, settings_ui.escape_combo.findData("host")))
    escaped = settings_ui.result_settings(config.settings)
    check(escaped.escape_key == "host", "ajustes guarda Escape como Host Key")
    settings_ui.hidden_check.setChecked(True)
    escaped = settings_ui.result_settings(config.settings)
    check(escaped.show_hidden_files is True, "ajustes guarda mostrar archivos ocultos")
    settings_ui.deleteLater()

    from rncli.config import Settings as SettingsCls

    check(SettingsCls.from_dict({"escape_key": "host"}).escape_key == "host", "config.json acepta escape_key=host")
    check(
        SettingsCls.from_dict({"escape_key": "espacio"}).escape_key == "terminal",
        "escape_key inválida usa el terminal",
    )
    check(
        SettingsCls.from_dict({}).show_hidden_files is False,
        "los archivos ocultos vienen desactivados por defecto",
    )
    check(
        SettingsCls.from_dict({"show_hidden_files": True}).show_hidden_files is True,
        "config.json recuerda mostrar archivos ocultos",
    )
    check(
        SettingsCls.from_dict({"theme": "modern_dark"}).theme == "modern_dark",
        "config.json acepta el tema modern_dark",
    )
    check(hasattr(window, "prompt") and window.prompt.objectName() == "PromptBar", "la barra de escritura está montada")
    check(
        hasattr(window, "layout_buttons")
        and list(window.layout_buttons) == ["1", "2v", "2h", "4", "6", "all"],
        "la barra muestra el selector de diseño",
    )
    from rncli.theme import THEME_LABELS, app_stylesheet

    check("modern_dark" in THEME_LABELS, "ajustes lista el tema Grafito")
    check("PromptContainer" in app_stylesheet("oscuro"), "el estilo incluye la barra de escritura")
    try:
        window._on_prompt("echo RNCLI-PROMPT-OK", False)
        prompt_send_ok = True
    except Exception:
        prompt_send_ok = False
    check(prompt_send_ok, "enviar desde la barra de escritura no falla")

    tab_ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier, "\t")
    check(tab_sequence(tab_ev) == b"\t", "Tab se envía al agente (cursor-agent)")
    backtab_ev = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier
    )
    check(tab_sequence(backtab_ev) == b"\x1b[Z", "Shift+Tab se envía al agente (Pi)")
    ctrl_tab_ev = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier
    )
    check(tab_sequence(ctrl_tab_ev) is None, "Ctrl+Tab no se envía al agente")

    esc_ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    host_settings = dataclasses.replace(config.settings, escape_key="host")
    term_settings = dataclasses.replace(config.settings, escape_key="terminal")
    check(is_host_key(esc_ev, host_settings), "Escape configurado es Host Key")
    check(not is_host_key(esc_ev, term_settings), "Escape por defecto va al terminal")

    target = workspace.add_pane(shell, "/tmp")
    wait(200)
    if target is not None and target.terminal is not None and target.session is not None:
        target.terminal.settings = term_settings
        target.terminal.setFocus(Qt.FocusReason.OtherFocusReason)
        wait(50)
        recorded: list[bytes] = []
        real_write = target.session.write

        def spy(data: bytes, _real=real_write) -> None:
            recorded.append(bytes(data))
            return _real(data)

        target.session.write = spy  # type: ignore[method-assign]
        tab_press = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier, "\t"
        )
        handled = target.terminal.event(tab_press)
        wait(40)
        check(
            bool(handled) and any(b"\t" in chunk for chunk in recorded),
            "Tab llega al terminal seleccionado",
        )
        check(
            target.terminal.focusNextPrevChild(True) is False,
            "Tab no cambia el foco a otro widget",
        )
        recorded.clear()
        host_hits: list[bool] = []
        target.terminal.settings = host_settings
        target.terminal.hostKeyPressed.connect(lambda: host_hits.append(True))
        QApplication.sendEvent(
            target.terminal,
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier),
        )
        wait(40)
        check(
            bool(host_hits) and not any(chunk == b"\x1b" for chunk in recorded),
            "Escape como Host Key no se envía al agente",
        )
        target.session.write = real_write  # type: ignore[method-assign]
    else:
        check(False, "Tab llega al terminal seleccionado")
        check(False, "Tab no cambia el foco a otro widget")
        check(False, "Escape como Host Key no se envía al agente")

    from PySide6.QtCore import QDir, QMimeData, QPoint, QPointF, QUrl, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent

    from rncli.terminal import quote_drop_paths, split_drop_paths

    filt = window.file_browser.model.filter()
    check(bool(filt & QDir.Filter.Files), "el explorador lista archivos además de carpetas")
    check(not bool(filt & QDir.Filter.Hidden), "los archivos ocultos no se muestran por defecto")
    check(not window.file_browser.show_hidden, "el explorador arranca sin archivos ocultos")
    check(not window.file_browser.add_button.isEnabled(), "añadir archivo exige seleccionar uno")
    window.file_browser.set_show_hidden(True)
    check(
        bool(window.file_browser.model.filter() & QDir.Filter.Hidden)
        and window.file_browser.show_hidden
        and window.file_browser.hidden_button.isChecked()
        and window.act_show_hidden.isChecked()
        and window.settings.show_hidden_files,
        "se pueden volver a ver los archivos ocultos",
    )
    window.file_browser.toggle_show_hidden()
    check(
        not bool(window.file_browser.model.filter() & QDir.Filter.Hidden)
        and not window.file_browser.show_hidden
        and not window.settings.show_hidden_files,
        "se pueden volver a ocultar los archivos ocultos",
    )

    tmpdir = tempfile.mkdtemp(prefix="rncli-drop-")
    samples = {
        "foto.png": b"\x89PNG\r\n",
        "nota.pdf": b"%PDF-1.4\n",
        "texto.txt": b"hola agente\n",
    }
    sample_paths = []
    for name, payload in samples.items():
        path = os.path.join(tmpdir, name)
        with open(path, "wb") as handle:
            handle.write(payload)
        sample_paths.append(os.path.realpath(path))

    files, dirs = split_drop_paths([*sample_paths, tmpdir])
    check(len(files) == 3 and dirs == [os.path.realpath(tmpdir)], "separa archivos de carpetas")
    quoted = quote_drop_paths(sample_paths)
    check(
        all(name in quoted for name in samples),
        "entrecomilla imagen, PDF y texto",
    )

    chosen: list[str] = []
    window.file_browser.filesRequested.connect(lambda paths: chosen.extend(paths))
    window.file_browser._selected_files = list(sample_paths)
    window.file_browser._update_labels()
    check(window.file_browser.add_button.isEnabled(), "el botón añadir se activa con archivos")
    window.file_browser._add_files()
    check(chosen == sample_paths, "añadir archivo emite los archivos elegidos")

    drop_pane = workspace.active_pane()
    if drop_pane is not None and drop_pane.terminal is not None and drop_pane.session is not None:
        recorded: list[bytes] = []
        real_write = drop_pane.session.write

        def drop_spy(data: bytes, _real=real_write) -> None:
            recorded.append(bytes(data))
            return _real(data)

        drop_pane.session.write = drop_spy  # type: ignore[method-assign]
        drop_pane.terminal.insert_paths(sample_paths)
        joined = b"".join(recorded)
        check(
            all(name.encode() in joined for name in samples),
            "pega rutas de imagen, PDF y texto en el terminal",
        )
        recorded.clear()
        dropped: list[str] = []
        drop_pane.terminal.filesDropped.connect(lambda paths: dropped.extend(paths))
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(sample_paths[0])])
        enter = QDragEnterEvent(
            QPoint(12, 12),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        drop_pane.terminal.dragEnterEvent(enter)
        check(enter.isAccepted(), "el terminal acepta soltar un archivo del explorador")
        drop_ev = QDropEvent(
            QPointF(12, 12),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        drop_pane.terminal.dropEvent(drop_ev)
        wait(40)
        check(
            bool(drop_ev.isAccepted())
            and any(os.path.basename(sample_paths[0]).encode() in chunk for chunk in recorded)
            and any(os.path.samefile(sample_paths[0], path) for path in dropped),
            "soltar un archivo lo pega en ese terminal",
        )
        drop_pane.session.write = real_write  # type: ignore[method-assign]
    else:
        check(False, "pega rutas de imagen, PDF y texto en el terminal")
        check(False, "el terminal acepta soltar un archivo del explorador")
        check(False, "soltar un archivo lo pega en ese terminal")

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
