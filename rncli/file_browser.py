"""Explorador lateral: carpetas para el cwd y archivos para pegar en cada terminal."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QDir, QItemSelection, QModelIndex, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from .remote_fs import IsDirRole, PathRole, RemoteFsModel, RemoteTarget, remote_parent
from .ssh_hosts import SshHost


class FileBrowserWidget(QWidget):
    """Árbol de archivos y carpetas con acciones sobre el panel activo.

    Dos árboles comparten el espacio: el local (``QFileSystemModel``) y el de
    los archivos del PC del panel activo (``RemoteFsModel``, que solo se carga
    cuando ese panel es una conexión SSH).
    """

    directorySelected = Signal(str)
    assignRequested = Signal(str)
    filesRequested = Signal(list)
    showHiddenChanged = Signal(bool)
    #: Se pulsó el botón: la ventana carga el equipo del panel activo.
    remoteRequested = Signal()
    #: Se eligió una carpeta remota: la ventana re-ancla allí el panel SSH.
    remoteAssignRequested = Signal(str)

    _VISIBLE_FILTER = (
        QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives
    )
    _REMOTE_TEXT = "Archivos remotos"
    _LOCAL_TEXT = "← Volver al local"
    _REMOTE_TIP = (
        "Carga el árbol de archivos del PC del panel activo (SSH).\n"
        "Púlsalo otra vez para volver al árbol local."
    )

    def __init__(
        self,
        start_dir: str = "",
        parent: QWidget | None = None,
        *,
        show_hidden: bool = False,
    ) -> None:
        super().__init__(parent)
        self._current_dir = ""
        self._selected_files: list[str] = []
        self._show_hidden = bool(show_hidden)
        self._remote_mode = False
        self._local_dir = str(Path.home())

        self.model = QFileSystemModel(self)
        self.model.setReadOnly(True)
        self._apply_filter()

        self.remote_model = RemoteFsModel(self)
        self.remote_model.rootChanged.connect(self._remote_root_changed)
        self.remote_model.statusChanged.connect(self._remote_status_changed)

        self.tree = QTreeView(self)
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(16)
        self.tree.setUniformRowHeights(True)
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.tree.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.tree.doubleClicked.connect(self._activated)

        self.remote_tree = QTreeView(self)
        self.remote_tree.setModel(self.remote_model)
        self.remote_tree.setHeaderHidden(True)
        self.remote_tree.setAnimated(True)
        self.remote_tree.setIndentation(16)
        self.remote_tree.setUniformRowHeights(True)
        self.remote_tree.setDragEnabled(True)
        self.remote_tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.remote_tree.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.remote_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.remote_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for column in (1, 2, 3):
            self.remote_tree.hideColumn(column)
        self.remote_tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.remote_tree.doubleClicked.connect(self._activated)
        self.remote_tree.setVisible(False)

        self.path_edit = QLineEdit(self)
        self.path_edit.setPlaceholderText("Ruta…")
        self.path_edit.returnPressed.connect(self._go_to_path)

        up = QToolButton(self)
        up.setObjectName("IconButton")
        up.setText("↑")
        up.setToolTip("Carpeta padre")
        up.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        up.clicked.connect(self._go_up)
        home = QToolButton(self)
        home.setObjectName("IconButton")
        home.setText("⌂")
        home.setToolTip("Carpeta personal")
        home.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        home.clicked.connect(lambda: self.set_root(str(Path.home())))
        self.hidden_button = QToolButton(self)
        self.hidden_button.setObjectName("IconButton")
        self.hidden_button.setText(".*")
        self.hidden_button.setCheckable(True)
        self.hidden_button.setChecked(self._show_hidden)
        self.hidden_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hidden_button.setToolTip(
            "Mostrar u ocultar archivos ocultos (los que empiezan por «.»). Ctrl+H"
        )
        self.hidden_button.toggled.connect(self.set_show_hidden)
        self._hidden_shortcut = QShortcut(QKeySequence("Ctrl+H"), self)
        self._hidden_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._hidden_shortcut.activated.connect(self.toggle_show_hidden)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(6)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(up)
        path_row.addWidget(home)
        path_row.addWidget(self.hidden_button)

        self.selected_label = QLabel("Selecciona una carpeta o un archivo")
        self.selected_label.setWordWrap(True)
        self.selected_label.setObjectName("FileBrowserSelection")

        self.assign_button = QPushButton("Usar carpeta")
        self.assign_button.setToolTip("Cambia el directorio del panel activo y lo reinicia allí")
        self.assign_button.clicked.connect(self._assign)
        self.add_button = QPushButton("Pegar archivo")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setToolTip(
            "Pega la ruta (imagen, PDF, texto o cualquier archivo) en el terminal activo.\n"
            "También puedes arrastrar el archivo y soltarlo encima de un panel concreto."
        )
        self.add_button.clicked.connect(self._add_files)
        self.add_button.setEnabled(False)
        self.remote_button = QPushButton(self._REMOTE_TEXT)
        self.remote_button.setCheckable(True)
        self.remote_button.setToolTip(self._REMOTE_TIP)
        self.remote_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.remote_button.clicked.connect(self._toggle_remote)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        actions.addWidget(self.assign_button, 1)
        actions.addWidget(self.add_button, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        root.addLayout(path_row)
        root.addWidget(self.tree, 1)
        root.addWidget(self.remote_tree, 1)
        root.addWidget(self.selected_label)
        root.addLayout(actions)
        root.addWidget(self.remote_button)

        self.setMinimumWidth(240)
        self.set_root(start_dir or str(Path.home()))

    def _apply_filter(self) -> None:
        filt = self._VISIBLE_FILTER
        if self._show_hidden:
            filt |= QDir.Filter.Hidden
        self.model.setFilter(filt)

    def set_show_hidden(self, show: bool) -> None:
        show = bool(show)
        if show == self._show_hidden:
            if self.hidden_button.isChecked() != show:
                self.hidden_button.blockSignals(True)
                self.hidden_button.setChecked(show)
                self.hidden_button.blockSignals(False)
            return
        self._show_hidden = show
        if self.hidden_button.isChecked() != show:
            self.hidden_button.blockSignals(True)
            self.hidden_button.setChecked(show)
            self.hidden_button.blockSignals(False)
        self._apply_filter()
        self.remote_model.set_show_hidden(show)
        self.showHiddenChanged.emit(show)

    def toggle_show_hidden(self) -> None:
        self.set_show_hidden(not self._show_hidden)

    @property
    def show_hidden(self) -> bool:
        return self._show_hidden

    @property
    def current_dir(self) -> str:
        return self._current_dir

    @property
    def remote_mode(self) -> bool:
        return self._remote_mode

    # ------------------------------------------------------------------ remoto (panel SSH)
    def _toggle_remote(self) -> None:
        """Botón: carga el árbol del PC del panel activo (o vuelve al local)."""
        if self._remote_mode:
            self.show_local()
        else:
            self.remoteRequested.emit()

    def show_remote(self, host: SshHost | None) -> None:
        """Apunta el explorador a los archivos remotos de ``host`` (el PC del panel)."""
        if host is None or not host.host:
            return
        self.remote_model.set_source(
            RemoteTarget.from_host(host),
            root="~",
            show_hidden=self._show_hidden,
        )
        self._remote_mode = True
        self.remote_tree.setVisible(True)
        self.tree.setVisible(False)
        self.remote_button.setChecked(True)
        self.remote_button.setText(self._LOCAL_TEXT)
        self.remote_button.setToolTip(
            f"Viendo los archivos de {host.label}.\nPulsa para volver al árbol local."
        )
        self._selected_files = []
        self._current_dir = ""
        self.path_edit.setText(host.target)
        self._update_labels()
        self.selected_label.setText(f"Cargando los archivos de {host.label}…")

    def show_local(self) -> None:
        """Vuelve al árbol local de la máquina que ejecuta RNCli."""
        if not self._remote_mode:
            return
        self._remote_mode = False
        self.remote_tree.setVisible(False)
        self.tree.setVisible(True)
        self.remote_button.setChecked(False)
        self.remote_button.setText(self._REMOTE_TEXT)
        self.remote_button.setToolTip(self._REMOTE_TIP)
        self._current_dir = self._local_dir or str(Path.home())
        self.path_edit.setText(self._current_dir)
        self._update_labels()

    def _remote_root_changed(self, path: str) -> None:
        """El ``~`` remoto se resolvió a la carpeta canónica del PC."""
        self._current_dir = str(path)
        self.path_edit.setText(self._current_dir)
        self._update_labels()

    def _remote_status_changed(self, error: str) -> None:
        """Un listado remoto falló (vacío = todo bien)."""
        if error:
            self.selected_label.setText(f"Error remoto: {error}")
        else:
            self._update_labels()

    # ------------------------------------------------------------------ navegación
    def set_root(self, path: str) -> None:
        self.show_local()
        path = os.path.realpath(os.path.expanduser(path or "~"))
        if not os.path.isdir(path):
            path = str(Path.home())
        index = self.model.setRootPath(path)
        self.tree.setRootIndex(index)
        self.path_edit.setText(path)
        self._selected_files = []
        self._local_dir = path
        self._current_dir = path
        self._update_labels()
        self.directorySelected.emit(path)

    def _go_to_path(self) -> None:
        self.set_root(self.path_edit.text())

    def _go_up(self) -> None:
        path = os.path.dirname(self._current_dir or str(Path.home()))
        self.set_root(path)

    def _path_for_index(self, index: QModelIndex) -> str:
        if not index.isValid():
            return ""
        if self._remote_mode:
            return str(index.data(PathRole) or "")
        return os.path.realpath(self.model.filePath(index))

    def _on_selection_changed(self, _selected: QItemSelection, _deselected: QItemSelection) -> None:
        self._refresh_selection()

    def _refresh_selection(self) -> None:
        files: list[str] = []
        dirs: list[str] = []
        tree = self.remote_tree if self._remote_mode else self.tree
        selection = tree.selectionModel()
        if selection is None:
            return
        for index in selection.selectedRows():
            path = self._path_for_index(index)
            if not path:
                continue
            if self._remote_mode:
                if bool(index.data(IsDirRole)):
                    dirs.append(path)
                else:
                    files.append(path)
            elif os.path.isfile(path):
                files.append(path)
            elif os.path.isdir(path):
                dirs.append(path)
        self._selected_files = list(dict.fromkeys(files))
        if dirs:
            self._current_dir = dirs[-1]
            self.path_edit.setText(self._current_dir)
        elif self._selected_files:
            if self._remote_mode:
                parent = remote_parent(self._selected_files[0])
                self._current_dir = parent
                self.path_edit.setText(parent)
            else:
                parent = os.path.dirname(self._selected_files[0])
                if os.path.isdir(parent):
                    self._current_dir = parent
                    self.path_edit.setText(parent)
        self._update_labels()
        if self._current_dir and not self._remote_mode:
            self.directorySelected.emit(self._current_dir)

    def _update_labels(self) -> None:
        if self._selected_files:
            names = ", ".join(os.path.basename(path) for path in self._selected_files[:5])
            extra = f" (+{len(self._selected_files) - 5})" if len(self._selected_files) > 5 else ""
            self.selected_label.setText(f"{len(self._selected_files)} archivo(s) · {names}{extra}")
        elif self._current_dir:
            self.selected_label.setText(self._current_dir)
        else:
            self.selected_label.setText("Selecciona una carpeta o un archivo")
        self.add_button.setEnabled(bool(self._selected_files))
        self.assign_button.setEnabled(
            bool(self._current_dir)
            and (self._remote_mode or os.path.isdir(self._current_dir))
        )

    def _activated(self, index: QModelIndex) -> None:
        path = self._path_for_index(index)
        if not path:
            return
        if self._remote_mode:
            if bool(index.data(IsDirRole)):
                self._current_dir = path
                self._update_labels()
                self.remoteAssignRequested.emit(path)
            else:
                chosen = self._selected_files if path in self._selected_files else [path]
                self.filesRequested.emit(list(chosen))
            return
        if os.path.isdir(path):
            self._current_dir = path
            self._update_labels()
            self.assignRequested.emit(path)
        elif os.path.isfile(path):
            chosen = self._selected_files if path in self._selected_files else [path]
            self.filesRequested.emit(list(chosen))

    # ------------------------------------------------------------------ acciones
    def _assign(self) -> None:
        if not self._current_dir:
            return
        if self._remote_mode:
            self.remoteAssignRequested.emit(self._current_dir)
        elif os.path.isdir(self._current_dir):
            self.assignRequested.emit(self._current_dir)

    def _add_files(self) -> None:
        if self._selected_files:
            self.filesRequested.emit(list(self._selected_files))

    @property
    def selected_directory(self) -> str:
        return self._current_dir

    @property
    def selected_files(self) -> list[str]:
        return list(self._selected_files)
