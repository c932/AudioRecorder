"""
Design tokens & shared styles for the English Pronunciation Coach.

Design language: "storybook desk" — a calm paper workspace where the parrot
mascot coaches the child. Warm off-white paper, one mango accent, leaf/clay
reserved for right/wrong outcomes. One font (Nunito), one radius (12px),
one 8px spacing grid.

Centralize all visual decisions here so the 10+ page files stop drifting.
Page files should reference AppStyles.* constants instead of inline hex.
"""
from PyQt6.QtGui import QFont, QFontDatabase
from src.utils import get_resource_path
import os

# ──────────────────────────────────────────────────────────────────────
# Font registration — Nunito (rounded, early-reader friendly), bundled.
# Falls back to system rounded sans / Segoe UI if the file is missing.
# ──────────────────────────────────────────────────────────────────────
_FONT_LOADED = False
FONT_FAMILY = "Nunito"
FONT_FALLBACK = "'Nunito', 'Segoe UI', 'Microsoft YaHei', sans-serif"


def load_fonts():
    """Load bundled Nunito. Call once at app startup (after QApplication)."""
    global _FONT_LOADED
    if _FONT_LOADED:
        return
    path = get_resource_path(os.path.join("src", "resources", "fonts", "Nunito-variable.ttf"))
    if os.path.exists(path):
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id != -1:
            _FONT_LOADED = True
            return
    # Graceful fallback: app still runs with system sans.
    _FONT_LOADED = False


