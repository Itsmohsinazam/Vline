"""
VLINE - Vehicle Licence Interpretation and Number Extraction
Configuration Settings
"""

import os
import json
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
DB_PATH       = BASE_DIR / "vline_data.db"
CONFIG_FILE   = BASE_DIR / "vline_config.json"
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
SNAPSHOTS_DIR.mkdir(exist_ok=True)

# ─── App Metadata ─────────────────────────────────────────────────────────────
APP_VERSION = "2.1.0"

# ─── EasyOCR Settings ─────────────────────────────────────────────────────────
EASYOCR_CONFIDENCE = 0.3          # minimum confidence score for text
EASYOCR_MIN_LENGTH = 4            # minimum length for a valid plate

# ─── Video ────────────────────────────────────────────────────────────────────
FRAME_SKIP         = 10           # analyse every N-th frame (reduce API calls)
DETECTION_COOLDOWN = 3.0          # seconds before re-detecting same plate
JPEG_QUALITY       = 85           # quality of frames sent to API
DISPLAY_WIDTH      = 720
DISPLAY_HEIGHT     = 480

# ─── Vehicle type icon mapping ────────────────────────────────────────────────
VEHICLE_ICONS = {
    "Car":        "🚗",
    "Motorcycle": "🏍️",
    "Truck":      "🚚",
    "Bus":        "🚌",
    "Van":        "🚐",
    "Pickup":     "🛻",
    "Unknown":    "🚙",
}

# ─── Colours used by the dashboard ───────────────────────────────────────────
COLORS = {
    # Core backgrounds
    "bg":             "#0b0d14",
    "sidebar":        "#11141f",
    "card":           "#161a2b",
    "card_alt":       "#1c2038",
    "header_bg":      "#0e1019",

    # Accent palette
    "accent":         "#4f8ef7",
    "accent2":        "#6c63ff",
    "accent_glow":    "#4f8ef720",
    "accent_gradient_start": "#4f8ef7",
    "accent_gradient_end":   "#6c63ff",

    # Semantic
    "success":        "#2ecc71",
    "success_dim":    "#1a8a4a",
    "warning":        "#f1c40f",
    "warning_dim":    "#a68a00",
    "danger":         "#e74c3c",
    "danger_dim":     "#a63228",

    # Text
    "text":           "#e8eaf6",
    "text_dim":       "#6b7394",
    "text_muted":     "#3d4566",

    # Borders / Lines
    "border":         "#1e2340",
    "border_light":   "#2a2f52",
    "divider":        "#1a1e35",

    # Treeview
    "row_even":       "#161a2b",
    "row_odd":        "#1a1f33",
    "row_hover":      "#222845",
    "row_selected":   "#2d4a8a",

    # Toast
    "toast_bg":       "#1c2038ee",
    "toast_success":  "#2ecc71",
    "toast_info":     "#4f8ef7",
    "toast_warning":  "#f1c40f",
    "toast_error":    "#e74c3c",
}

# ─── Animation / Timing ──────────────────────────────────────────────────────
ANIM = {
    "poll_ms":            50,     # queue poll interval (ms)
    "stats_debounce_ms":  2000,   # debounce for stats/log refresh
    "toast_duration_ms":  3000,   # how long toast notifications display
    "toast_fade_ms":      300,    # toast fade in/out
    "pulse_interval_ms":  800,    # status dot pulse speed
    "clock_update_ms":    1000,   # footer clock refresh
    "session_timer_ms":   1000,   # session elapsed timer
}

# ─── Load / Save persistent config ───────────────────────────────────────────
_DEFAULTS = {
    "easyocr_confidence": EASYOCR_CONFIDENCE,
    "easyocr_min_length": EASYOCR_MIN_LENGTH,
    "frame_skip":         FRAME_SKIP,
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            return {**_DEFAULTS, **data}
        except Exception:
            pass
    return dict(_DEFAULTS)


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
