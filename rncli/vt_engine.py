"""Motor de terminal: Rust (alacritty) si está compilado, pyte si no."""

from __future__ import annotations

from dataclasses import dataclass

try:
    import rncli_native
except ImportError:
    rncli_native = None

NATIVE = rncli_native is not None

FLAG_BOLD = 1
FLAG_ITALIC = 1 << 1
FLAG_UNDERLINE = 1 << 2
FLAG_STRIKE = 1 << 3
FLAG_REVERSE = 1 << 4


@dataclass(slots=True)
class Cell:
    data: str = " "
    fg: object = "default"
    bg: object = "default"
    bold: bool = False
    italics: bool = False
    underscore: bool = False
    strikethrough: bool = False
    reverse: bool = False


BLANK = Cell()


def unpack_row(raw) -> list[Cell]:
    cells: list[Cell] = []
    for data, fg, bg, flags in raw:
        cells.append(
            Cell(
                data=data,
                fg=fg,
                bg=bg,
                bold=bool(flags & FLAG_BOLD),
                italics=bool(flags & FLAG_ITALIC),
                underscore=bool(flags & FLAG_UNDERLINE),
                strikethrough=bool(flags & FLAG_STRIKE),
                reverse=bool(flags & FLAG_REVERSE),
            )
        )
    return cells


class _Dirty(set):
    pass


class _RowView:
    def __init__(self, cells: list[Cell]) -> None:
        self._cells = cells

    def __getitem__(self, col: int) -> Cell:
        return self._cells[col]

    def __iter__(self):
        return iter(self._cells)

    def get(self, col: int, default=None):
        if 0 <= col < len(self._cells):
            return self._cells[col]
        return default


class _Buffer:
    def __init__(self, engine: NativeEngine) -> None:
        self._engine = engine

    def __getitem__(self, y: int) -> _RowView:
        return _RowView(self._engine.row(self._engine.history_len() + int(y)))


class _HistoryTop:
    def __init__(self, engine: NativeEngine) -> None:
        self._engine = engine

    def __len__(self) -> int:
        return self._engine.history_len()

    def __getitem__(self, index: int):
        return dict(enumerate(self._engine.row(index)))


class _History:
    def __init__(self, engine: NativeEngine) -> None:
        self.top = _HistoryTop(engine)


class _Cursor:
    def __init__(self, engine: NativeEngine) -> None:
        self._engine = engine

    @property
    def x(self) -> int:
        return int(self._engine.cursor()[0])

    @property
    def y(self) -> int:
        return int(self._engine.cursor()[1])

    @property
    def hidden(self) -> bool:
        return bool(self._engine.cursor()[2])


class _Screen:
    """Fachada con la misma forma que pyte.HistoryScreen (pruebas y pintado)."""

    def __init__(self, engine: NativeEngine) -> None:
        self._engine = engine
        self.dirty: set = _Dirty()
        self.history = _History(engine)
        self.buffer = _Buffer(engine)
        self.cursor = _Cursor(engine)
        self.bell = False

    @property
    def columns(self) -> int:
        return self._engine.columns()

    @property
    def lines(self) -> int:
        return self._engine.lines()

    @property
    def title(self) -> str:
        return self._engine.title()

    @property
    def mode(self) -> set:
        modes: set = set()
        if self._engine.app_cursor():
            modes.add(1)
        if self._engine.bracketed_paste():
            modes.add(2004)
        return modes

    def resize(self, lines: int | None = None, columns: int | None = None) -> None:
        self._engine.resize(columns or self.columns, lines or self.lines)


class NativeEngine:
    native = True

    def __init__(self, cols: int, rows: int, scrollback: int) -> None:
        assert rncli_native is not None
        self._vte = rncli_native.NativeVte(int(cols), int(rows), int(scrollback))
        self.screen = _Screen(self)
        self.blank = BLANK

    def feed(self, data: bytes) -> bytes:
        return bytes(self._vte.feed(data) or b"")

    def resize(self, cols: int, rows: int) -> None:
        self._vte.resize(int(cols), int(rows))

    def columns(self) -> int:
        return int(self._vte.columns())

    def lines(self) -> int:
        return int(self._vte.lines())

    def history_len(self) -> int:
        return int(self._vte.history_len())

    def row(self, abs_row: int) -> list[Cell]:
        if abs_row < 0:
            return [BLANK] * self.columns()
        return unpack_row(self._vte.row(int(abs_row)))

    def cursor(self) -> tuple[int, int, bool]:
        x, y, hidden = self._vte.cursor()
        return int(x), int(y), bool(hidden)

    def app_cursor(self) -> bool:
        return bool(self._vte.app_cursor())

    def bracketed_paste(self) -> bool:
        return bool(self._vte.bracketed_paste())

    def title(self) -> str:
        return str(self._vte.title() or "")

    def take_bell(self) -> bool:
        return bool(self._vte.take_bell())


class PyteEngine:
    native = False

    def __init__(self, cols: int, rows: int, scrollback: int) -> None:
        import pyte

        self._pyte = pyte
        self.screen = pyte.HistoryScreen(int(cols), int(rows), history=int(scrollback), ratio=0.5)
        self._stream = pyte.ByteStream(self.screen)
        self.blank = pyte.screens.Char(" ")

    def feed(self, data: bytes) -> bytes:
        if data:
            self._stream.feed(data)
        return b""

    def resize(self, cols: int, rows: int) -> None:
        self.screen.resize(lines=int(rows), columns=int(cols))

    def columns(self) -> int:
        return int(self.screen.columns)

    def lines(self) -> int:
        return int(self.screen.lines)

    def history_len(self) -> int:
        return len(self.screen.history.top)

    def row(self, abs_row: int) -> list:
        cols = self.columns()
        if abs_row < 0:
            return [self.blank] * cols
        hist = self.screen.history.top
        hlen = len(hist)
        if abs_row < hlen:
            row = hist[abs_row]
            return [row.get(col, self.blank) for col in range(cols)]
        y = abs_row - hlen
        if 0 <= y < self.screen.lines:
            row = self.screen.buffer[y]
            return [row[col] for col in range(cols)]
        return [self.blank] * cols

    def cursor(self) -> tuple[int, int, bool]:
        cur = self.screen.cursor
        return int(cur.x), int(cur.y), bool(cur.hidden)

    def app_cursor(self) -> bool:
        return 1 in getattr(self.screen, "mode", set())

    def bracketed_paste(self) -> bool:
        return 2004 in getattr(self.screen, "mode", set())

    def title(self) -> str:
        title = getattr(self.screen, "title", "") or ""
        return title if isinstance(title, str) else ""

    def take_bell(self) -> bool:
        if callable(getattr(self.screen, "bell", None)):
            return False
        if getattr(self.screen, "bell", False):
            self.screen.bell = False
            return True
        return False


def make_engine(cols: int, rows: int, scrollback: int):
    if NATIVE:
        try:
            return NativeEngine(cols, rows, scrollback)
        except Exception:
            pass
    return PyteEngine(cols, rows, scrollback)


def spawn_native_pty(argv: list[str], cwd: str, env: dict[str, str], cols: int, rows: int):
    if not NATIVE:
        return None
    return rncli_native.NativePty(list(argv), str(cwd), dict(env), int(cols), int(rows))
