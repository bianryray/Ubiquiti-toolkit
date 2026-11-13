"""Design system for UniFi Toolbox: palette, type scale and widget factories.

Every color is a `(light, dark)` tuple so CustomTkinter switches with the
appearance mode. Tabs build their UI only through the helpers at the bottom
(card, button, entry, field, ...) so the whole app stays visually consistent.
"""

from typing import Optional, Tuple

import customtkinter as ctk

Color = Tuple[str, str]  # (light, dark)

# ── Surfaces ────────────────────────────────────────────────────────
BG_APP: Color = ("#f3f5f9", "#0d1117")
BG_SIDEBAR: Color = ("#ffffff", "#11161d")
BG_CARD: Color = ("#ffffff", "#161b23")
BG_CARD_ALT: Color = ("#f6f8fb", "#1b212b")      # table header / inset areas
BG_INPUT: Color = ("#f8fafc", "#0f141a")
BG_LOG: Color = ("#f8fafc", "#0b0f14")
BG_UPDATE: Color = ("#e8f0ff", "#132443")
BG_HOVER: Color = ("#eef2f7", "#1f2630")
BG_SELECTED: Color = ("#e6efff", "#1a2a44")

# ── Text ────────────────────────────────────────────────────────────
TEXT: Color = ("#0f172a", "#e6edf3")
TEXT_DIM: Color = ("#64748b", "#8b98a9")
TEXT_FAINT: Color = ("#94a3b8", "#5d6b7d")
TEXT_ON_CARD = TEXT
TEXT_LOG: Color = ("#334155", "#c9d4e0")
TEXT_ON_ACCENT: Color = ("#ffffff", "#ffffff")

# ── Lines ───────────────────────────────────────────────────────────
BORDER: Color = ("#e2e8f0", "#232b36")
BORDER_INPUT: Color = ("#d4dbe5", "#2c3643")
SEPARATOR = BORDER

# ── Brand / status ──────────────────────────────────────────────────
ACCENT: Color = ("#2563eb", "#3b82f6")
ACCENT_HOVER: Color = ("#1d4ed8", "#2563eb")
ACCENT_SOFT: Color = ("#dbe7ff", "#1c2c4a")      # selected nav item, chips
SUCCESS: Color = ("#16a34a", "#22c55e")
SUCCESS_HOVER: Color = ("#15803d", "#16a34a")
TEXT_ON_SUCCESS: Color = ("#ffffff", "#052e14")
DANGER: Color = ("#dc2626", "#ef4444")
DANGER_HOVER: Color = ("#b91c1c", "#dc2626")
WARNING: Color = ("#d97706", "#f59e0b")

# Back-compat names used by older code
BG_HEADER = BG_SIDEBAR
TEXT_ON_HEADER = TEXT
GHOST_HOVER = BG_HOVER
ROW_STRIPE: Color = ("#f8fafc", "#18202a")

# ── Type ────────────────────────────────────────────────────────────
_F = "Segoe UI"
FONT_TITLE = (_F, 22, "bold")
FONT_PAGE_TITLE = (_F, 20, "bold")
FONT_HEADING = (_F, 14, "bold")
FONT_LABEL = (_F, 12)
FONT_LABEL_BOLD = (_F, 12, "bold")
FONT_SMALL = (_F, 11)
FONT_SMALL_BOLD = (_F, 11, "bold")
FONT_BTN = (_F, 12)
FONT_BTN_BOLD = (_F, 12, "bold")
FONT_NAV = (_F, 13)
FONT_MONO = ("Consolas", 12)
FONT_MONO_SMALL = ("Consolas", 11)

RADIUS = 10
RADIUS_SM = 8
CONTROL_H = 34
PAD = 18  # inner card padding


# ── Widget factories ────────────────────────────────────────────────

