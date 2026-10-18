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

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest
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

    window = MainWindow(config, restore=False)
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
    wait(300)
    positions_before = [pane.geometry().x() for pane in workspace.visible_panes()]
    workspace.focus_pane(workspace.visible_panes()[1])
    wait(300)
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

    # Regresión: al maximizar, ocultar la terminal con el foco hace que Qt se
    # lo pase a otra terminal; el panel maximizado debe seguir siendo el clicado.
    workspace.set_layout("all")
    wait(300)
    from PySide6.QtCore import Qt as _Qt  # main() reimporta Qt más abajo
    clicked, other = workspace.visible_panes()[:2]
    QTest.mouseClick(
        clicked.terminal,
        _Qt.MouseButton.LeftButton,
        _Qt.KeyboardModifier.NoModifier,
        clicked.terminal.rect().center(),
    )
    wait(150)
    workspace.set_layout("1")
    wait(150)
    check(
        workspace.visible_panes() == [clicked] and workspace.active_pane() is clicked,
        "maximizar muestra el panel clicado, no el que Qt enfocó al ocultar el otro",
    )
    workspace.set_layout("all")
    wait(150)

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
        for _ in range(25):
            wait(500)
            if probe_pane.session.returncode is not None:
                break
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
    check(active.scrollbar is not None and active.scrollbar.isEnabled(), "el panel tiene una barra de scroll activa")
    terminal.scroll_by(20)
    check(terminal._scroll_offset == 20, "la rueda/atajo desplaza el historial")
    check(active.scrollbar.value() == terminal.history_len() - 20, "la barra de scroll se sincroniza con el historial")
    active.scrollbar.setValue(terminal.history_len() - 15)
    check(terminal._scroll_offset == 15, "arrastrar la barra de scroll desplaza el historial")
    check("LINEA-" in visible_text(terminal), "se pueden leer líneas antiguas del historial")
    terminal.scroll_to_bottom()
    check(terminal._scroll_offset == 0, "volver abajo restaura la vista en vivo")

    # --- rueda reenviada a la app (OpenCode/OpenTUI piden el ratón) ---------------
    terminal.feed_text("\x1b[?1000h\x1b[?1006h")
    wait(200)
    check(terminal._engine.mouse_tracking(), "el motor detecta que la app pidió eventos de ratón")
    check(terminal._engine.mouse_sgr(), "el motor detecta la codificación SGR del ratón (1006)")
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    def make_wheel(delta_y: int, mods=Qt.KeyboardModifier.NoModifier) -> QWheelEvent:
        return QWheelEvent(
            QPointF(50, 50), QPointF(50, 50), QPoint(0, 0), QPoint(0, delta_y),
            Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False,
        )

    sent: list[bytes] = []
    original_write = terminal.session.write
    terminal.session.write = lambda data: (sent.append(bytes(data)), original_write(data))[1]
    QApplication.sendEvent(terminal, make_wheel(120))
    check(any(b"[<64;" in chunk for chunk in sent), "la rueda se reenvía a la app como secuencia de ratón")
    check(terminal._scroll_offset == 0, "la rueda reenviada no desplaza el historial local")
    QApplication.sendEvent(terminal, make_wheel(120, Qt.KeyboardModifier.ShiftModifier))
    check(terminal._scroll_offset > 0, "Shift+rueda sigue desplazando el historial de RNCli")
    terminal.session.write = original_write
    terminal.feed_text("\x1b[?1000l\x1b[?1006l")
    terminal.scroll_to_bottom()

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
    # Con bracketed paste (lo activa el motor nativo) el salto de línea del
    # portapapeles no ejecuta: hace falta Enter, que también se difunde.
    active.terminal.send_special(b"\r")
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

    # --- selección con el ratón sobre celdas con fondo propio (OpenCode) ------
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    bg_marker = "FONDO-PROPIO-OK"
    terminal.feed_text(f"\x1b[48;2;30;30;30m{bg_marker}\x1b[0m\r\n")
    wait(300)
    bg_row = bg_col = None
    for abs_row in range(terminal._history_len() + terminal._screen.lines):
        row_text = "".join(ch.data or " " for ch in terminal._row_abs(abs_row))
        idx = row_text.find(bg_marker)
        if idx >= 0:
            bg_row, bg_col = abs_row, idx
            break
    check(bg_row is not None, "la línea de prueba con fondo propio está en pantalla")
    visible_row = (bg_row or 0) - (terminal._history_len() - terminal._scroll_offset)
    if bg_row is not None and 0 <= visible_row < terminal._screen.lines:
        copy_was = terminal.settings.copy_on_select
        terminal.settings.copy_on_select = True
        QApplication.clipboard().setText("")

        def mouse(kind, x, y, button, buttons):
            pos = QPoint(int(x), int(y))
            ev = QMouseEvent(
                kind, pos.toPointF(), terminal.mapToGlobal(pos), button, buttons,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(terminal, ev)

        y_mid = PAD_Y + visible_row * terminal._cell_h + terminal._cell_h / 2
        x_from = PAD_X + bg_col * terminal._cell_w + terminal._cell_w / 2
        x_to = x_from + (len(bg_marker) - 1) * terminal._cell_w
        mouse(QEvent.Type.MouseButtonPress, x_from, y_mid, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        wait(50)
        mouse(QEvent.Type.MouseMove, x_to, y_mid, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        wait(50)
        mouse(QEvent.Type.MouseButtonRelease, x_to, y_mid, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        wait(100)
        check(
            bg_marker in QApplication.clipboard().text(),
            "arrastrar con el ratón selecciona y copia al soltar (aunque la app pinte fondos propios)",
        )
        pixel = terminal.grab().toImage().pixelColor(
            int(PAD_X + (bg_col + 2) * terminal._cell_w), int(y_mid)
        )
        sel = terminal._selection_color
        check(
            abs(pixel.red() - sel.red()) <= 12
            and abs(pixel.green() - sel.green()) <= 12
            and abs(pixel.blue() - sel.blue()) <= 12,
            "el resaltado de selección se ve sobre las celdas con fondo propio",
        )
        terminal.settings.copy_on_select = copy_was
        terminal._clear_selection()
    else:
        check(False, "arrastrar con el ratón selecciona y copia al soltar (aunque la app pinte fondos propios)")
        check(False, "el resaltado de selección se ve sobre las celdas con fondo propio")

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

    # --- conexiones SSH ----------------------------------------------------------
    from rncli.ssh_hosts import SshHost

    parsed = SshHost.parse("deploy@prod.example.com:2222")
    check(
        parsed is not None
        and parsed.user == "deploy"
        and parsed.host == "prod.example.com"
        and parsed.port == 2222,
        "se interpreta el destino SSH [usuario@]host[:puerto]",
    )
    ipv6 = SshHost.parse("[::1]:2200")
    check(
        ipv6 is not None and ipv6.host == "::1" and ipv6.port == 2200,
        "se interpretan destinos SSH IPv6 con puerto",
    )
    ssh_cmd = SshHost(
        host="10.0.0.5",
        user="root",
        port=2222,
        identity="~/.ssh/id_ed25519",
        options=["-L 8080:localhost:80"],
    ).command()
    check(
        ssh_cmd[0] == "ssh"
        and "2222" in ssh_cmd
        and "-i" in ssh_cmd
        and "-L" in ssh_cmd
        and ssh_cmd[-1] == "root@10.0.0.5",
        "el comando ssh incluye puerto, identidad y opciones",
    )
    remote_cmd = SshHost(
        host="10.0.0.5",
        user="root",
        identity="~/.ssh/id_ed25519",
    ).command(["opencode", "--model", "sonnet"])
    check(
        remote_cmd[0] == "ssh"
        and "-t" in remote_cmd
        and remote_cmd[-3:] == ["bash", "-lc", "opencode --model sonnet"],
        "el comando ssh remoto lanza el agente con TTY y un shell de login",
    )
    remote_agent = Agent(
        id="opencode",
        name="OpenCode",
        command=["opencode"],
        emoji="◆",
        color="#4ade80",
    )
    ssh_agent = SshHost(host="box", user="dev", remote_agent="opencode").to_agent(remote_agent)
    check(
        ssh_agent.id == "ssh:dev@box:opencode"
        and "OpenCode" in ssh_agent.name
        and "-t" in ssh_agent.command
        and ssh_agent.command[-1].startswith("opencode"),
        "to_agent con agente remoto construye el panel SSH+agente",
    )
    check(
        SshHost.from_dict(SshHost(host="h", user="u").to_dict()).id == "u@h:22",
        "los equipos SSH se serializan y se recuperan",
    )
    restored = SshHost.from_dict(
        SshHost(host="h", user="u", remote_agent="pi", identity="~/.ssh/id_ed25519").to_dict()
    )
    check(
        restored.remote_agent == "pi" and restored.identity.endswith("id_ed25519"),
        "los equipos SSH conservan el agente remoto y la clave",
    )
    from rncli.ssh_hosts import ensure_ssh_identity, public_key_path

    provision = SshHost(
        host="10.0.0.5",
        user="root",
        port=2222,
        identity="~/.ssh/id_ed25519",
    ).provision_command()
    check(
        provision[0].endswith("ssh-copy-id") or provision[0] == "bash",
        "provisionar clave usa ssh-copy-id (o un fallback bash)",
    )
    if provision[0].endswith("ssh-copy-id") or os.path.basename(provision[0]) == "ssh-copy-id":
        check(
            "-i" in provision and "2222" in provision and provision[-1] == "root@10.0.0.5",
            "ssh-copy-id recibe la clave pública, el puerto y el destino",
        )
    with tempfile.TemporaryDirectory(prefix="rncli-ssh-key-") as key_dir:
        key_path = os.path.join(key_dir, "id_ed25519")
        try:
            private, notice = ensure_ssh_identity(key_path)
            check(
                os.path.isfile(private)
                and os.path.isfile(public_key_path(private))
                and "clave" in notice.lower(),
                "si no hay clave SSH se crea una ed25519",
            )
            again, silent = ensure_ssh_identity(key_path)
            check(again == private and silent == "", "si la clave ya existe no se regenera")
        except RuntimeError as exc:
            check("ssh-keygen" in str(exc).lower(), "sin ssh-keygen se avisa con claridad")

    ssh_config = Config.load()
    ssh_config.ssh_hosts = [SshHost(host="equipo-u", user="u", name="Equipo U")]
    ssh_config.save()
    check(
        any(host.host == "equipo-u" for host in Config.load().ssh_hosts),
        "config.json guarda los equipos SSH",
    )

    # --- explorador remoto: transporte sin nuevas dependencias -----------------
    from rncli.remote_fs import RemoteTarget, parse_listing

    fake_listing = "/srv/data\nnotes/\nold report.txt\nback\\\\slash.txt\n"
    parsed_root, parsed_entries = parse_listing(fake_listing)
    check(
        parsed_root == "/srv/data"
        and [entry.name for entry in parsed_entries]
        == ["notes", "back\\slash.txt", "old report.txt"]
        and parsed_entries[0].is_dir
        and not parsed_entries[1].is_dir
        and all(entry.path.startswith("/srv/data/") for entry in parsed_entries),
        "se parsea la salida de ls remoto (carpetas, espacios y escapes octales)",
    )
    remote_host = SshHost(host="127.0.0.2", user="root")
    list_argv = remote_host.listing_command("bin")
    check(
        list_argv[:1] == ["ssh"]
        and "BatchMode=yes" in list_argv
        and "ls -1 -p -b" in list_argv[-1]
        and list_argv[-2] == "root@127.0.0.2",
        "el listado remoto reutiliza ssh sin colgarse pidiendo contraseña",
    )
    remote_target = RemoteTarget.from_host(remote_host)
    check(
        remote_target.target == "root@127.0.0.2" and remote_target.id == "root@127.0.0.2:22",
        "RemoteTarget describe el equipo sin duplicar la conexión",
    )
    anchor = remote_host.command_with_cwd("/srv/data")
    check(
        anchor[:1] == ["ssh"]
        and "-t" in anchor
        and "cd -- /srv/data && exec" in anchor[-1],
        "command_with_cwd re-ancla el panel SSH dentro de una carpeta remota",
    )
    # La tilde NO puede ir entrecomillada: ``cd -- '~'`` falla en el equipo
    # remoto con «No such file or directory» (era el error del explorador).
    import shlex as _shlex
    import subprocess as _subprocess

    from rncli.ssh_hosts import remote_path_expr

    check(
        remote_path_expr("~") == "~"
        and remote_path_expr("~/docs") == "~/docs"
        and remote_path_expr("~/mis fotos") == "~/'mis fotos'"
        and remote_path_expr("/srv/x") == "/srv/x",
        "la ruta remota deja la tilde sin comillas y cita solo el resto",
    )
    home_dir = tempfile.mkdtemp(prefix="rncli-home-")
    os.makedirs(os.path.join(home_dir, "bin"))
    os.makedirs(os.path.join(home_dir, "mis fotos"))
    # ssh concatena los argv remotos y los entrega a la shell de login: se
    # reproduce tal cual el último argv (no se extrae el script con -1, que
    # ocultaba que faltaba el ``-c`` y sh abría el script como fichero).
    home_remote = remote_host.listing_command("~")[-1]
    check(
        _shlex.split(home_remote)[:2] == ["sh", "-c"],
        "el listado remoto se ejecuta con «sh -c» (sin -c, sh busca un fichero)",
    )
    home_run = _subprocess.run(
        ["sh", "-c", home_remote],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": home_dir},
    )
    check(
        home_run.returncode == 0
        and home_run.stdout.splitlines()[0] == home_dir
        and "bin/" in home_run.stdout
        and "mis\\ fotos/" in home_run.stdout,
        "el listado de «~» se expande y llega al HOME del equipo remoto",
    )
    spaced_remote = remote_host.listing_command("~/mis fotos")[-1]
    spaced_run = _subprocess.run(
        ["sh", "-c", spaced_remote],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": home_dir},
    )
    check(
        spaced_run.returncode == 0
        and spaced_run.stdout.splitlines()[0] == os.path.join(home_dir, "mis fotos"),
        "el listado de una carpeta remota con espacios también funciona",
    )

    from rncli.dialogs import SshDialog

    ssh_dialog = SshDialog(
        ssh_config.ssh_hosts,
        window,
        agents=config.agents,
        default_agent="shell",
    )
    ssh_dialog._apply_preset("alice@server:2222")
    idx = ssh_dialog.agent_combo.findData("shell")
    if idx < 0:
        idx = 1 if ssh_dialog.agent_combo.count() > 1 else 0
    ssh_dialog.agent_combo.setCurrentIndex(idx)
    ssh_dialog._connect()
    mini_host = ssh_dialog.result_host()
    check(
        mini_host is not None and mini_host.user == "alice" and mini_host.port == 2222,
        "el diálogo SSH construye el destino a partir del formulario",
    )
    check(
        ssh_dialog.agent_combo.count() >= 1
        and ssh_dialog.provision_button is not None
        and "Provisionar" in ssh_dialog.provision_button.text(),
        "el diálogo SSH permite elegir agente remoto y provisionar la clave",
    )
    check(not ssh_dialog.wants_provision(), "conectar no marca la provisión de clave")
    ssh_dialog.save_check.setChecked(True)
    check(ssh_dialog.wants_save(), "el diálogo SSH permite guardar el equipo")
    chosen = ssh_dialog.chosen_remote_agent()
    check(
        mini_host is not None
        and (
            (chosen is None and mini_host.remote_agent == "")
            or (chosen is not None and mini_host.remote_agent == chosen.id)
        ),
        "el diálogo SSH guarda el agente remoto seleccionado",
    )
    ssh_dialog.deleteLater()

    # --- diálogos ----------------------------------------------------------------
    from rncli.agents import KNOWN_AGENTS, catalog_agents
    from rncli.dialogs import (
        AddAgentDialog,
        AgentChooserDialog,
        AgentManagerDialog,
        SettingsDialog,
        ShortcutsDialog,
        SudoDialog,
    )

    # Catálogo extendido de agentes
    catalog = catalog_agents(config.agents)
    check(len(catalog) >= len(KNOWN_AGENTS), "el catálogo contiene los agentes conocidos")
    check(any(a.id == "aider" for a in catalog), "el catálogo incluye aider")
    check(any(a.id == "antigravity" for a in catalog), "el catálogo incluye antigravity")
    check(any(a.id == "goose" for a in catalog), "el catálogo incluye goose")

    # Diálogo de añadir agente
    add_agent_dialog = AddAgentDialog(window)
    add_agent_dialog.name_edit.setText("Mi Agente Custom")
    add_agent_dialog.cmd_edit.setText("echo custom-agent")
    add_agent_dialog.desc_edit.setText("Agente de prueba")
    add_agent_dialog._accept()
    custom_created = add_agent_dialog.created_agent()
    check(
        custom_created is not None
        and custom_created.id == "mi-agente-custom"
        and custom_created.command == ["echo", "custom-agent"],
        "el diálogo de añadir agente crea un nuevo agente",
    )
    add_agent_dialog.deleteLater()

    # Asistente y gestor de agentes
    manager = AgentManagerDialog(config, window)
    check(len(manager._all_agents) == len(catalog), "el gestor carga todos los agentes del catálogo")
    check(all(a.id in manager._checkboxes for a in manager._all_agents), "cada agente tiene su casilla de selección")

    # Selección masiva e instalados
    manager._select_none()
    check(all(not cb.isChecked() for cb in manager._checkboxes.values()), "el botón «Ninguno» desmarca todos los agentes")

    manager._select_all()
    check(all(cb.isChecked() for cb in manager._checkboxes.values()), "el botón «Todos» marca todos los agentes")

    manager._select_installed()
    installed_ids = {a.id for a in manager._all_agents if a.available()}
    checked_ids = {aid for aid, cb in manager._checkboxes.items() if cb.isChecked()}
    check(checked_ids == installed_ids, "«Seleccionar instalados» marca solo los instalados en el sistema")

    # Filtro de búsqueda (el diálogo está oculto en la prueba: isVisibleTo mide
    # la visibilidad relativa al diálogo, no la cadena de padres ocultos).
    manager._apply_filter("Bash")
    visible_bash = [aid for aid, card in manager._cards.items() if card.isVisibleTo(manager)]
    check("shell" in visible_bash and len(visible_bash) < len(manager._cards), "el filtro oculta agentes que no coinciden")
    manager._apply_filter("")
    check(all(card.isVisibleTo(manager) for card in manager._cards.values()), "limpiar el filtro vuelve a mostrar todos los agentes")

    # Guardar selección y persistencia
    # Dejamos seleccionados shell y opencode (si existe)
    manager._select_none()
    manager._checkboxes["shell"].setChecked(True)
    manager._save_and_apply()
    check(len(config.agents) == 1 and config.agents[0].id == "shell", "guardar aplica los agentes seleccionados al config")

    # Comprobación de que desaparecen los deseleccionados y aparecen los seleccionados
    chooser = AgentChooserDialog(config.agents, config.settings, window, config=config)
    check(chooser.chosen_agent() is not None, "el selector de agentes lista los agentes")
    check(chooser._grid.count() == 1, "el selector muestra solo el agente seleccionado")
    chooser._choose_ssh()
    check(chooser.wants_ssh(), "el selector de agentes ofrece la conexión SSH")

    # Añadir otro agente a config y recargar la rejilla
    shell_agent = config.agents[0]
    config.agents = [shell_agent, Agent(id="test-agent", name="Test", command=["echo", "test"], emoji="🧪")]
    chooser._agents = list(config.agents)
    chooser._reload_grid()
    check(chooser._grid.count() == 2, "al actualizar agentes, los nuevos aparecen y los deseleccionados desaparecen")
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

    from rncli.config import HOST_KEY_MODES
    from rncli.terminal import is_host_key, tab_sequence

    settings_ui = SettingsDialog(config.settings, config.agents, window)
    check(
        settings_ui.host_combo.count() == len(HOST_KEY_MODES),
        "ajustes permite elegir la tecla Host",
    )
    check(
        "escape" not in " ".join(HOST_KEY_MODES).lower(),
        "Escape no puede ser Host Key: la usan los agentes",
    )
    settings_ui.host_combo.setCurrentIndex(max(0, settings_ui.host_combo.findData("caps_lock")))
    escaped = settings_ui.result_settings(config.settings)
    check(escaped.host_key == "caps_lock", "ajustes guarda la tecla Host elegida")
    settings_ui.hidden_check.setChecked(True)
    escaped = settings_ui.result_settings(config.settings)
    check(escaped.show_hidden_files is True, "ajustes guarda mostrar archivos ocultos")
    settings_ui.toolbar_check.setChecked(False)
    escaped = settings_ui.result_settings(config.settings)
    check(escaped.show_toolbar is False, "ajustes guarda ocultar la barra de herramientas")
    settings_ui.deleteLater()

    from rncli.config import Settings as SettingsCls

    check(SettingsCls.from_dict({}).host_key == "right_ctrl", "la Host Key por defecto es Ctrl derecho")
    check(SettingsCls.from_dict({"host_key": "menu"}).host_key == "menu", "config.json acepta host_key=menu")
    check(
        SettingsCls.from_dict({"host_key": "espacio"}).host_key == "right_ctrl",
        "host_key inválida vuelve a Ctrl derecho",
    )
    check(
        SettingsCls.from_dict({"escape_key": "host"}).host_key == "right_ctrl",
        "escape_key queda fuera de los ajustes (config antiguas arrancan normal)",
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
        SettingsCls.from_dict({}).show_toolbar is True,
        "la barra de herramientas viene visible por defecto",
    )
    check(
        SettingsCls.from_dict({"show_toolbar": False}).show_toolbar is False,
        "config.json recuerda ocultar la barra de herramientas",
    )
    check(
        SettingsCls.from_dict({}).restore_session is True,
        "recordar la sesión viene activado por defecto",
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
    check(window.toolbar.isVisible() and window.settings.show_toolbar, "la barra de herramientas arranca visible")
    window.toolbar.setVisible(False)
    check(
        not window.toolbar.isVisible()
        and not window.settings.show_toolbar
        and not window.act_toggle_toolbar.isChecked(),
        "se puede ocultar la barra de herramientas",
    )
    window.act_toggle_toolbar.trigger()
    check(
        window.toolbar.isVisible()
        and window.settings.show_toolbar
        and window.act_toggle_toolbar.isChecked(),
        "Ver → Barra de herramientas la vuelve a mostrar",
    )
    window.act_toggle_files.trigger()
    check(
        not window.file_dock.isVisible() and not window.act_toggle_files.isChecked(),
        "el atajo toggle_files oculta el explorador",
    )
    window.act_toggle_files.trigger()
    check(
        window.file_dock.isVisible() and window.act_toggle_files.isChecked(),
        "el atajo toggle_files vuelve a mostrar el explorador",
    )
    from PySide6.QtWidgets import QToolButton

    hide_buttons = [
        button
        for button in window.toolbar.findChildren(QToolButton)
        if button.text() == "Ocultar"
    ]
    check(len(hide_buttons) == 1, "la barra tiene un botón Ocultar")
    hide_buttons[0].click()
    check(
        not window.toolbar.isVisible() and not window.settings.show_toolbar,
        "el botón Ocultar esconde la barra de herramientas",
    )
    window.act_toggle_toolbar.trigger()
    window._persist_session()
    persisted = load_session()
    check(
        bool(persisted.get("tabs")),
        "al cerrar se guarda la sesión aunque restore_session esté desactivado",
    )
    check(
        isinstance(persisted.get("file_browser"), dict)
        and bool(persisted["file_browser"].get("path")),
        "la sesión guarda la carpeta del explorador",
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
    caps_ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_CapsLock, Qt.KeyboardModifier.NoModifier)
    caps_settings = dataclasses.replace(config.settings, host_key="caps_lock")
    check(not is_host_key(esc_ev, config.settings), "Escape no es Host Key por defecto")
    check(not is_host_key(esc_ev, caps_settings), "Escape nunca es Host Key, ni configurada")
    check(is_host_key(caps_ev, caps_settings), "Bloq Mayús como Host Key configurable")
    check(not is_host_key(caps_ev, config.settings), "Bloq Mayús no es Host Key por defecto")

    # --- Atajos del chasis: tabla única configurable (config.SHORTCUT_DEFAULTS) ---
    from PySide6.QtGui import QKeySequence

    from rncli.config import SHORTCUT_CLASSIC, SHORTCUT_DEFAULTS, merged_shortcuts
    from rncli.terminal import is_right_ctrl

    check(
        window.act_new_tab.shortcut() == QKeySequence(SHORTCUT_DEFAULTS["new_tab"])
        and window.act_close_pane.shortcut() == QKeySequence(SHORTCUT_DEFAULTS["close_pane"]),
        "los atajos por defecto usan Ctrl+Shift+letra y no pisan a los agentes",
    )
    check(
        window.act_toggle_files.shortcut() == QKeySequence(SHORTCUT_DEFAULTS["toggle_files"])
        and window.act_toggle_toolbar.shortcut()
        == QKeySequence(SHORTCUT_DEFAULTS["toggle_toolbar"]),
        "explorador y barra de herramientas tienen atajo por defecto",
    )
    check(
        window.act_new_tab.shortcutContext() == Qt.ShortcutContext.WindowShortcut,
        "los atajos del chasis están siempre activos",
    )
    shifted_t = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_T,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    check(
        window._host_action(shifted_t) is window.act_new_tab,
        "MODO RNCli dispara la acción según la tabla configurada",
    )
    plain_t = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
    check(window._host_action(plain_t) is None, "Ctrl+T queda libre para los agentes")

    custom = SettingsCls.from_dict(
        {"shortcuts": {"new_tab": "Ctrl+Shift+J", "close_pane": "", "rollo este": "Ctrl+X"}}
    )
    check(custom.shortcuts["new_tab"] == "Ctrl+Shift+J", "config.json guarda atajos reconfigurados")
    check(custom.shortcuts["close_pane"] == SHORTCUT_DEFAULTS["close_pane"], "un atajo vacío vuelve al defecto")
    check("rollo este" not in custom.shortcuts, "se ignoran action_ids desconocidos")
    check(SettingsCls.from_dict({}).shortcuts == SHORTCUT_DEFAULTS, "configs antiguas heredan los nuevos atajos")
    check(
        merged_shortcuts(dataclasses.replace(config.settings, shortcuts={"quit": "F9"}))["quit"] == "F9",
        "merged_shortcuts combina defectos y cambios del usuario",
    )

    shortcuts_ui = SettingsDialog(config.settings, config.agents, window)
    check("new_tab" in shortcuts_ui.shortcut_edits, "ajustes tiene pestaña de atajos")
    shortcuts_ui.shortcut_preset.setCurrentIndex(1)
    check(
        shortcuts_ui.shortcut_edits["new_tab"].keySequence() == QKeySequence(SHORTCUT_CLASSIC["new_tab"]),
        "el preset Clásico rellena los campos con los atajos antiguos",
    )
    shortcuts_ui._fill_shortcuts(SHORTCUT_DEFAULTS)
    shortcuts_ui.shortcut_edits["new_tab"].setKeySequence(QKeySequence("Ctrl+Shift+J"))
    saved_shortcuts = shortcuts_ui.result_settings(config.settings)
    check(saved_shortcuts.shortcuts["new_tab"] == "Ctrl+Shift+J", "ajustes guarda el atajo reasignado")
    shortcuts_ui.deleteLater()

    class FakeKey:  # QKeyEvent no permite fijar el scan code nativo
        def __init__(self, scan: int) -> None:
            self._scan = scan

        def type(self):
            return QEvent.Type.KeyPress

        def key(self):
            return Qt.Key.Key_Control

        def nativeScanCode(self) -> int:
            return self._scan

        def nativeVirtualKey(self) -> int:
            return 0

        def accept(self) -> None:
            pass

        def ignore(self) -> None:
            pass

    check(is_right_ctrl(FakeKey(105)), "Ctrl derecho detectado en X11")
    check(is_right_ctrl(FakeKey(97)), "Ctrl derecho detectado en Wayland")
    check(is_right_ctrl(FakeKey(284)), "Ctrl derecho detectado en Windows")
    check(not is_right_ctrl(FakeKey(29)), "Ctrl izquierdo no es la Host Key")
    check(
        not is_host_key(FakeKey(105), dataclasses.replace(config.settings, host_key="none")),
        "host_key=none deja todas las teclas en el agente",
    )

    # Con el foco fuera de la terminal, la Host Key alterna el MODO AGENTE
    window._host_mode = False
    window.prompt.setFocus(Qt.FocusReason.OtherFocusReason)
    wait(50)
    check(
        window.eventFilter(window, FakeKey(105)) is True and window._agent_mode,
        "Ctrl derecho entra en MODO AGENTE aunque el foco no esté en la terminal",
    )
    check(
        window.eventFilter(window, esc_ev) is False and window._agent_mode,
        "Escape no alterna el MODO AGENTE: sigue siendo tecla del agente",
    )
    check(
        window._toast.isVisible() and "MODO AGENTE" in window._toast.text(),
        "el cambio de modo muestra un aviso flotante semitransparente",
    )
    check(
        window.act_new_tab.shortcut().isEmpty() and window.act_quit.shortcut().isEmpty(),
        "en MODO AGENTE los atajos globales del chasis están apagados",
    )
    window._on_host_key()
    check(not window._agent_mode, "la Host Key vuelve a sacar del MODO AGENTE")
    check(
        window.act_new_tab.shortcut() == QKeySequence(SHORTCUT_DEFAULTS["new_tab"]),
        "al salir del MODO AGENTE los atajos vuelven a su tabla",
    )
    # MODO RNCli: atajo propio que entra y sale (no depende de la Host Key)
    window.act_host_mode.trigger()
    check(window._host_mode, "Ctrl+Shift+Space (act_host_mode) abre MODO RNCli")
    window.act_host_mode.trigger()
    check(not window._host_mode, "Ctrl+Shift+Space otra vez devuelve el teclado a la terminal")
    window._return_keyboard_to_terminal()
    check(not window._host_mode, "la Host Key vuelve a devolver el teclado a la terminal")
    window.settings = config.settings

    target = workspace.add_pane(shell, "/tmp")
    wait(200)
    if target is not None and target.terminal is not None and target.session is not None:
        target.terminal.settings = config.settings
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
        QApplication.sendEvent(
            target.terminal,
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier),
        )
        wait(40)
        check(
            any(chunk == b"\x1b" for chunk in recorded) and not window._agent_mode,
            "Escape llega al agente y no activa el MODO AGENTE",
        )
        recorded.clear()
        host_hits: list[bool] = []
        target.terminal.settings = caps_settings
        target.terminal.hostKeyPressed.connect(lambda: host_hits.append(True))
        QApplication.sendEvent(
            target.terminal,
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_CapsLock, Qt.KeyboardModifier.NoModifier),
        )
        wait(40)
        check(
            bool(host_hits) and not any(chunk for chunk in recorded),
            "la Host Key configurable no se envía al agente",
        )
        check(window._agent_mode, "la Host Key en la terminal entra en MODO AGENTE")
        check(
            target.terminal.agent_mode and window.act_new_tab.shortcut().isEmpty(),
            "en MODO AGENTE el terminal también suelta sus atajos fijos",
        )
        recorded.clear()
        # Ctrl+Shift+C ya no copia: llega a la sesión como teclas del agente
        target.terminal.keyPressEvent(
            QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_C,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
            )
        )
        check(
            any(chunk for chunk in recorded),
            "en MODO AGENTE Ctrl+Shift+C se envía a la sesión",
        )
        window._on_host_key()
        check(
            not window._agent_mode and not target.terminal.agent_mode,
            "la Host Key otra vez devuelve los atajos del chasis",
        )
        recorded.clear()
        # Acentos: tecla muerta aguda + vocal 'a' -> 'á'
        target.terminal.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Dead_Acute, Qt.KeyboardModifier.NoModifier, "")
        )
        target.terminal.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "a")
        )
        check(
            b"\xc3\xa1" in b"".join(recorded),
            "las teclas muertas componen vocales acentuadas (á)",
        )
        recorded.clear()
        # InputMethodEvent (IBus / Wayland IME)
        from PySide6.QtGui import QInputMethodEvent

        ime_ev = QInputMethodEvent()
        ime_ev.setCommitString("canción")
        target.terminal.inputMethodEvent(ime_ev)
        check(
            "canción".encode("utf-8") in b"".join(recorded),
            "inputMethodEvent reconoce caracteres acentuados desde el método de entrada",
        )
        target.session.write = real_write  # type: ignore[method-assign]
    else:
        check(False, "Tab llega al terminal seleccionado")
        check(False, "Tab no cambia el foco a otro widget")
        check(False, "Escape llega al agente y no activa el MODO AGENTE")
        check(False, "la Host Key configurable no se envía al agente")

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

    # --- explorador remoto: carga el tree del PC del panel activo --------------
    config.ssh_hosts = [*config.ssh_hosts, remote_host]
    remote_pane = window.workspace().active_pane()
    remote_pane.agent = remote_host.to_agent()
    window.file_browser.remote_button.click()
    wait(2000)
    check(
        window.file_browser.remote_mode
        and window.file_browser.remote_tree.isVisible()
        and not window.file_browser.tree.isVisible(),
        "el botón carga el árbol de archivos del PC del panel activo",
    )
    check(
        window.file_browser.remote_button.text() == window.file_browser._LOCAL_TEXT
        and window.file_browser.remote_button.isChecked(),
        "el botón cambia de texto y queda marcado en modo remoto",
    )
    check(
        bool(window.file_browser.remote_model.error),
        "un equipo inalcanzable se avisa sin colgarse el explorador",
    )
    window.file_browser.remote_button.click()
    check(
        not window.file_browser.remote_mode
        and window.file_browser.tree.isVisible()
        and window.file_browser.remote_button.text() == window.file_browser._REMOTE_TEXT
        and not window.file_browser.remote_button.isChecked(),
        "el botón otra vez vuelve al árbol local y recupera su texto",
    )
    remote_pane.agent = shell

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

    # --- Velocidad: daño del motor, caché de filas y atlas de glifos ---
    from PySide6.QtCore import QObject, QRect, Signal

    from rncli.terminal import PAD_X, PAD_Y, TerminalWidget
    from rncli.vt_engine import make_engine

    probe = make_engine(20, 6, 100)
    first = probe.take_damage()
    probe.feed(b"hola")
    damage = probe.take_damage() or []
    check(
        any(line == 0 for line, _left, _right in damage),
        "el motor informa de la fila dañada al escribir",
    )
    if probe.native:
        check(
            first is None,
            "el motor nativo arranca con daño de pantalla completa",
        )
        probe.feed(b"relleno\r\n" * 10)
        check(
            probe.take_damage() is None,
            "un scroll de pantalla fuerza el repintado completo",
        )
    else:
        check(
            isinstance(first, list) and len(first) == 6,
            "pyte arranca marcando toda la pantalla",
        )
        probe.feed(b"relleno\r\n" * 10)
        check(
            len(probe.take_damage() or []) == 6,
            "pyte marca toda la pantalla al hacer scroll",
        )

    view = target.terminal if target is not None else None
    if view is not None and view._screen.columns > 1:
        view.feed_text("coherencia-cache-rncli\n")
        wait(80)
        history = view._history_len()
        coherent = all(
            [cell.data for cell in view._row_for_paint(history + row)]
            == [cell.data for cell in view._engine.row(history + row)]
            for row in range(view._screen.lines)
        )
        check(coherent, "la caché de filas coincide con el motor tras escribir")
        check(
            len(view._row_cache) <= view._row_cache_cap,
            "la caché de filas está acotada",
        )
    else:
        check(False, "la caché de filas coincide con el motor tras escribir")
        check(False, "la caché de filas está acotada")

    class _FakeTerm(QObject):
        dataReceived = Signal(bytes)

        def write(self, data: bytes) -> None:
            pass

        def is_alive(self) -> bool:
            return True

        def resize(self, cols: int, rows: int) -> None:
            pass

    paint_view = TerminalWidget(_FakeTerm(), config.settings, window)
    paint_view.resize(440, 180)
    paint_view.show()
    wait(60)
    paint_view.session.dataReceived.emit(b"\x1b[1mhola\x1b[0m rncli \xe2\x9c\x93\r\n")
    wait(60)
    paint_view.update()
    wait(60)
    painted = len(paint_view._atlas._cache)
    check(painted > 0, "el atlas de glifos cachea lo pintado")
    paint_view.update()
    wait(60)
    check(
        len(paint_view._atlas._cache) == painted,
        "el atlas reutiliza los glifos ya pintados",
    )
    full = paint_view.grab().toImage()
    cell = paint_view._cursor_rect() or QRect(
        int(PAD_X), int(PAD_Y), int(paint_view._cell_w), int(paint_view._cell_h)
    )
    paint_view.update(cell)
    wait(60)
    check(
        paint_view.grab().toImage() == full,
        "el repintado parcial de una celda deja la misma imagen",
    )
    paint_view.set_font(config.settings.font_family, int(config.settings.font_size))
    check(not paint_view._atlas._cache, "cambiar la fuente vacía el atlas de glifos")
    paint_view.deleteLater()

    if args.screenshot:
        window.workspace().set_layout("all")
        wait(250)
        window.grab().save(args.screenshot)
        print(f"[info] captura guardada en {args.screenshot}")

    # --- mover paneles entre pestañas -----------------------------------------
    from rncli.dialogs import MovePaneDialog

    main_ws = window.workspace()
    before = main_ws.count()
    donor = window.new_tab(shell, "/tmp")
    wait(400)
    check(window.tabs.count() == 2, "can create tabs")
    moved_pane = donor.active_pane()
    check(moved_pane is not None and moved_pane.is_alive(), "the panel to move is alive")
    window._move_pane_to_tab(moved_pane, window.tabs.indexOf(main_ws))
    wait(400)
    check(main_ws.count() == before + 1, "the panel arrives in the other pestaña")
    check(moved_pane.is_alive(), "the moved process stays alive during the move")
    check(window.tabs.count() == 1, "the empty pestaña disappears")
    pane2 = window.workspace().active_pane()
    window._move_pane_to_tab(pane2, -1)
    wait(400)
    check(
        window.tabs.count() == 2 and window.workspace().count() == 1,
        "moving to a new pestaña creates one with the panel",
    )
    dialog = MovePaneDialog(window.workspace().panes(), [(0, "Other")], window)
    check(
        dialog.chosen_pane() is window.workspace().active_pane()
        and dialog.chosen_target() == 0,
        "the move dialog defaults to the active panel and the first tab",
    )
    dialog.deleteLater()

    # --- arrastrar paneles (misma pestaña y otras) ----------------------------
    import rncli.pane as pane_mod
    from rncli.pane import PANE_MIME
    from rncli.window import PaneDropTabBar

    grid = window.new_tab(shell, "/tmp")
    grid.add_pane(shell, "/tmp")
    grid.set_layout("2v")
    wait(400)
    left, right = grid.panes()
    check(left is not right and grid.count() == 2, "pestaña con dos paneles para reordenar")
    grid.reorder_pane(right, 0)
    wait(80)
    check(
        grid.panes()[0] is right and grid.panes()[1] is left,
        "reorder_pane coloca el panel al principio",
    )
    grid.reorder_pane(right, 2)
    wait(80)
    check(
        grid.panes()[0] is left and grid.panes()[1] is right,
        "reorder_pane coloca el panel al final",
    )

    pane_mod._active_drag = left
    mime = QMimeData()
    mime.setData(PANE_MIME, left.pane_id.encode("utf-8"))
    enter = QDragEnterEvent(
        QPoint(8, 8),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    right.dragEnterEvent(enter)
    check(enter.isAccepted(), "un panel acepta soltar otro panel")
    drop_pos = QPointF(max(80.0, float(max(right.width(), 1)) - 4.0), 8.0)
    drop_ev = QDropEvent(
        drop_pos,
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    right.dropEvent(drop_ev)
    wait(120)
    check(
        bool(drop_ev.isAccepted())
        and grid.panes()[0] is right
        and grid.panes()[1] is left,
        "soltar un panel a la derecha del otro cambia el orden",
    )

    other = window.new_tab(shell, "/tmp")
    wait(300)
    moving = other.active_pane()
    bar = window.tabs.tabBar()
    check(isinstance(bar, PaneDropTabBar), "la barra de pestañas es la que acepta paneles")
    check(moving is not None and moving.is_alive(), "el panel a arrastrar a otra pestaña está vivo")
    pane_mod._active_drag = moving
    mime2 = QMimeData()
    mime2.setData(PANE_MIME, moving.pane_id.encode("utf-8"))
    dest_index = window.tabs.indexOf(grid)
    tab_pos = bar.tabRect(dest_index).center()
    enter2 = QDragEnterEvent(
        tab_pos,
        Qt.DropAction.MoveAction,
        mime2,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    bar.dragEnterEvent(enter2)
    check(enter2.isAccepted(), "la barra de pestañas acepta soltar un panel")
    drop2 = QDropEvent(
        QPointF(tab_pos),
        Qt.DropAction.MoveAction,
        mime2,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    bar.dropEvent(drop2)
    wait(150)
    check(
        moving in grid.panes() and moving.is_alive(),
        "soltar el panel en otra pestaña lo mueve sin matar el proceso",
    )
    pane_mod._active_drag = None

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
