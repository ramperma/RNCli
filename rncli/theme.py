"""Paletas de color para la terminal y el chasis de la aplicación."""

from __future__ import annotations

from PySide6.QtGui import QColor

#: Colores ANSI (nombres que usa pyte) mapeados a cada tema.
#: Además de fg/bg de la terminal, cada paleta define el chasis:
#: surface, raised, muted, hover, danger, on_accent.
THEMES: dict[str, dict[str, str]] = {
    "oscuro": {
        "bg": "#0d1117",
        "fg": "#e6edf3",
        "cursor": "#58a6ff",
        "selection": "#264f78",
        "border": "#30363d",
        "header_bg": "#161b22",
        "header_fg": "#8b949e",
        "accent": "#58a6ff",
        "surface": "#161b22",
        "raised": "#21262d",
        "muted": "#8b949e",
        "hover": "#30363d",
        "danger": "#f85149",
        "on_accent": "#0d1117",
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
        "border": "#3d4055",
        "header_bg": "#21222c",
        "header_fg": "#bdc0d0",
        "accent": "#bd93f9",
        "surface": "#21222c",
        "raised": "#2b2c3b",
        "muted": "#6272a4",
        "hover": "#3b3d51",
        "danger": "#ff5555",
        "on_accent": "#1e1f29",
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
        "surface": "#f6f8fa",
        "raised": "#ffffff",
        "muted": "#656d76",
        "hover": "#eaeef2",
        "danger": "#cf222e",
        "on_accent": "#ffffff",
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
    "modern_dark": {
        "bg": "#0f1014",
        "fg": "#eceef2",
        "cursor": "#a8b4ff",
        "selection": "#2a3358",
        "border": "#2a2c36",
        "header_bg": "#16171d",
        "header_fg": "#9aa0ae",
        "accent": "#8ba0ff",
        "surface": "#16171d",
        "raised": "#1c1e27",
        "muted": "#8b909c",
        "hover": "#262833",
        "danger": "#f07178",
        "on_accent": "#0f1014",
        "black": "#111218",
        "red": "#f07178",
        "green": "#7fd99a",
        "brown": "#e0b089",
        "blue": "#82b4ff",
        "magenta": "#d4a0e0",
        "cyan": "#7ec8d4",
        "white": "#e6e7ea",
        "brightblack": "#6b7080",
        "brightred": "#ff8b90",
        "brightgreen": "#97e8b0",
        "brightbrown": "#f0c6a0",
        "brightblue": "#a8c8ff",
        "brightmagenta": "#e6b8ee",
        "brightcyan": "#9adce6",
        "brightwhite": "#ffffff",
    },
}

THEME_LABELS = {
    "oscuro": "Oscuro",
    "dracula": "Dracula",
    "claro": "Claro",
    "modern_dark": "Grafito",
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
    """Hoja de estilo del chasis. No pinta QToolButton genéricos: si no,
    los botones de cerrar pestaña y de la cabecera del panel se solapan."""
    pal = theme(name)
    surface = pal.get("surface", pal["header_bg"])
    raised = pal.get("raised", pal["bg"])
    muted = pal.get("muted", pal["header_fg"])
    hover = pal.get("hover", pal["selection"])
    danger = pal.get("danger", pal["red"])
    on_accent = pal.get("on_accent", pal["bg"])
    return f"""
    QMainWindow, QDialog {{
        background: {pal['bg']};
        color: {pal['fg']};
    }}
    QWidget {{
        color: {pal['fg']};
        font-size: 13px;
    }}
    QToolTip {{
        background: {raised};
        color: {pal['fg']};
        border: 1px solid {pal['border']};
        padding: 6px 10px;
        border-radius: 6px;
    }}

    QLabel#Hint, QLabel#PaneStatus, QLabel#PanePath, QLabel#PromptHint,
    QLabel#FileBrowserSelection {{
        color: {muted};
    }}
    QLabel#FileBrowserTitle {{
        color: {pal['fg']};
        font-weight: 600;
        font-size: 13px;
        letter-spacing: 0.2px;
    }}
    QLabel#Placeholder {{
        color: {muted};
        font-size: 14px;
    }}

    QMenuBar {{
        background: {surface};
        border-bottom: 1px solid {pal['border']};
        padding: 3px 8px;
        spacing: 2px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 5px 10px;
        border-radius: 6px;
    }}
    QMenuBar::item:selected {{
        background: {hover};
        color: {pal['fg']};
    }}
    QMenu {{
        background: {surface};
        border: 1px solid {pal['border']};
        padding: 6px;
    }}
    QMenu::item {{
        padding: 6px 22px 6px 14px;
        border-radius: 5px;
    }}
    QMenu::item:selected {{
        background: {pal['accent']};
        color: {on_accent};
    }}
    QMenu::separator {{
        height: 1px;
        background: {pal['border']};
        margin: 6px 8px;
    }}

    QToolBar {{
        background: {surface};
        border: none;
        border-bottom: 1px solid {pal['border']};
        spacing: 8px;
        padding: 7px 12px;
    }}
    QToolBar::separator {{
        background: {pal['border']};
        width: 1px;
        margin: 6px 4px;
    }}

    QToolButton#ChromeButton, QToolButton#SegmentButton, QToolButton#IconButton {{
        background: {raised};
        color: {pal['fg']};
        border: 1px solid {pal['border']};
        border-radius: 7px;
    }}
    QToolButton#ChromeButton {{
        padding: 6px 12px;
        min-height: 20px;
    }}
    QToolButton#IconButton {{
        padding: 0px;
        min-width: 30px;
        min-height: 30px;
    }}
    QToolButton#ChromeButton:hover, QToolButton#IconButton:hover,
    QToolButton#SegmentButton:hover {{
        border-color: {pal['accent']};
        background: {hover};
    }}
    QToolButton#ChromeButton:checked, QToolButton#SegmentButton:checked,
    QToolButton#IconButton:checked {{
        background: {pal['accent']};
        color: {on_accent};
        border-color: {pal['accent']};
    }}
    QToolButton#PaneButton {{
        background: transparent;
        border: none;
        border-radius: 5px;
        padding: 0px;
        min-width: 24px;
        max-width: 24px;
        min-height: 24px;
        max-height: 24px;
        color: {muted};
    }}
    QToolButton#PaneButton:hover {{
        background: {hover};
        color: {pal['fg']};
    }}
    QToolButton#PaneClose {{
        background: transparent;
        border: none;
        border-radius: 5px;
        padding: 0px;
        min-width: 24px;
        max-width: 24px;
        min-height: 24px;
        max-height: 24px;
        color: {muted};
    }}
    QToolButton#PaneClose:hover {{
        background: {danger};
        color: {on_accent};
    }}

    QWidget#LayoutSegment {{
        background: {raised};
        border: 1px solid {pal['border']};
        border-radius: 8px;
    }}
    QLabel#LayoutCaption {{
        color: {muted};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.4px;
        padding: 0 2px 0 4px;
    }}
    QToolButton#SegmentButton {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 6px 11px;
        min-width: 22px;
        min-height: 20px;
    }}

    QTabWidget::pane {{
        border: none;
        background: {pal['bg']};
        top: 0px;
    }}
    QTabBar {{
        background: {surface};
        qproperty-drawBase: 0;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {muted};
        padding: 8px 18px 8px 14px;
        min-height: 20px;
        border: none;
        border-bottom: 2px solid transparent;
        margin: 0px 2px;
    }}
    QTabBar::tab:selected {{
        color: {pal['fg']};
        border-bottom: 2px solid {pal['accent']};
        background: {pal['bg']};
    }}
    QTabBar::tab:hover:!selected {{
        color: {pal['fg']};
        background: {hover};
    }}
    QTabBar::close-button {{
        subcontrol-position: right;
        subcontrol-origin: padding;
        width: 14px;
        height: 14px;
        margin: 2px 6px 2px 4px;
        background: transparent;
        border: none;
        padding: 0px;
    }}
    QTabBar::close-button:hover {{
        background: {danger};
        border-radius: 3px;
    }}

    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextBrowser, QFontComboBox {{
        background: {raised};
        color: {pal['fg']};
        border: 1px solid {pal['border']};
        border-radius: 7px;
        padding: 6px 8px;
        min-height: 18px;
        selection-background-color: {pal['selection']};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
        border-color: {pal['accent']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}

    QPushButton {{
        background: {raised};
        color: {pal['fg']};
        border: 1px solid {pal['border']};
        border-radius: 7px;
        padding: 7px 14px;
        min-height: 20px;
    }}
    QPushButton:hover {{
        border-color: {pal['accent']};
        background: {hover};
    }}
    QPushButton:disabled {{
        color: {muted};
        border-color: {pal['border']};
    }}
    QPushButton:default, QPushButton#PrimaryButton {{
        background: {pal['accent']};
        color: {on_accent};
        border-color: {pal['accent']};
    }}
    QPushButton:default:hover, QPushButton#PrimaryButton:hover {{
        background: {pal['accent']};
    }}
    QToolButton#AgentButton {{
        text-align: left;
        padding: 10px 12px;
        background: {raised};
        color: {pal['fg']};
        border: 1px solid {pal['border']};
        border-radius: 8px;
    }}
    QToolButton#AgentButton:hover {{
        border-color: {pal['accent']};
        background: {hover};
    }}
    QToolButton#AgentButton[missing="true"] {{
        color: {muted};
        border-style: dashed;
    }}

    QTreeView {{
        background: {raised};
        color: {pal['fg']};
        border: 1px solid {pal['border']};
        border-radius: 8px;
        alternate-background-color: {surface};
        padding: 4px;
    }}
    QTreeView::item {{
        padding: 4px 2px;
        border-radius: 4px;
    }}
    QTreeView::item:selected {{
        background: {pal['selection']};
        color: {pal['fg']};
    }}
    QTreeView::item:hover {{
        background: {hover};
    }}

    QDockWidget {{
        color: {pal['fg']};
        border: none;
    }}
    QDockWidget::title {{
        background: {surface};
        padding: 8px 12px;
        border-bottom: 1px solid {pal['border']};
        text-align: left;
    }}

    QStatusBar {{
        background: {surface};
        color: {muted};
        border-top: 1px solid {pal['border']};
        min-height: 22px;
        padding: 2px 8px;
    }}
    QStatusBar QLabel {{
        color: {muted};
        padding: 0 4px;
    }}

    QSplitter::handle {{
        background: {pal['bg']};
    }}
    QSplitter::handle:horizontal {{
        width: 8px;
    }}
    QSplitter::handle:vertical {{
        height: 8px;
    }}
    QSplitter::handle:hover {{
        background: {pal['accent']};
    }}

    QCheckBox {{
        spacing: 8px;
        padding: 2px 0;
    }}
    QGroupBox {{
        border: 1px solid {pal['border']};
        border-radius: 8px;
        margin-top: 12px;
        padding: 12px 10px 8px 10px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: {pal['fg']};
    }}

    QScrollBar:vertical {{
        background: {pal['bg']};
        width: 11px;
        margin: 2px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {pal['border']};
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {muted};
    }}
    QScrollBar:horizontal {{
        background: {pal['bg']};
        height: 11px;
        margin: 2px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background: {pal['border']};
        border-radius: 5px;
        min-width: 24px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        width: 0;
        height: 0;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent;
    }}

    QWidget#PromptContainer {{
        background: {surface};
        border-top: 1px solid {pal['border']};
    }}
    QWidget#PromptContainer[hostMode="true"] {{
        background: {hover};
        border-top: 2px solid {pal['accent']};
    }}
    QLabel#PromptIcon {{
        color: {pal['green']};
        font-weight: 600;
        font-size: 15px;
        padding: 0 2px;
    }}
    QLineEdit#PromptBar {{
        background: {raised};
        color: {pal['fg']};
        border: 1px solid {pal['border']};
        border-radius: 8px;
        padding: 8px 12px;
        font-family: monospace;
        font-size: 13px;
    }}
    QLineEdit#PromptBar:focus {{
        border-color: {pal['accent']};
    }}
    QLineEdit#PromptBar[hostMode="true"] {{
        border-color: {pal['accent']};
    }}

    QFrame#Pane {{
        border: 1px solid {pal['border']};
        border-radius: 8px;
        background: {pal['bg']};
    }}
    """