def page_header(parent, title: str, subtitle: str = ""):
    """Large page title + one-line description at the top of each page."""
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    wrap.pack(fill="x", padx=4, pady=(2, 14))
    ctk.CTkLabel(wrap, text=title, font=FONT_PAGE_TITLE, text_color=TEXT,
                 anchor="w").pack(fill="x")
    if subtitle:
        autowrap(ctk.CTkLabel(wrap, text=subtitle, font=FONT_LABEL, text_color=TEXT_DIM,
                              anchor="w", justify="left")).pack(fill="x", pady=(2, 0))
    return wrap


def autowrap(lbl, margin: int = 8):
    """Make a label re-wrap its text to the width of its container.

    Watches the parent, not the label: the label's own width depends on its
    wrap length, so reacting to it would shrink it in a feedback loop.
    """
    parent = lbl.master
    state = {"w": 0}

    def on_resize(event):
        width = max(event.width - margin, 100)
        if abs(width - state["w"]) > 2:
            state["w"] = width
            lbl.configure(wraplength=width)
    parent.bind("<Configure>", on_resize, add="+")
    return lbl


def card(parent, title: str = "", subtitle: str = "", *, expand: bool = False,
         actions: bool = False):
    """Rounded bordered surface. Returns the padded body frame.

    With actions=True returns (body, header_right) so callers can put
    buttons on the right side of the title row.
    """
    outer = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=RADIUS,
                         border_width=1, border_color=BORDER)
    outer.pack(fill="both" if expand else "x", expand=expand, padx=4, pady=(0, 12))
    right = None
    if title:
        head = ctk.CTkFrame(outer, fg_color="transparent")
        head.pack(fill="x", padx=PAD, pady=(PAD - 4, 0))
        text_col = ctk.CTkFrame(head, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text_col, text=title, font=FONT_HEADING, text_color=TEXT,
                     anchor="w").pack(fill="x")
        if subtitle:
            autowrap(ctk.CTkLabel(text_col, text=subtitle, font=FONT_SMALL, text_color=TEXT_DIM,
                                  anchor="w", justify="left")).pack(fill="x")
        if actions:  # an empty CTkFrame would keep its default 200px height
            right = ctk.CTkFrame(head, fg_color="transparent")
            right.pack(side="right")
    body = ctk.CTkFrame(outer, fg_color="transparent")
    body.pack(fill="both", expand=expand, padx=PAD, pady=(12 if title else PAD, PAD))
    body.outer = outer
    return (body, right) if actions else body


# Backwards-compatible name
def section_card(parent, title: str):
    return card(parent, title)


_BTN_STYLES = {
    "primary": dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT_ON_ACCENT,
                    border_width=0),
    "success": dict(fg_color=SUCCESS, hover_color=SUCCESS_HOVER, text_color=TEXT_ON_SUCCESS,
                    border_width=0),
    "danger": dict(fg_color=DANGER, hover_color=DANGER_HOVER, text_color=TEXT_ON_ACCENT,
                   border_width=0),
    "secondary": dict(fg_color=BG_CARD_ALT, hover_color=BG_HOVER, text_color=TEXT,
                      border_width=1, border_color=BORDER_INPUT),
    "ghost": dict(fg_color="transparent", hover_color=BG_HOVER, text_color=TEXT,
                  border_width=0),
    "danger-outline": dict(fg_color="transparent", hover_color=("#fdecec", "#2a1518"),
                           text_color=DANGER, border_width=1, border_color=DANGER),
}


def button(parent, text: str, command=None, kind: str = "secondary",
           width: int = 0, height: int = CONTROL_H, bold: Optional[bool] = None, **kw):
    style = dict(_BTN_STYLES[kind])
    style.update(kw)
    if bold is None:
        bold = kind in ("primary", "success", "danger")
    if not width:
        width = max(80, 22 + 8 * len(text))
    return ctk.CTkButton(
        parent, text=text, command=command, width=width, height=height,
        corner_radius=RADIUS_SM, font=FONT_BTN_BOLD if bold else FONT_BTN, **style,
    )


