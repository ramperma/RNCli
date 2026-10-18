"""Sistema de archivos remoto de un panel SSH: transporte asíncrono y modelo de árbol.

No se añade ninguna dependencia: se reutiliza el binario ``ssh`` y su **socket de
control** (ver ``ssh_hosts.control_socket_pattern``), así que los listados viajan
por la conexión que el propio panel ya autenticó — con sus alias de
``~/.ssh/config``, su agente, su contraseña o su 2FA.

El árbol solo necesita *nombre* y *si es carpeta* (el explorador oculta tamaño,
tipo y fecha), por eso basta con ``ls -1 -p -b``, que es POSIX.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass

from PySide6.QtCore import (
    QAbstractItemModel,
    QMimeData,
    QModelIndex,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
)

from .shell_env import resolve_executable
from .ssh_hosts import SshHost

#: Ruta remota completa de una fila: el nombre visible puede repetirse.
PathRole = Qt.ItemDataRole.UserRole + 1
#: True si la fila es una carpeta (no hay que tocar el disco para saberlo).
IsDirRole = Qt.ItemDataRole.UserRole + 2

#: MIME interno: una ruta remota NO es un archivo local y no debe tratarse como tal.
REMOTE_PATH_MIME = "application/x-rncli-remote-path"

LIST_TIMEOUT_S = 8.0
CACHE_TTL_S = 20.0
MAX_WORKERS = 2


# --------------------------------------------------------------------------- datos
@dataclass(frozen=True)
class RemoteTarget:
    """Destino de un panel SSH, hashable para poder cachear sus listados."""

    host: str = ""
    user: str = ""
    port: int = 22
    identity: str = ""
    options: tuple[str, ...] = ()
    keepalive: bool = True
    name: str = ""

    @classmethod
    def from_host(cls, host: SshHost) -> RemoteTarget:
        return cls(
            host=host.host,
            user=host.user,
            port=int(host.port or 22),
            identity=host.identity,
            options=tuple(host.options),
            keepalive=bool(host.keepalive),
            name=host.name or host.label,
        )

    def to_host(self) -> SshHost:
        return SshHost(
            host=self.host,
            user=self.user,
            port=self.port,
            identity=self.identity,
            options=list(self.options),
            name=self.name,
            keepalive=self.keepalive,
        )

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    @property
    def label(self) -> str:
        return self.name or self.target

    @property
    def id(self) -> str:
        return f"{self.target}:{int(self.port)}"

    def cache_key(self, path: str, show_hidden: bool) -> tuple[str, str, bool]:
        return (self.id, path or "~", bool(show_hidden))


@dataclass(slots=True)
class Entry:
    """Una fila de un directorio remoto."""

    name: str
    path: str
    is_dir: bool


def join_remote(root: str, name: str) -> str:
    """Une una ruta remota sin duplicar las barras."""
    if not name:
        return root
    if root in ("", "/"):
        return "/" + name
    return root.rstrip("/") + "/" + name


def remote_parent(path: str) -> str:
    """Carpeta padre de una ruta remota absoluta (``/`` para la raíz)."""
    clean = (path or "").rstrip("/")
    if not clean or clean == "/":
        return "/"
    return os.path.dirname(clean) or "/"


def unescape_ls_name(raw: str) -> str:
    """Deshace los escapes de ``ls -b`` (``\\`` literal y octales como ``\\012``)."""
    out: list[str] = []
    index = 0
    length = len(raw)
    while index < length:
        char = raw[index]
        if char != "\\" or index + 1 >= length:
            out.append(char)
            index += 1
            continue
        cursor = index + 1
        digits = ""
        while cursor < length and len(digits) < 3 and raw[cursor] in "01234567":
            digits += raw[cursor]
            cursor += 1
        if digits:
            out.append(chr(int(digits, 8)))
            index = cursor
        else:
            out.append(raw[cursor])
            index = cursor + 1
    return "".join(out)


def parse_listing(stdout: str) -> tuple[str, list[Entry]]:
    """Convierte la salida de ``pwd -P && ls -1 -p -b`` en ``(ruta, entradas)``.

    La primera línea es el ``pwd -P`` del directorio pedido: da la ruta canónica
    (por eso ``~`` se resuelve solo) y confirma que existe.
    """
    lines = (stdout or "").splitlines()
    if not lines:
        return "", []
    root = lines[0].strip()
    entries: list[Entry] = []
    for line in lines[1:]:
        if not line:
            continue
        name = unescape_ls_name(line)
        is_dir = name.endswith("/")
        if is_dir:
            name = name[:-1]
        if not name or name in (".", ".."):
            continue
        entries.append(Entry(name, join_remote(root, name), is_dir))
    entries.sort(key=lambda item: (not item.is_dir, item.name.casefold(), item.name))
    return root, entries


def _clean_error(text: str) -> str:
    """Mensaje útil de stderr, sin los avisos de conexión que añade ssh."""
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if line and not line.startswith("Connection to "):
            return line
    return "el equipo remoto rechazó la orden"


# --------------------------------------------------------------------------- transporte
class _JobSignals(QObject):
    finished = Signal(int, str, list, str)  # secuencia, ruta, entradas, error


class _ListJob(QRunnable):
    """Lista un directorio remoto en un hilo de trabajo."""

    def __init__(
        self, host: SshHost, path: str, show_hidden: bool, seq: int, signals: _JobSignals
    ) -> None:
        super().__init__()
        # El QRunnable vive en C++ pero lo referenciamos desde Python hasta que
        # termina: sin esto, el recolector de basura podría destruirlo en vuelo.
        self.setAutoDelete(False)
        self.host = host
        self.path = path
        self.show_hidden = show_hidden
        self.seq = seq
        self.signals = signals
        self._error = ""
        self._entries: list[Entry] = []
        self._root = ""

    def run(self) -> None:
        argv = self.host.listing_command(self.path, self.show_hidden)
        resolved = resolve_executable(argv[0])
        if resolved:
            argv[0] = resolved
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=LIST_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            self._error = f"el equipo no respondió en {int(LIST_TIMEOUT_S)} s"
        except FileNotFoundError:
            self._error = "no se encontró el binario «ssh»"
        except OSError as exc:
            self._error = f"no se pudo lanzar ssh: {exc}"
        else:
            if proc.returncode != 0:
                self._error = _clean_error(proc.stderr or proc.stdout)
            else:
                self._root, self._entries = parse_listing(proc.stdout or "")
        self.signals.finished.emit(self.seq, self._root or self.path, self._entries, self._error)


class RemoteClient(QObject):
    """Cola de listados: nunca bloquea la interfaz, cachea y deduplica trabajo."""

    listed = Signal(int, str, list, str)  # secuencia, ruta, entradas, error

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool()
        self._pool.setParent(self)
        self._pool.setMaxThreadCount(MAX_WORKERS)
        self._cache: dict[tuple[str, str, bool], tuple[float, list[Entry]]] = {}
        self._inflight: dict[tuple[str, str, bool], int] = {}
        self._jobs: dict[int, tuple[_ListJob, _JobSignals, tuple[str, str, bool]]] = {}
        self._seq = 0

    def request(self, target: RemoteTarget, path: str, show_hidden: bool) -> tuple[int, list | None]:
        """Pide un directorio y devuelve ``(seq, entries)``.

        Con caché fresca devuelve los datos directamente (no emite la señal
        antes de que el modelo haya registrado la petición, o la respuesta
        llegaría antes de que la carpeta esté lista); si no, lanza el trabajo
        y devuelve ``None``: la respuesta llegará por ``listed``.
        """
        key = target.cache_key(path, show_hidden)
        cached = self._cache.get(key)
        if cached is not None and (time.monotonic() - cached[0]) < CACHE_TTL_S:
            self._seq += 1
            return self._seq, list(cached[1])
        running = self._inflight.get(key)
        if running is not None:
            return running, None
        self._seq += 1
        seq = self._seq
        signals = _JobSignals(self)
        signals.finished.connect(self._on_finished)
        job = _ListJob(target.to_host(), key[1], show_hidden, seq, signals)
        self._jobs[seq] = (job, signals, key)
        self._inflight[key] = seq
        self._pool.start(job)
        return seq, None

    def _on_finished(self, seq: int, path: str, entries: list, error: str) -> None:
        handle = self._jobs.pop(seq, None)
        if handle is None:
            return  # cancelada mientras estaba en vuelo
        _job, signals, key = handle
        self._inflight.pop(key, None)
        signals.deleteLater()
        if not error:
            self._cache[key] = (time.monotonic(), list(entries))
        self.listed.emit(seq, path, list(entries), error)

    def invalidate(self) -> None:
        self._cache.clear()

    def cancel_all(self) -> None:
        """Olvida las peticiones pendientes: el modelo ya no quiere esas carpetas."""
        self._pool.clear()
        self._jobs.clear()
        self._inflight.clear()


# --------------------------------------------------------------------------- modelo
class _Node:
    __slots__ = ("children", "is_dir", "loaded", "loading", "name", "parent", "path", "row")

    def __init__(
        self, name: str, path: str, is_dir: bool, parent: _Node | None, row: int = -1
    ) -> None:
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.parent = parent
        self.children: list[_Node] | None = None
        self.loaded = False
        self.loading = False
        self.row = row


class RemoteFsModel(QAbstractItemModel):
    """Árbol de un equipo remoto, con carga perezosa por carpeta."""

    #: La raíz se ha resuelto (``~`` → ``/home/usuario``): hay que refrescar la caja de ruta.
    rootChanged = Signal(str)
    #: Un listado ha fallado (vacío = todo bien): para el aviso del explorador.
    statusChanged = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.client = RemoteClient(self)
        self.client.listed.connect(self._apply)
        self.target: RemoteTarget | None = None
        self.show_hidden = False
        self.root_path = ""
        self.error = ""
        self._root = _Node("", "", True, None)
        self._nodes: dict[str, _Node] = {}
        self._wanted: dict[int, _Node] = {}

    # ------------------------------------------------------------------ estado
    @property
    def ok(self) -> bool:
        return self.target is not None and not self.error

    def set_source(self, target: RemoteTarget, root: str = "~", show_hidden: bool = False) -> None:
        """Apunta el modelo a un equipo y a una carpeta remota (vacío = ``~``)."""
        self.beginResetModel()
        self.client.cancel_all()
        self._wanted.clear()
        self._nodes.clear()
        self.target = target
        self.show_hidden = bool(show_hidden)
        self.root_path = root or "~"
        self.error = ""
        self._root = _Node(_basename(self.root_path), self.root_path, True, None)
        self._nodes[self.root_path] = self._root
        self.endResetModel()
        self._fetch(self._root)

    def set_show_hidden(self, show: bool) -> None:
        if bool(show) == self.show_hidden:
            return
        self.show_hidden = bool(show)
        self.refresh()

    def refresh(self) -> None:
        """Vuelve a leer lo ya desplegado, conservando el árbol expandido."""
        if self.target is None:
            return
        self.client.invalidate()
        self._unload(self._root)
        self._set_error("")
        self._fetch(self._root)

    # ------------------------------------------------------------------ Qt
    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        node = self._child(row, parent)
        if node is None:
            return QModelIndex()
        return self.createIndex(row, column, node)

    def parent(self, index: QModelIndex = QModelIndex()) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        if node is None or node.parent is None or node.parent is self._root:
            return QModelIndex()
        return self.createIndex(node.parent.row, 0, node.parent)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        if not parent.isValid():
            return len(self._root.children or ())
        node = parent.internalPointer()
        return len(node.children or ()) if node is not None else 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        if node is None:
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return node.name
        if role == PathRole:
            return node.path
        if role == IsDirRole:
            return node.is_dir
        if role == Qt.ItemDataRole.ToolTipRole:
            return node.path
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        )

    def hasChildren(self, index: QModelIndex = QModelIndex()) -> bool:  # noqa: N802
        if not index.isValid():
            return True
        node = index.internalPointer()
        return bool(node is not None and node.is_dir)

    def canFetchMore(self, index: QModelIndex) -> bool:  # noqa: N802
        node = index.internalPointer() if index.isValid() else self._root
        return bool(
            node is not None
            and node.is_dir
            and self.target is not None
            and not node.loaded
            and not node.loading
        )

    def fetchMore(self, index: QModelIndex) -> None:  # noqa: N802
        node = index.internalPointer() if index.isValid() else self._root
        if node is not None:
            self._fetch(node)

    # ------------------------------------------------------------------ arrastre
    def mimeTypes(self) -> list[str]:  # noqa: N802
        return [REMOTE_PATH_MIME, "text/plain"]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:  # noqa: N802
        data = QMimeData()
        paths = [str(path) for index in indexes if (path := index.data(PathRole))]
        if paths:
            data.setData(REMOTE_PATH_MIME, "\n".join(paths).encode("utf-8"))
            data.setText("\n".join(paths))
        return data

    def supportedDropActions(self) -> Qt.DropAction:  # noqa: N802
        return Qt.DropAction.IgnoreAction

    def dropMimeData(self, data, action, row, column, parent) -> bool:  # noqa: N802
        return False

    # ------------------------------------------------------------------ utilidades
    def path_for(self, index: QModelIndex) -> str:
        node = index.internalPointer() if index.isValid() else None
        return str(node.path) if node is not None else ""

    def is_dir_for(self, index: QModelIndex) -> bool:
        node = index.internalPointer() if index.isValid() else None
        return bool(node is not None and node.is_dir)

    def index_for_path(self, path: str) -> QModelIndex:
        node = self._nodes.get(path)
        if node is None or node is self._root or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.row, 0, node)

    # ------------------------------------------------------------------ interno
    def _child(self, row: int, parent: QModelIndex) -> _Node | None:
        if not parent.isValid():
            children = self._root.children
        else:
            node = parent.internalPointer()
            children = node.children if node is not None else None
        if not children or row < 0 or row >= len(children):
            return None
        return children[row]

    def _index_of(self, node: _Node) -> QModelIndex:
        if node is self._root or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.row, 0, node)

    def _fetch(self, node: _Node) -> None:
        if self.target is None or node.loading or node.loaded:
            return
        node.loading = True
        seq, entries = self.client.request(self.target, node.path, self.show_hidden)
        self._wanted[seq] = node
        if entries is not None:
            self._apply(seq, node.path, entries, "")

    def _unload(self, node: _Node) -> None:
        """Vacía un nodo y sus descendientes (de abajo arriba, como pide Qt)."""
        children = node.children
        if not children:
            node.loaded = False
            node.loading = False
            return
        for child in children:
            self._nodes.pop(child.path, None)
            self._unload(child)
        parent_index = self._index_of(node)
        self.beginRemoveRows(parent_index, 0, len(children) - 1)
        node.children = None
        node.loaded = False
        node.loading = False
        self.endRemoveRows()

    def _set_error(self, error: str) -> None:
        if error == self.error:
            return
        self.error = error
        self.statusChanged.emit(error)

    def _apply(self, seq: int, path: str, entries: list, error: str) -> None:
        node = self._wanted.pop(seq, None)
        if node is None:
            return  # respuesta de una carpeta que ya no nos interesa
        node.loading = False
        if error:
            self._set_error(error)
            return
        self._set_error("")
        if node is self._root and path and path != node.path:
            # ``~`` (o un enlace) se ha resuelto a la ruta canónica del equipo.
            self._nodes.pop(node.path, None)
            node.path = path
            node.name = _basename(path)
            self.root_path = path
            self._nodes[path] = node
            self.rootChanged.emit(path)
        parent_index = self._index_of(node)
        self.beginInsertRows(parent_index, 0, len(entries) - 1)
        children: list[_Node] = []
        for position, entry in enumerate(entries):
            child = _Node(entry.name, entry.path, entry.is_dir, node, position)
            children.append(child)
            self._nodes[entry.path] = child
        node.children = children
        node.loaded = True
        self.endInsertRows()


def _basename(path: str) -> str:
    clean = (path or "").rstrip("/")
    if not clean:
        return "/"
    return os.path.basename(clean) or "/"
