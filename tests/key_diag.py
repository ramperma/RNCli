"""Diagnóstico de teclas: imprime lo que Qt recibe de verdad.

Útil cuando la Host Key (Ctrl derecho, Bloq Mayús o tecla Menú) no entra en
MODO AGENTE / MODO RNCli: pulsa la tecla y compara los códigos que imprime este
script con los que reconoce rncli.terminal.is_right_ctrl
(X11 105, evdev/Wayland 97, Windows 284).

Ejecución:  QT_QPA_PLATFORM=xcb .venv/bin/python tests/key_diag.py
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from rncli.terminal import is_right_ctrl


class DiagWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RNCli · diagnóstico de teclas (cierra con Ctrl+C o la X)")
        self.resize(560, 320)
        self._info = QLabel(
            "Pulsa teclas aquí, sobre todo Ctrl derecho, Ctrl izquierdo, Bloq Mayús, "
            "tecla Menú y Escape.\n"
            "Ctrl+Q sale.\n"
            "Espera: Ctrl+Q es el atajo clásico; aquí solo cierra con la X."
        )
        self._info.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self._info)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Q and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            QApplication.instance().quit()
            return
        line = (
            f"key={key!r} text={event.text()!r} "
            f"nativeScanCode={event.nativeScanCode()} "
            f"nativeVirtualKey={event.nativeVirtualKey()} "
            f"modifiers={int(event.modifiers())}"
        )
        if key == Qt.Key.Key_Control:
            line += f"  -> is_right_ctrl={is_right_ctrl(event)}"
        print(line, flush=True)
        self._info.setText(line)


def main() -> int:
    app = QApplication(sys.argv)
    window = DiagWindow()
    window.show()
    print("Pulsa teclas en la ventana; la salida también se imprime aquí.", flush=True)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