def app_font(point_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Build a QFont on the registered family with a safe fallback."""
    f = QFont(FONT_FAMILY, point_size, weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


# ──────────────────────────────────────────────────────────────────────
# Color tokens
#   paper / desk  — the worksheet surface (warm off-white + deeper panel)
#   ink / ink-soft — text (warm near-black, not #000)
#   mango         — the ONE accent (CTAs, active, the parrot's energy)
#   leaf / clay   — outcome-only (correct / wrong). Never navigation.
# ──────────────────────────────────────────────────────────────────────
PAPER     = "#F4F1E8"   # page background — warm worksheet paper
DESK      = "#E8E4D5"   # cards / panels — slightly deeper paper
DESK_LINE = "#D9D3C2"   # hairline border on paper cards
INK       = "#2B2A26"   # primary text — warm near-black
INK_SOFT  = "#6B6960"   # secondary text / metadata
MANGO     = "#F2A736"   # the one accent — beak & feathers, "go"
MANGO_DK  = "#D88A1E"   # accent hover / press
LEAF      = "#5B8A5A"   # correct / success — calm green
LEAF_SOFT = "#DCE7D8"   # correct background tint
CLAY      = "#C76B5A"   # wrong / error — warm clay, not alarm red
CLAY_SOFT = "#F0D9D2"   # wrong background tint


# ──────────────────────────────────────────────────────────────────────
# Type scale (1.25 ratio) — sizes in px, weights as role
#   body 13 · secondary 13 · ui 16 · title 20 · section 25 · header 31
#   The word card breaks scale at 56 — the word IS the hero.
# ──────────────────────────────────────────────────────────────────────
SIZE_BODY    = 13
SIZE_UI      = 16
SIZE_TITLE   = 20
SIZE_SECTION = 25
SIZE_HEADER  = 31
SIZE_WORD    = 56     # practice word card — the hero
SIZE_PHON    = 24     # phonetic transcription
SIZE_SCORE   = 39     # score number


# ──────────────────────────────────────────────────────────────────────
# Spacing — 8px grid
# ──────────────────────────────────────────────────────────────────────
SP_1 = 4
SP_2 = 8
SP_3 = 16
SP_4 = 24
SP_5 = 32
RADIUS      = 12   # one radius for cards & buttons
RADIUS_SM   = 8    # inputs, chips, small controls
RADIUS_ROUND = 999 # record button (physical mic) — the single exception


class AppStyles:
    """Shared QSS strings. Pages reference these instead of inlining hex."""

    # ── Surfaces ────────────────────────────────────────────────────
    MAIN_WINDOW_BG = f"background-color: {PAPER};"

    PAGE_PADDING = f"padding: {SP_5}px;"

    # ── Text ────────────────────────────────────────────────────────
    HEADER_LABEL = f"""
        font-family: {FONT_FALLBACK};
        font-size: {SIZE_HEADER}px;
        font-weight: 800;
        color: {INK};
        letter-spacing: -0.5px;
    """

    SECTION_LABEL = f"""
        font-family: {FONT_FALLBACK};
        font-size: {SIZE_SECTION}px;
        font-weight: 700;
        color: {INK};
    """

    TITLE_LABEL = f"""
        font-family: {FONT_FALLBACK};
        font-size: {SIZE_TITLE}px;
        font-weight: 700;
        color: {INK};
    """

    BODY_LABEL = f"""
        font-family: {FONT_FALLBACK};
        font-size: {SIZE_BODY}px;
        font-weight: 400;
        color: {INK_SOFT};
    """

    SUBTITLE_LABEL = f"""
        font-family: {FONT_FALLBACK};
        font-size: {SIZE_BODY}px;
        font-weight: 400;
        color: {INK_SOFT};
    """

    # ── Buttons ─────────────────────────────────────────────────────
    # Primary CTA — mango, the one accent. Used for the main forward action.
    BIG_BUTTON = f"""
        QPushButton {{
            background-color: {MANGO};
            color: {INK};
            border: none;
            border-radius: {RADIUS}px;
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_UI}px;
            font-weight: 700;
            padding: {SP_3}px {SP_4}px;
            min-width: 200px;
        }}
        QPushButton:hover {{ background-color: {MANGO_DK}; }}
        QPushButton:pressed {{ background-color: {MANGO_DK}; }}
        QPushButton:disabled {{ background-color: {DESK}; color: {INK_SOFT}; }}
    """

    # Secondary button — paper card with ink text, for non-primary actions.
    CARD_BUTTON = f"""
        QPushButton {{
            background-color: {DESK};
            color: {INK};
            border: 1px solid {DESK_LINE};
            border-radius: {RADIUS}px;
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_UI}px;
            font-weight: 600;
            padding: {SP_2}px {SP_3}px;
        }}
        QPushButton:hover {{ background-color: #D9D3C2; border-color: #C8C0AB; }}
        QPushButton:pressed {{ background-color: #C8C0AB; }}
        QPushButton:disabled {{ color: {INK_SOFT}; }}
    """

    # Ghost / back button — transparent, ink-soft, for navigation chrome.
    GHOST_BUTTON = f"""
        QPushButton {{
            background: transparent;
            color: {INK_SOFT};
            border: none;
            border-radius: {RADIUS_SM}px;
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_BODY}px;
            font-weight: 600;
            padding: {SP_1}px {SP_2}px;
        }}
        QPushButton:hover {{ background-color: {DESK}; color: {INK}; }}
    """

    # ── Record button — the one round element (physical mic metaphor) ─
    RECORD_BUTTON_IDLE = f"""
        QPushButton {{
            background-color: {MANGO};
            border: none;
            border-radius: {RADIUS_ROUND}px;
            font-family: {FONT_FALLBACK};
            font-size: 28px;
        }}
        QPushButton:hover {{ background-color: {MANGO_DK}; }}
    """

    RECORD_BUTTON_ACTIVE = f"""
        QPushButton {{
            background-color: {CLAY};
            border: none;
            border-radius: {RADIUS_ROUND}px;
            font-family: {FONT_FALLBACK};
            font-size: 28px;
        }}
        QPushButton:hover {{ background-color: #B05A4A; }}
    """

    # ── Practice word card — the hero ───────────────────────────────
    WORD_DISPLAY = f"""
        font-family: {FONT_FALLBACK};
        font-size: {SIZE_WORD}px;
        font-weight: 800;
        color: {INK};
        letter-spacing: -1px;
    """

    PHONETIC_DISPLAY = f"""
        font-family: {FONT_FALLBACK};
        font-size: {SIZE_PHON}px;
        font-weight: 400;
        color: {INK_SOFT};
    """

    # ── Inputs ──────────────────────────────────────────────────────
    INPUT = f"""
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {{
            background-color: #FBFAF5;
            color: {INK};
            border: 1px solid {DESK_LINE};
            border-radius: {RADIUS_SM}px;
            padding: {SP_2}px {SP_3}px;
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_UI}px;
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
            border-color: {MANGO};
        }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
    """

    # ── Progress bar ────────────────────────────────────────────────
    PROGRESS_BAR = f"""
        QProgressBar {{
            background-color: {DESK};
            border: none;
            border-radius: {RADIUS_SM}px;
            text-align: center;
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_BODY}px;
            color: {INK};
            min-height: 18px;
        }}
        QProgressBar::chunk {{
            background-color: {MANGO};
            border-radius: {RADIUS_SM}px;
        }}
    """

    # ── Home module cards — paper cards, ink text, one accent border ─
    @staticmethod
    def MODULE_CARD(active: bool = False) -> str:
        border = f"border-left: 4px solid {MANGO};" if active else f"border: 1px solid {DESK_LINE};"
        return f"""
            QPushButton {{
                background-color: {DESK};
                color: {INK};
                {border}
                border-top-left-radius: {RADIUS}px;
                border-top-right-radius: {RADIUS}px;
                border-bottom-left-radius: {RADIUS}px;
                border-bottom-right-radius: {RADIUS}px;
                font-family: {FONT_FALLBACK};
                font-size: {SIZE_TITLE}px;
                font-weight: 700;
                padding: {SP_4}px {SP_3}px;
                text-align: left;
            }}
            QPushButton:hover {{ background-color: #DDD7C6; }}
            QPushButton:pressed {{ background-color: #CFC8B5; }}
        """

    # ── Quiz / choice options ───────────────────────────────────────
    QUIZ_OPTION_BUTTON = f"""
        QPushButton {{
            background-color: #FBFAF5;
            color: {INK};
            border: 1px solid {DESK_LINE};
            border-radius: {RADIUS}px;
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_UI}px;
            font-weight: 400;
            padding: {SP_3}px;
            text-align: left;
        }}
        QPushButton:hover {{ border-color: {MANGO}; background-color: #FBF6EC; }}
    """

    QUIZ_CORRECT = f"""
        QPushButton {{
            background-color: {LEAF_SOFT};
            border: 1px solid {LEAF};
            color: {LEAF};
            border-radius: {RADIUS}px;
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_UI}px;
            font-weight: 700;
            padding: {SP_3}px;
            text-align: left;
        }}
    """

    QUIZ_WRONG = f"""
        QPushButton {{
            background-color: {CLAY_SOFT};
            border: 1px solid {CLAY};
            color: {CLAY};
            border-radius: {RADIUS}px;
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_UI}px;
            font-weight: 700;
            padding: {SP_3}px;
            text-align: left;
        }}
    """

    QUIZ_INPUT = f"""
        QLineEdit {{
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_TITLE}px;
            padding: {SP_3}px;
            border: 1px solid {DESK_LINE};
            border-radius: {RADIUS}px;
            background-color: #FBFAF5;
            color: {INK};
        }}
        QLineEdit:focus {{ border-color: {MANGO}; }}
    """

    QUIZ_PROGRESS_BAR = PROGRESS_BAR

    # ── Scroll areas — quiet, paper-on-paper ────────────────────────
    SCROLL_AREA = f"""
        QScrollArea {{ border: none; background: transparent; }}
        QScrollBar:vertical {{
            background: transparent; width: 10px; margin: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {DESK_LINE}; border-radius: 5px; min-height: 32px;
        }}
        QScrollBar::handle:vertical:hover {{ background: #C8C0AB; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """

    # ── Cards (info panels, result rows) ────────────────────────────
    CARD = f"""
        QFrame {{
            background-color: {DESK};
            border: 1px solid {DESK_LINE};
            border-radius: {RADIUS}px;
        }}
    """

    # Result row with a left color bar — the bar encodes score tier.
    @staticmethod
    def RESULT_ROW(bar_color: str) -> str:
        return f"""
            QFrame {{
                background-color: #FBFAF5;
                border: 1px solid {DESK_LINE};
                border-left: 5px solid {bar_color};
                border-radius: {RADIUS}px;
            }}
        """

    # ── Tables ──────────────────────────────────────────────────────
    TABLE = f"""
        QTableWidget {{
            background-color: #FBFAF5;
            alternate-background-color: {DESK};
            border: 1px solid {DESK_LINE};
            border-radius: {RADIUS}px;
            gridline-color: {DESK_LINE};
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_BODY}px;
            color: {INK};
        }}
        QHeaderView::section {{
            background-color: {DESK};
            color: {INK_SOFT};
            border: none;
            border-bottom: 1px solid {DESK_LINE};
            padding: {SP_2}px;
            font-weight: 700;
        }}
        QTableWidget::item {{ padding: {SP_2}px; border: none; }}
    """

    # ── List widgets (day pickers, group selectors) ─────────────────
    LIST_WIDGET = f"""
        QListWidget {{
            background-color: #FBFAF5;
            border: 1px solid {DESK_LINE};
            border-radius: {RADIUS}px;
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_UI}px;
            color: {INK};
            padding: {SP_1}px;
            outline: 0;
        }}
        QListWidget::item {{ padding: {SP_2}px {SP_3}px; border-radius: {RADIUS_SM}px; }}
        QListWidget::item:hover {{ background-color: {DESK}; }}
        QListWidget::item:selected {{ background-color: {MANGO}; color: {INK}; }}
    """

    # ── Score outcome labels ────────────────────────────────────────
    @staticmethod
    def SCORE_LABEL(tier: str) -> str:
        """tier: 'high' | 'mid' | 'low'"""
        color = {"high": LEAF, "mid": MANGO_DK, "low": CLAY}[tier]
        return f"""
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_SCORE}px;
            font-weight: 800;
            color: {color};
        """

    # ── Group box ───────────────────────────────────────────────────
    GROUP_BOX = f"""
        QGroupBox {{
            background-color: {DESK};
            border: 1px solid {DESK_LINE};
            border-radius: {RADIUS}px;
            margin-top: {SP_4}px;
            padding-top: {SP_3}px;
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_UI}px;
            font-weight: 700;
            color: {INK};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: {SP_3}px; padding: 0 {SP_2}px;
        }}
    """

    # ── Checkbox ────────────────────────────────────────────────────
    CHECKBOX = f"""
        QCheckBox {{
            font-family: {FONT_FALLBACK};
            font-size: {SIZE_UI}px;
            color: {INK};
            spacing: {SP_2}px;
        }}
        QCheckBox::indicator {{
            width: 20px; height: 20px;
            border: 2px solid {DESK_LINE};
            border-radius: 5px;
            background-color: #FBFAF5;
        }}
        QCheckBox::indicator:hover {{ border-color: {MANGO}; }}
        QCheckBox::indicator:checked {{
            background-color: {MANGO};
            border-color: {MANGO_DK};
        }}
    """
