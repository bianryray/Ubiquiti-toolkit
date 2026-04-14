"""Shared theme palette for UniFi Toolbox.

CustomTkinter supports `(light, dark)` 2-tuples for most color arguments.
Centralising them here lets every tab respect the current appearance mode
instead of hard-coding dark-only hex values.
"""

from typing import Tuple

Color = Tuple[str, str]  # (light, dark)


# ── Surfaces ────────────────────────────────────────────────────────
# (light, dark)
BG_APP: Color = ("#f5f5f9", "#1a1a2e")
BG_HEADER: Color = ("#2a3e5c", "#16213e")         # header bar (always dark-ish for brand)
BG_CARD: Color = ("#ffffff", "#2a2a3e")           # section cards
BG_CARD_ALT: Color = ("#eef0f5", "#222236")       # table header / striped rows
BG_LOG: Color = ("#fafafa", "#1e1e2e")            # log textbox
BG_UPDATE: Color = ("#dde9ff", "#1e3a5f")         # update banner

# ── Text ────────────────────────────────────────────────────────────
TEXT: Color = ("#1a1a2e", "#eaeaea")
TEXT_DIM: Color = ("#6a6a7a", "#8a8a9a")
TEXT_ON_CARD: Color = ("#1a1a2e", "#ffffff")
TEXT_LOG: Color = ("#2a2a3e", "#d4d4d4")
TEXT_ON_HEADER: Color = ("#ffffff", "#ffffff")

# ── Borders / separators ────────────────────────────────────────────
BORDER: Color = ("#d0d0dc", "#4a4a5e")
SEPARATOR: Color = ("#d5d5e0", "#3a3a4e")

# ── Brand accent buttons ────────────────────────────────────────────
ACCENT: Color = ("#3b5998", "#0f3460")
ACCENT_HOVER: Color = ("#2d4373", "#1a4a70")

# ── Status / actions ────────────────────────────────────────────────
SUCCESS: Color = ("#00a381", "#00b894")
SUCCESS_HOVER: Color = ("#00846b", "#00a381")
DANGER: Color = ("#e94560", "#e94560")
DANGER_HOVER: Color = ("#c73e54", "#c73e54")

# Text color to use on top of SUCCESS buttons. Green works with dark text in
# both modes because the green itself is bright.
TEXT_ON_SUCCESS: Color = ("#ffffff", "#1a1a2e")

# ── Ghost / transparent button borders / hovers ─────────────────────
GHOST_HOVER: Color = ("#e4e4ec", "#3a3a4e")

# ── Row striping (for tables) ───────────────────────────────────────
ROW_STRIPE: Color = ("#f0f2f7", "#282840")

# ── Fonts ───────────────────────────────────────────────────────────
FONT_LABEL = ("Segoe UI", 12)
FONT_HEADING = ("Segoe UI", 13, "bold")
FONT_MONO = ("Consolas", 12)
FONT_SMALL = ("Segoe UI", 11)
FONT_SMALL_BOLD = ("Segoe UI", 11, "bold")
FONT_BTN_BOLD = ("Segoe UI", 12, "bold")
FONT_TITLE = ("Segoe UI", 22, "bold")


def section_card(parent, title: str):
    """Create a themed section card with heading + separator. Returns the card frame."""
    import customtkinter as ctk
    card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=8)
    card.pack(fill="x", padx=4, pady=(0, 8))
    ctk.CTkLabel(
        card, text=title, font=FONT_HEADING,
        text_color=TEXT_ON_CARD, anchor="w",
    ).pack(fill="x", padx=14, pady=(10, 2))
    sep = ctk.CTkFrame(card, height=1, fg_color=SEPARATOR)
    sep.pack(fill="x", padx=14, pady=(0, 8))
    return card
