"""Visual language: palette tokens and the application stylesheet.

Dark-first, deep charcoal rather than pure black, with a single vivid accent
(electric blue, taken from the app mark) reserved for interactive and active
states. The semantic colours for confidence badges are deliberately kept out
of the blue family so an accent-coloured control is never mistaken for a
status signal.
"""
from __future__ import annotations

# --- Palette ---------------------------------------------------------------
BG_DEEP = "#121317"        # window background
BG_SURFACE = "#191B21"     # panels
BG_ELEVATED = "#21242C"    # cards
BG_HOVER = "#282C36"
BG_INPUT = "#0E0F13"

BORDER = "#2C3038"
BORDER_STRONG = "#3A404B"

TEXT = "#E8EAED"
TEXT_MUTED = "#9BA1AC"
TEXT_DIM = "#6B7280"

# Sampled from the app mark: its neon core sits around #0030C0, lifted here
# for legibility against the charcoal background.
ACCENT = "#2A6BFF"
ACCENT_BRIGHT = "#6FA0FF"
ACCENT_DEEP = "#1B4FD8"
ACCENT_WASH = "rgba(42, 107, 255, 0.16)"

OK = "#22C55E"             # confident match
OK_WASH = "rgba(34, 197, 94, 0.14)"
WARN = "#F59E0B"           # uncertain match
WARN_WASH = "rgba(245, 158, 11, 0.14)"
DANGER = "#EF4444"
DANGER_WASH = "rgba(239, 68, 68, 0.14)"
IDLE = "#6E7480"           # unassigned
IDLE_WASH = "rgba(110, 116, 128, 0.14)"

RADIUS = 10
RADIUS_SM = 7

FONT_STACK = '"Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif'
MONO_STACK = '"Cascadia Mono", "Consolas", monospace'


STYLESHEET = f"""
* {{
    font-family: {FONT_STACK};
    color: {TEXT};
}}

QWidget#Root {{
    background: {BG_DEEP};
    border: 1px solid {BORDER_STRONG};
    border-radius: 12px;
}}

QWidget#Screen {{ background: transparent; }}

/* ---- Title bar ---- */
QWidget#TitleBar {{
    background: transparent;
    border-bottom: 1px solid {BORDER};
}}
QLabel#TitleText {{
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.2px;
}}
QLabel#TitleDot {{
    font-size: 15px;
    color: {ACCENT};
}}
QPushButton#WinBtn {{
    background: transparent;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    color: {TEXT_MUTED};
    padding: 0px;
}}
QPushButton#WinBtn:hover {{ background: {BG_HOVER}; color: {TEXT}; }}
QPushButton#WinBtnClose:hover {{ background: {DANGER}; color: #fff; }}

/* ---- Navigation rail ---- */
QWidget#NavRail {{
    background: {BG_SURFACE};
    border-right: 1px solid {BORDER};
}}
QPushButton#NavItem {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_SM}px;
    padding: 9px 14px;
    text-align: left;
    font-size: 12.5px;
    font-weight: 500;
    color: {TEXT_MUTED};
}}
QPushButton#NavItem:hover:!checked {{ background: {BG_HOVER}; color: {TEXT}; }}
QPushButton#NavItem:checked {{
    background: {ACCENT_WASH};
    color: {ACCENT_BRIGHT};
    font-weight: 600;
}}
QPushButton#NavItem:disabled {{ color: {TEXT_DIM}; }}
QLabel#NavStep {{
    color: {TEXT_DIM};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.2px;
    padding: 14px 14px 6px 14px;
}}

/* ---- Typography ---- */
QLabel#H1 {{ font-size: 25px; font-weight: 650; letter-spacing: -0.4px; }}
QLabel#H2 {{ font-size: 16px; font-weight: 600; }}
QLabel#Sub {{ font-size: 12.5px; color: {TEXT_MUTED}; }}
QLabel#Dim {{ font-size: 11.5px; color: {TEXT_DIM}; }}
QLabel#Mono {{ font-family: {MONO_STACK}; font-size: 11px; color: {TEXT_MUTED}; }}

/* ---- Buttons ---- */
QPushButton {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 8px 16px;
    font-size: 12.5px;
    font-weight: 550;
}}
QPushButton:hover {{ background: {BG_HOVER}; border-color: {BORDER_STRONG}; }}
QPushButton:pressed {{ background: {BG_SURFACE}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; background: {BG_SURFACE}; }}

QPushButton#Primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #FFFFFF;
    font-weight: 600;
    padding: 9px 20px;
}}
QPushButton#Primary:hover {{ background: {ACCENT_BRIGHT}; border-color: {ACCENT_BRIGHT}; }}
QPushButton#Primary:pressed {{ background: {ACCENT_DEEP}; }}
QPushButton#Primary:disabled {{
    background: {BG_ELEVATED}; border-color: {BORDER}; color: {TEXT_DIM};
}}

QPushButton#Ghost {{ background: transparent; border: 1px solid {BORDER}; }}
QPushButton#Ghost:hover {{ background: {BG_HOVER}; }}

QPushButton#Danger {{ color: {DANGER}; border-color: rgba(239,68,68,0.35); background: transparent; }}
QPushButton#Danger:hover {{ background: {DANGER_WASH}; }}

QPushButton#Link {{
    background: transparent; border: none; color: {ACCENT_BRIGHT};
    padding: 4px 6px; font-size: 12px; text-align: left;
}}
QPushButton#Link:hover {{ color: {TEXT}; }}

/* ---- Cards ---- */
QFrame#Card {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QFrame#Panel {{
    background: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}

/* ---- Inputs ---- */
QLineEdit {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 8px 11px;
    font-size: 12.5px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled {{ color: {TEXT_DIM}; }}

QComboBox {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 6px 10px;
    font-size: 12px;
}}
QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS_SM}px;
    selection-background-color: {ACCENT_WASH};
    selection-color: {ACCENT_BRIGHT};
    padding: 4px;
    outline: none;
}}

QCheckBox {{ font-size: 12px; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QSlider::groove:horizontal {{
    height: 4px; background: {BORDER}; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT}; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background: {ACCENT_DEEP}; border-radius: 2px; }}

/* ---- Scroll ---- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {BORDER_STRONG}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* ---- Progress ---- */
QProgressBar {{
    background: {BG_INPUT};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

/* ---- Dialogs ---- */
QDialog {{ background: {BG_SURFACE}; }}
QMessageBox {{ background: {BG_SURFACE}; }}
QMessageBox QLabel {{ font-size: 12.5px; }}

QToolTip {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 6px 9px;
    color: {TEXT};
    font-size: 11.5px;
}}

QMenu {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS_SM}px;
    padding: 5px;
}}
QMenu::item {{
    padding: 7px 22px 7px 12px;
    border-radius: 5px;
    font-size: 12px;
}}
QMenu::item:selected {{ background: {ACCENT_WASH}; color: {ACCENT_BRIGHT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
"""
