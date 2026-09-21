"""Paletas de color para la terminal y el chasis de la aplicación."""

from __future__ import annotations

from PySide6.QtGui import QColor

#: Colores ANSI (nombres que usa pyte) mapeados a cada tema.
THEMES: dict[str, dict[str, str]] = {
    "oscuro": {
        "bg": "#0d1117",
        "fg": "#c9d1d9",
        "cursor": "#58a6ff",
        "selection": "#264f78",
        "border": "#30363d",
        "header_bg": "#161b22",
        "header_fg": "#8b949e",
        "accent": "#58a6ff",
        "black": "#484f58",
        "red": "#ff7b72",
        "green": "#3fb950",
        "brown": "#d29922",
        "blue": "#58a6ff",
        "magenta": "#bc8cff",
        "cyan": "#39c5cf",
        "white": "#b1bac4",
        "brightblack": "#6e7681",
        "brightred": "#ffa198",
        "brightgreen": "#56d364",
        "brightbrown": "#e3b341",
        "brightblue": "#79c0ff",
        "brightmagenta": "#d2a8ff",
        "brightcyan": "#56d4dd",
        "brightwhite": "#f0f6fc",
    },
    "dracula": {
        "bg": "#282a36",
        "fg": "#f8f8f2",
        "cursor": "#f8f8f2",
        "selection": "#44475a",
        "border": "#44475a",
        "header_bg": "#21222c",
        "header_fg": "#bdc0d0",
        "accent": "#bd93f9",
        "black": "#21222c",
        "red": "#ff5555",
        "green": "#50fa7b",
        "brown": "#f1fa8c",
        "blue": "#8be9fd",
        "magenta": "#ff79c6",
        "cyan": "#8be9fd",
        "white": "#f8f8f2",
        "brightblack": "#6272a4",
        "brightred": "#ff6e6e",
        "brightgreen": "#69ff94",
        "brightbrown": "#ffffa5",
        "brightblue": "#d6acff",
        "brightmagenta": "#ff92df",
        "brightcyan": "#a4ffff",
        "brightwhite": "#ffffff",
    },
    "claro": {
        "bg": "#ffffff",
        "fg": "#1f2328",
        "cursor": "#0969da",
        "selection": "#b6d7ff",
        "border": "#d0d7de",
        "header_bg": "#f6f8fa",
        "header_fg": "#57606a",
        "accent": "#0969da",
        "black": "#24292f",
        "red": "#cf222e",
        "green": "#116329",
        "brown": "#953800",
        "blue": "#0969da",
        "magenta": "#8250df",
        "cyan": "#1b7c83",
        "white": "#6e7781",
        "brightblack": "#57606a",
        "brightred": "#a40e26",
        "brightgreen": "#1a7f37",
        "brightbrown": "#9a6700",
        "brightblue": "#218bff",
        "brightmagenta": "#a475f9",
        "brightcyan": "#3192aa",
        "brightwhite": "#8c959f",
    },
}

THEME_LABELS = {
    "oscuro": "Oscuro (GitHub)",
    "dracula": "Dracula",
    "claro": "Claro",
}

#: Nombres de color que emite pyte -> clave de la paleta.
PYTE_COLOR_KEYS = {
    "black", "red", "green", "brown", "blue", "magenta", "cyan", "white",
    "brightblack", "brightred", "brightgreen", "brightbrown",
    "brightblue", "brightmagenta", "brightcyan", "brightwhite",
}


def theme(name: str) -> dict[str, str]:
    return THEMES.get(name, THEMES["oscuro"])


def resolve_color(value, pal: dict[str, str], default_key: str) -> QColor:
    """Convierte un color de pyte ('default', 'red', 'ff8700'...) en QColor."""
    if not value or value == "default":
        return QColor(pal[default_key])
    if value in PYTE_COLOR_KEYS:
        return QColor(pal.get(value, pal[default_key]))
    text = str(value)
    if len(text) == 6:
        text = "#" + text
    color = QColor(text)
    return color if color.isValid() else QColor(pal[default_key])


def brighten(color: QColor) -> QColor:
    """Aclara un color (se usa para 'bold' cuando el tema no define negrita)."""
    return color.lighter(135)


def app_stylesheet(name: str) -> str:
    """Hoja de estilo global del chasis (Qt) para el tema elegido."""
    pal = theme(name)
    return f"""
    QMainWindow, QDialog {{ background: {pal['bg']}; color: {pal['fg']}; }}
    QWidget {{ color: {pal['fg']}; font-size: 13px; }}
    QLabel#Hint, QLabel#PaneStatus {{ color: {pal['brightblack']}; }}
    QLabel#FileBrowserTitle {{ color: {pal['fg']}; font-weight: 600; }}
    QLabel#FileBrowserSelection {{ color: {pal['brightblack']}; padding: 3px; }}
    QToolBar {{ background: {pal['header_bg']}; border-bottom: 1px solid {pal['border']}; spacing: 6px; padding: 4px; }}
    QToolButton, QPushButton {{ background: {pal['header_bg']}; color: {pal['fg']};
        border: 1px solid {pal['border']}; border-radius: 5px; padding: 4px 10px; }}
    QToolButton:hover, QPushButton:hover {{ border-color: {pal['accent']}; }}
    QToolButton:checked, QPushButton:checked {{ background: {pal['accent']}; color: {pal['bg']}; }}
    QToolButton#AgentButton {{ text-align: left; padding: 8px 10px; }}
    QToolButton#AgentButton[missing="true"] {{ color: {pal['brightblack']}; border-style: dashed; }}
    QTabBar::tab {{ background: {pal['header_bg']}; color: {pal['header_fg']};
        padding: 6px 14px; border: 1px solid {pal['border']}; border-bottom: none;
        border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
    QTabBar::tab:selected {{ background: {pal['bg']}; color: {pal['fg']}; border-bottom: 2px solid {pal['accent']}; }}
    QTabWidget::pane {{ border: 1px solid {pal['border']}; }}
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextBrowser, QFontComboBox {{
        background: {pal['header_bg']}; color: {pal['fg']};
        border: 1px solid {pal['border']}; border-radius: 5px; padding: 4px 6px; }}
    QTreeView {{ background: {pal['header_bg']}; color: {pal['fg']};
        border: 1px solid {pal['border']}; border-radius: 5px; alternate-background-color: {pal['bg']}; }}
    QTreeView::item {{ padding: 3px 2px; }}
    QTreeView::item:selected {{ background: {pal['selection']}; color: {pal['fg']}; }}
    QTreeView::item:hover {{ background: {pal['selection']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border-color: {pal['accent']}; }}
    QStatusBar {{ background: {pal['header_bg']}; color: {pal['header_fg']}; }}
    QMenuBar {{ background: {pal['header_bg']}; }}
    QMenuBar::item:selected, QMenu::item:selected {{ background: {pal['accent']}; color: {pal['bg']}; }}
    QMenu {{ background: {pal['header_bg']}; border: 1px solid {pal['border']}; }}
    QSplitter::handle {{ background: {pal['border']}; }}
    QCheckBox {{ spacing: 6px; }}
    QScrollBar:vertical {{ background: {pal['bg']}; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {pal['border']}; border-radius: 5px; min-height: 20px; }}
    """
