//! Emulador VT basado en alacritty_terminal, expuesto a Python.

use std::cell::RefCell;
use std::rc::Rc;

use alacritty_terminal::event::{Event, EventListener, WindowSize};
use alacritty_terminal::grid::Dimensions;
use alacritty_terminal::index::{Column, Line};
use alacritty_terminal::term::cell::{Cell, Flags};
use alacritty_terminal::term::{Config, Term, TermMode};
use alacritty_terminal::vte::ansi::{Color, NamedColor, Processor};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

#[derive(Clone)]
struct TermSize {
    columns: usize,
    screen_lines: usize,
}

impl Dimensions for TermSize {
    fn total_lines(&self) -> usize {
        self.screen_lines
    }

    fn screen_lines(&self) -> usize {
        self.screen_lines
    }

    fn columns(&self) -> usize {
        self.columns
    }
}

struct BusInner {
    title: String,
    bell: bool,
    writes: Vec<u8>,
    cols: u16,
    rows: u16,
}

#[derive(Clone)]
struct Bus(Rc<RefCell<BusInner>>);

impl EventListener for Bus {
    fn send_event(&self, event: Event) {
        let mut inner = self.0.borrow_mut();
        match event {
            Event::Title(title) => inner.title = title,
            Event::ResetTitle => inner.title.clear(),
            Event::Bell => inner.bell = true,
            Event::PtyWrite(data) => inner.writes.extend(data.as_bytes()),
            Event::TextAreaSizeRequest(callback) => {
                let reply = callback(WindowSize {
                    num_lines: inner.rows,
                    num_cols: inner.cols,
                    cell_width: 1,
                    cell_height: 1,
                });
                inner.writes.extend(reply.as_bytes());
            }
            _ => {}
        }
    }
}

const FLAG_BOLD: u8 = 1;
const FLAG_ITALIC: u8 = 1 << 1;
const FLAG_UNDERLINE: u8 = 1 << 2;
const FLAG_STRIKE: u8 = 1 << 3;
const FLAG_REVERSE: u8 = 1 << 4;

fn named_pyte(name: NamedColor) -> &'static str {
    match name {
        NamedColor::Black => "black",
        NamedColor::Red => "red",
        NamedColor::Green => "green",
        NamedColor::Yellow => "brown",
        NamedColor::Blue => "blue",
        NamedColor::Magenta => "magenta",
        NamedColor::Cyan => "cyan",
        NamedColor::White => "white",
        NamedColor::BrightBlack => "brightblack",
        NamedColor::BrightRed => "brightred",
        NamedColor::BrightGreen => "brightgreen",
        NamedColor::BrightYellow => "brightbrown",
        NamedColor::BrightBlue => "brightblue",
        NamedColor::BrightMagenta => "brightmagenta",
        NamedColor::BrightCyan => "brightcyan",
        NamedColor::BrightWhite => "brightwhite",
        NamedColor::Foreground | NamedColor::Background | _ => "default",
    }
}

fn indexed_hex(index: u8) -> String {
    match index {
        0 => "black".into(),
        1 => "red".into(),
        2 => "green".into(),
        3 => "brown".into(),
        4 => "blue".into(),
        5 => "magenta".into(),
        6 => "cyan".into(),
        7 => "white".into(),
        8 => "brightblack".into(),
        9 => "brightred".into(),
        10 => "brightgreen".into(),
        11 => "brightbrown".into(),
        12 => "brightblue".into(),
        13 => "brightmagenta".into(),
        14 => "brightcyan".into(),
        15 => "brightwhite".into(),
        16..=231 => {
            let n = index - 16;
            let r = n / 36;
            let g = (n % 36) / 6;
            let b = n % 6;
            let step = |v: u8| if v == 0 { 0 } else { 55 + 40 * v };
            format!("{:02x}{:02x}{:02x}", step(r), step(g), step(b))
        }
        _ => {
            let gray = 8 + 10 * (index - 232);
            format!("{gray:02x}{gray:02x}{gray:02x}")
        }
    }
}

fn color_to_pyte(color: Color) -> String {
    match color {
        Color::Named(name) => named_pyte(name).to_string(),
        Color::Indexed(index) => indexed_hex(index),
        Color::Spec(rgb) => format!("{:02x}{:02x}{:02x}", rgb.r, rgb.g, rgb.b),
    }
}