def entry(parent, var=None, width: int = 260, placeholder: str = "", show: str = "",
          mono: bool = False, **kw):
    opts = dict(
        width=width, height=CONTROL_H, corner_radius=RADIUS_SM, border_width=1,
        fg_color=BG_INPUT, border_color=BORDER_INPUT, text_color=TEXT,
        placeholder_text_color=TEXT_FAINT, font=FONT_MONO if mono else FONT_LABEL,
    )
    if var is not None:
        opts["textvariable"] = var
    if placeholder and var is None:
        opts["placeholder_text"] = placeholder
    if show:
        opts["show"] = show
    opts.update(kw)
    return ctk.CTkEntry(parent, **opts)


def label(parent, text: str = "", dim: bool = False, small: bool = False,
          bold: bool = False, **kw):
    font = (FONT_SMALL_BOLD if bold else FONT_SMALL) if small else (
        FONT_LABEL_BOLD if bold else FONT_LABEL)
    kw.setdefault("anchor", "w")
    kw.setdefault("justify", "left")
    return ctk.CTkLabel(parent, text=text, font=font,
                        text_color=TEXT_DIM if dim else TEXT, **kw)


def checkbox(parent, text: str, var, command=None):
    return ctk.CTkCheckBox(
        parent, text=text, variable=var, command=command, font=FONT_LABEL,
        text_color=TEXT, checkbox_width=18, checkbox_height=18, corner_radius=5,
        border_width=2, border_color=BORDER_INPUT, fg_color=ACCENT,
        hover_color=ACCENT_HOVER,
    )


def switch(parent, text: str, var, command=None):
    return ctk.CTkSwitch(
        parent, text=text, variable=var, command=command, font=FONT_LABEL,
        text_color=TEXT, progress_color=ACCENT, switch_width=38, switch_height=20,
    )


def segmented(parent, values, var=None, command=None, **kw):
    return ctk.CTkSegmentedButton(
        parent, values=values, variable=var, command=command, font=FONT_LABEL,
        height=CONTROL_H - 2, corner_radius=RADIUS_SM,
        fg_color=BG_CARD_ALT, unselected_color=BG_CARD_ALT,
        unselected_hover_color=BG_HOVER, selected_color=ACCENT_SOFT,
        selected_hover_color=ACCENT_SOFT, text_color=TEXT, **kw,
    )


def field(parent, row: int, col: int, title: str, widget_factory, hint: str = "",
          colspan: int = 1):
    """Grid cell with a small label above its input (and optional hint below).

    widget_factory(cell) must create and return the input inside `cell`.
    """
    cell = ctk.CTkFrame(parent, fg_color="transparent")
    cell.grid(row=row, column=col, columnspan=colspan, sticky="nw",
              padx=(0, 20), pady=(0, 12))
    ctk.CTkLabel(cell, text=title, font=FONT_SMALL_BOLD, text_color=TEXT_DIM,
                 anchor="w").pack(fill="x", pady=(0, 4))
    w = widget_factory(cell)
    w.pack(anchor="w")
    if hint:
        ctk.CTkLabel(cell, text=hint, font=FONT_SMALL, text_color=TEXT_FAINT,
                     anchor="w", justify="left").pack(fill="x", pady=(3, 0))
    cell.input = w
    return cell


def row(parent, pady=(0, 0)):
    """Horizontal container; pack children with side='left'."""
    f = ctk.CTkFrame(parent, fg_color="transparent")
    f.pack(fill="x", pady=pady)
    return f


def divider(parent, pady=(4, 12)):
    ctk.CTkFrame(parent, height=1, fg_color=BORDER).pack(fill="x", pady=pady)


def scroll_page(parent):
    """Scrollable page body with consistent padding."""
    s = ctk.CTkScrollableFrame(parent, fg_color="transparent",
                               scrollbar_button_color=BORDER_INPUT,
                               scrollbar_button_hover_color=TEXT_FAINT)
    s.pack(fill="both", expand=True)
    return s
