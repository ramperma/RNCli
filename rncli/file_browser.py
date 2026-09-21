"""Explorador de carpetas lateral para asignar directorios a paneles."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, Signal
from PySide6.QtWidgets import (
    QFileSystemModel,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)


class FileBrowserWidget(QWidget):
    """Árbol de directorios con acciones sobre el panel activo."""

    directorySelected = Signal(str)
    assignRequested = Signal(str)
    newPanelRequested = Signal(str)

    def __init__(self, start_dir: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_dir = ""

        self.model = QFileSystemModel(self)
        self.model.setFilter(
            QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives
        )
        self.model.setReadOnly(True)

        self.tree = QTreeView(self)
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(16)
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QTreeView.DragDropMode.DragOnly)
        self.tree.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.tree.clicked.connect(self._selected)
        self.tree.doubleClicked.connect(self._activated)

        self.path_edit = QLineEdit(self)
        self.path_edit.setPlaceholderText("Ruta…")
        self.path_edit.returnPressed.connect(self._go_to_path)

        up = QToolButton(self)
        up.setText("↑")
        up.setToolTip("Carpeta padre")
        up.clicked.connect(self._go_up)
        home = QToolButton(self)
        home.setText("⌂")
        home.setToolTip("Carpeta personal")
        home.clicked.connect(lambda: self.set_root(str(Path.home())))

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(3)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(up)
        path_row.addWidget(home)

        self.selected_label = QLabel("Selecciona una carpeta")
        self.selected_label.setWordWrap(True)
        self.selected_label.setObjectName("FileBrowserSelection")

        assign = QPushButton("Asignar al terminal activo")
        assign.setToolTip("Cambia el directorio del panel activo y lo reinicia allí")
        assign.clicked.connect(self._assign)
        new_panel = QPushButton("＋ Nuevo panel aquí")
        new_panel.setToolTip("Abre el selector de agentes usando esta carpeta")
        new_panel.clicked.connect(self._new_panel)

        root = QVBoxLayout(self)
        root.setContentsMargins(7, 7, 7, 7)
        root.setSpacing(6)
        title = QLabel("Explorador de carpetas")
        title.setObjectName("FileBrowserTitle")
        root.addWidget(title)
        root.addLayout(path_row)
        root.addWidget(self.tree, 1)
        root.addWidget(self.selected_label)
        root.addWidget(assign)
        root.addWidget(new_panel)

        self.setMinimumWidth(220)
        self.set_root(start_dir or str(Path.home()))

    # ------------------------------------------------------------------ navegación
    def set_root(self, path: str) -> None:
        path = os.path.realpath(os.path.expanduser(path or "~"))
        if not os.path.isdir(path):
            path = str(Path.home())
        index = self.model.setRootPath(path)
        self.tree.setRootIndex(index)
        self.path_edit.setText(path)
        self._set_selected(path)

    def _go_to_path(self) -> None:
        self.set_root(self.path_edit.text())

    def _go_up(self) -> None:
        path = os.path.dirname(self._current_dir or str(Path.home()))
        self.set_root(path)

    def _path_for_index(self, index: QModelIndex) -> str:
        return os.path.realpath(self.model.filePath(index)) if index.isValid() else ""

    def _selected(self, index: QModelIndex) -> None:
        path = self._path_for_index(index)
        if os.path.isdir(path):
            self._set_selected(path)

    def _set_selected(self, path: str) -> None:
        if not os.path.isdir(path):
            return
        self._current_dir = path
        self.path_edit.setText(path)
        self.selected_label.setText(f"Carpeta elegida:\n{path}")
        self.directorySelected.emit(path)

    def _activated(self, index: QModelIndex) -> None:
        path = self._path_for_index(index)
        if os.path.isdir(path):
            self._set_selected(path)
            self.assignRequested.emit(path)

    # ------------------------------------------------------------------ acciones
    def _assign(self) -> None:
        if self._current_dir and os.path.isdir(self._current_dir):
            self.assignRequested.emit(self._current_dir)

    def _new_panel(self) -> None:
        if self._current_dir and os.path.isdir(self._current_dir):
            self.newPanelRequested.emit(self._current_dir)

    @property
    def selected_directory(self) -> str:
        return self._current_dir