fn pack_flags(flags: Flags) -> u8 {
    let mut packed = 0u8;
    if flags.contains(Flags::BOLD) {
        packed |= FLAG_BOLD;
    }
    if flags.contains(Flags::ITALIC) {
        packed |= FLAG_ITALIC;
    }
    if flags.contains(Flags::UNDERLINE) || flags.contains(Flags::DOUBLE_UNDERLINE) {
        packed |= FLAG_UNDERLINE;
    }
    if flags.contains(Flags::STRIKEOUT) {
        packed |= FLAG_STRIKE;
    }
    if flags.contains(Flags::INVERSE) {
        packed |= FLAG_REVERSE;
    }
    packed
}

fn cell_tuple(cell: &Cell) -> (String, String, String, u8) {
    if cell.flags.contains(Flags::WIDE_CHAR_SPACER) {
        return (
            String::new(),
            color_to_pyte(cell.fg),
            color_to_pyte(cell.bg),
            pack_flags(cell.flags),
        );
    }
    let ch = if cell.c == '\0' { ' ' } else { cell.c };
    (
        ch.to_string(),
        color_to_pyte(cell.fg),
        color_to_pyte(cell.bg),
        pack_flags(cell.flags),
    )
}

type RowTuple = Vec<(String, String, String, u8)>;

#[pyclass(unsendable)]
pub struct NativeVte {
    term: Term<Bus>,
    parser: Processor,
    bus: Bus,
}

impl NativeVte {
    fn size(&self) -> (usize, usize) {
        (self.term.columns(), self.term.screen_lines())
    }

    fn dump_row(&self, abs_row: usize) -> RowTuple {
        let (cols, rows) = self.size();
        let hist = self.term.history_size();
        let blank = (
            " ".to_string(),
            "default".to_string(),
            "default".to_string(),
            0u8,
        );
        if abs_row >= hist + rows {
            return vec![blank; cols];
        }
        let line = Line(abs_row as i32 - hist as i32);
        let grid = self.term.grid();
        (0..cols)
            .map(|col| cell_tuple(&grid[line][Column(col)]))
            .collect()
    }
}

#[pymethods]
impl NativeVte {
    #[new]
    fn new(cols: u16, rows: u16, scrollback: usize) -> Self {
        let cols = cols.max(2) as usize;
        let rows = rows.max(2) as usize;
        let bus = Bus(Rc::new(RefCell::new(BusInner {
            title: String::new(),
            bell: false,
            writes: Vec::new(),
            cols: cols as u16,
            rows: rows as u16,
        })));
        let mut config = Config::default();
        config.scrolling_history = scrollback.max(200);
        let size = TermSize {
            columns: cols,
            screen_lines: rows,
        };
        let term = Term::new(config, &size, bus.clone());
        Self {
            term,
            parser: Processor::new(),
            bus,
        }
    }

    fn feed<'py>(&mut self, py: Python<'py>, data: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
        if !data.is_empty() {
            self.parser.advance(&mut self.term, data);
        }
            let writes = std::mem::take(&mut self.bus.0.borrow_mut().writes);
        Ok(PyBytes::new(py, &writes))
    }

    fn resize(&mut self, cols: u16, rows: u16) {
        let cols = cols.max(2) as usize;
        let rows = rows.max(2) as usize;
        {
            let mut inner = self.bus.0.borrow_mut();
            inner.cols = cols as u16;
            inner.rows = rows as u16;
        }
        self.term.resize(TermSize {
            columns: cols,
            screen_lines: rows,
        });
    }

    fn columns(&self) -> usize {
        self.term.columns()
    }

    fn lines(&self) -> usize {
        self.term.screen_lines()
    }

    fn history_len(&self) -> usize {
        self.term.history_size()
    }

    fn row(&self, abs_row: usize) -> RowTuple {
        self.dump_row(abs_row)
    }

    fn cursor(&self) -> (usize, usize, bool) {
        let point = self.term.grid().cursor.point;
        let hidden = !self.term.mode().contains(TermMode::SHOW_CURSOR);
        (point.column.0, point.line.0.max(0) as usize, hidden)
    }

    fn app_cursor(&self) -> bool {
        self.term.mode().contains(TermMode::APP_CURSOR)
    }

    fn bracketed_paste(&self) -> bool {
        self.term.mode().contains(TermMode::BRACKETED_PASTE)
    }

    fn title(&self) -> String {
        self.bus.0.borrow().title.clone()
    }

    fn take_bell(&self) -> bool {
        let mut inner = self.bus.0.borrow_mut();
        let bell = inner.bell;
        inner.bell = false;
        bell
    }
}
