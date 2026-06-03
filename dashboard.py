"""
VLINE – Dashboard UI  v2.1
Vehicle Licence Interpretation and Number Extraction
Full Tkinter-based dashboard with live camera / video feed, detection log,
stats panel, settings, and database management.

Improvements over v1:
  • Fixed status indicator color (was a no-op)
  • Debounced stats/log refresh to prevent UI freezing
  • Alternating row colors in treeviews
  • Toast notifications instead of blocking messageboxes
  • Loading overlay during model initialization
  • Pulsing status dot animation
  • Footer bar with version, DB count, clock, and session timer
  • Responsive canvas placeholder
  • Placeholder text in search entry
  • Cleaned up dead code and redundant style creation
"""

import io
import os
import csv
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime, timedelta
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageTk, ImageDraw

from config import (
    COLORS, VEHICLE_ICONS, ANIM, APP_VERSION,
    load_config, save_config, DISPLAY_WIDTH, DISPLAY_HEIGHT,
)
from database import VlineDatabase
from detector import VideoProcessor


# ─── Toast Notification System ────────────────────────────────────────────────

class ToastManager:
    """Manages non-blocking toast notifications in the top-right corner."""

    def __init__(self, parent: tk.Tk):
        self._parent = parent
        self._toasts: list[tk.Toplevel] = []

    def show(self, message: str, kind: str = "info"):
        """Show a toast. kind = info | success | warning | error"""
        color_map = {
            "info":    COLORS["toast_info"],
            "success": COLORS["toast_success"],
            "warning": COLORS["toast_warning"],
            "error":   COLORS["toast_error"],
        }
        icon_map = {
            "info": "ℹ️", "success": "✅",
            "warning": "⚠️", "error": "❌",
        }
        accent = color_map.get(kind, COLORS["toast_info"])
        icon   = icon_map.get(kind, "ℹ️")

        toast = tk.Toplevel(self._parent)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=COLORS["card"])

        # Outer frame with colored left accent bar
        outer = tk.Frame(toast, bg=COLORS["card"], padx=0, pady=0)
        outer.pack(fill="both", expand=True)

        bar = tk.Frame(outer, bg=accent, width=4)
        bar.pack(side="left", fill="y")

        content = tk.Frame(outer, bg=COLORS["card"], padx=14, pady=10)
        content.pack(side="left", fill="both", expand=True)

        tk.Label(content, text=f"{icon}  {message}",
                 font=("Segoe UI", 10), fg=COLORS["text"],
                 bg=COLORS["card"], anchor="w").pack(anchor="w")

        # Position in top-right
        toast.update_idletasks()
        tw = max(toast.winfo_reqwidth(), 300)
        th = toast.winfo_reqheight()
        px = self._parent.winfo_x() + self._parent.winfo_width() - tw - 24
        py = self._parent.winfo_y() + 70 + len(self._toasts) * (th + 8)
        toast.geometry(f"{tw}x{th}+{px}+{py}")

        # Fade effect via alpha
        toast.attributes("-alpha", 0.0)
        self._toasts.append(toast)
        self._fade_in(toast, 0.0)

    def _fade_in(self, toast, alpha):
        if not toast.winfo_exists():
            return
        alpha = min(alpha + 0.12, 0.95)
        toast.attributes("-alpha", alpha)
        if alpha < 0.95:
            self._parent.after(25, self._fade_in, toast, alpha)
        else:
            self._parent.after(ANIM["toast_duration_ms"], self._fade_out, toast, alpha)

    def _fade_out(self, toast, alpha):
        if not toast.winfo_exists():
            return
        alpha = max(alpha - 0.12, 0.0)
        toast.attributes("-alpha", alpha)
        if alpha > 0.0:
            self._parent.after(25, self._fade_out, toast, alpha)
        else:
            if toast in self._toasts:
                self._toasts.remove(toast)
            toast.destroy()


# ─── Loading Overlay ──────────────────────────────────────────────────────────

class LoadingOverlay:
    """Translucent overlay shown during model loading."""

    def __init__(self, parent: tk.Widget):
        self._parent = parent
        self._frame: Optional[tk.Frame] = None
        self._label: Optional[tk.Label] = None
        self._dots = 0
        self._anim_id = None

    def show(self, text="Loading models…"):
        if self._frame:
            return
        self._frame = tk.Frame(self._parent, bg="#000000")
        self._frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        inner = tk.Frame(self._frame, bg=COLORS["card"],
                         highlightbackground=COLORS["accent"],
                         highlightthickness=1, padx=30, pady=24)
        inner.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(inner, text="🚀", font=("Segoe UI", 28),
                 bg=COLORS["card"]).pack(pady=(0, 8))

        self._label = tk.Label(inner, text=text,
                               font=("Segoe UI", 12),
                               fg=COLORS["text"], bg=COLORS["card"])
        self._label.pack()

        self._sub = tk.Label(inner, text="Please wait",
                             font=("Segoe UI", 9),
                             fg=COLORS["text_dim"], bg=COLORS["card"])
        self._sub.pack(pady=(4, 0))
        self._animate_dots()

    def update_text(self, text: str):
        if self._label and self._label.winfo_exists():
            self._label.config(text=text)

    def _animate_dots(self):
        if self._sub and self._sub.winfo_exists():
            self._dots = (self._dots + 1) % 4
            self._sub.config(text="Please wait" + "." * self._dots)
            self._anim_id = self._parent.after(400, self._animate_dots)

    def hide(self):
        if self._anim_id:
            self._parent.after_cancel(self._anim_id)
            self._anim_id = None
        if self._frame and self._frame.winfo_exists():
            self._frame.destroy()
        self._frame = None
        self._label = None


# ─── Small helper widgets ─────────────────────────────────────────────────────

def make_card(parent, **kw):
    f = tk.Frame(parent, bg=COLORS["card"],
                 highlightbackground=COLORS["border"],
                 highlightthickness=1, **kw)
    return f


def label(parent, text, size=11, bold=False, color=None, **kw):
    return tk.Label(
        parent, text=text,
        font=("Segoe UI", size, "bold" if bold else "normal"),
        fg=color or COLORS["text"], bg=parent["bg"], **kw
    )


def btn(parent, text, cmd, **kw):
    b = ttk.Button(parent, text=text, command=cmd, style="Accent.TButton")
    return b


# ─── Stats card widget ───────────────────────────────────────────────────────

class StatCard(tk.Frame):
    def __init__(self, parent, title, value, icon, color):
        super().__init__(parent, bg=COLORS["card"],
                         highlightbackground=color, highlightthickness=2)
        tk.Label(self, text=icon, font=("Segoe UI", 22),
                 bg=COLORS["card"], fg=color).pack(pady=(14, 2))
        self._val = tk.StringVar(value=str(value))
        tk.Label(self, textvariable=self._val, font=("Segoe UI", 20, "bold"),
                 bg=COLORS["card"], fg=color).pack()
        tk.Label(self, text=title, font=("Segoe UI", 9),
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(pady=(0, 14))

    def update_val(self, v):
        self._val.set(str(v))


# ─── Placeholder Search Entry ────────────────────────────────────────────────

class PlaceholderEntry(tk.Entry):
    """Entry widget with built-in placeholder text."""

    def __init__(self, master, placeholder="Search…", **kw):
        super().__init__(master, **kw)
        self._ph = placeholder
        self._ph_color = COLORS["text_muted"]
        self._fg = kw.get("fg", COLORS["text"])
        self._has_focus = False

        self.bind("<FocusIn>",  self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self._show_placeholder()

    def _show_placeholder(self):
        if not self.get():
            self.insert(0, self._ph)
            self.config(fg=self._ph_color)

    def _on_focus_in(self, _):
        self._has_focus = True
        if self.get() == self._ph:
            self.delete(0, "end")
            self.config(fg=self._fg)

    def _on_focus_out(self, _):
        self._has_focus = False
        if not self.get():
            self._show_placeholder()

    def get_value(self):
        """Return the real value, or '' if placeholder is shown."""
        val = self.get()
        return "" if val == self._ph else val


# ─── Main Application ─────────────────────────────────────────────────────────

class VlineApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("VLINE  ·  Vehicle Licence Interpretation and Number Extraction")
        self.configure(bg=COLORS["bg"])
        self.state("zoomed")           # maximise on Windows
        try:
            self.attributes("-zoomed", True)
        except Exception:
            pass

        self.cfg       = load_config()
        self.db        = VlineDatabase()
        self._processor: Optional[VideoProcessor] = None
        self._session_id: Optional[int] = None
        self._session_count = 0
        self._session_start: Optional[datetime] = None
        self._q: queue.Queue = queue.Queue()   # thread → GUI
        self._last_frame: Optional[ImageTk.PhotoImage] = None
        self._running = False

        # Debounce tracking
        self._stats_dirty = False
        self._stats_timer_id = None

        # Pulse animation state
        self._pulse_on = True
        self._pulse_id = None

        # Toast manager
        self._toast = ToastManager(self)

        # Apply sv_ttk overrides
        try:
            import sv_ttk
            sv_ttk.set_theme("dark")
        except ImportError:
            pass

        self._apply_custom_styles()
        self._build_ui()
        self._refresh_stats()
        self._refresh_log()
        self._poll_queue()
        self._update_clock()

    # ── Custom style overrides (after sv_ttk) ─────────────────────────────────

    def _apply_custom_styles(self):
        style = ttk.Style(self)

        # Notebook
        style.configure("VLINE.TNotebook",
                        background=COLORS["bg"], borderwidth=0)
        style.configure("VLINE.TNotebook.Tab",
                        background=COLORS["sidebar"],
                        foreground=COLORS["text_dim"],
                        font=("Segoe UI", 10, "bold"),
                        padding=[20, 10])
        style.map("VLINE.TNotebook.Tab",
                  background=[("selected", COLORS["accent"])],
                  foreground=[("selected", "white")])

        # Treeview (configured once, globally)
        style.configure("Treeview",
                        background=COLORS["card"],
                        foreground=COLORS["text"],
                        rowheight=30,
                        fieldbackground=COLORS["card"],
                        borderwidth=0,
                        font=("Segoe UI", 9))
        style.configure("Treeview.Heading",
                        background=COLORS["sidebar"],
                        foreground=COLORS["accent"],
                        font=("Segoe UI", 9, "bold"),
                        relief="flat")
        style.map("Treeview",
                  background=[("selected", COLORS["row_selected"])],
                  foreground=[("selected", "white")])

        # Accent button
        style.configure("Accent.TButton",
                        font=("Segoe UI", 10, "bold"),
                        padding=[12, 8])

    # ── Build layout ──────────────────────────────────────────────────────────

    def _build_ui(self):
        # ─── Header ───────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=COLORS["header_bg"], height=58)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)

        # Accent line under header
        accent_line = tk.Frame(self, bg=COLORS["accent"], height=2)
        accent_line.pack(fill="x", side="top")

        tk.Label(hdr, text="🚘  VLINE",
                 font=("Segoe UI", 18, "bold"),
                 fg=COLORS["accent"], bg=COLORS["header_bg"]).pack(
                     side="left", padx=20, pady=10)
        tk.Label(hdr, text="Vehicle Licence Interpretation and Number Extraction",
                 font=("Segoe UI", 10),
                 fg=COLORS["text_dim"], bg=COLORS["header_bg"]).pack(side="left")

        # Status label – keep reference for color changes
        self._status_var = tk.StringVar(value="● Idle")
        self._status_label = tk.Label(
            hdr, textvariable=self._status_var,
            font=("Segoe UI", 10, "bold"),
            fg=COLORS["text_dim"], bg=COLORS["header_bg"])
        self._status_label.pack(side="right", padx=20)

        # ─── Notebook (tabs) ─────────────────────────────────────────────
        nb = ttk.Notebook(self, style="VLINE.TNotebook")
        nb.pack(fill="both", expand=True, padx=0, pady=0)

        # Tab 1 – Live Detection
        self._tab_live = tk.Frame(nb, bg=COLORS["bg"])
        nb.add(self._tab_live, text="  📷  Live Detection  ")

        # Tab 2 – History / Log
        self._tab_log = tk.Frame(nb, bg=COLORS["bg"])
        nb.add(self._tab_log, text="  📋  Detection Log  ")

        # Tab 3 – Settings
        self._tab_cfg = tk.Frame(nb, bg=COLORS["bg"])
        nb.add(self._tab_cfg, text="  ⚙️  Settings  ")

        self._build_live_tab()
        self._build_log_tab()
        self._build_settings_tab()
        self._build_footer()

    # ── Footer Bar ────────────────────────────────────────────────────────────

    def _build_footer(self):
        footer = tk.Frame(self, bg=COLORS["header_bg"], height=28)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        # Thin top border
        tk.Frame(footer, bg=COLORS["border"], height=1).pack(fill="x", side="top")

        inner = tk.Frame(footer, bg=COLORS["header_bg"])
        inner.pack(fill="both", expand=True)

        # Left: version
        tk.Label(inner, text=f"VLINE v{APP_VERSION}",
                 font=("Segoe UI", 8), fg=COLORS["text_muted"],
                 bg=COLORS["header_bg"]).pack(side="left", padx=12)

        # Left: DB count
        self._footer_db_var = tk.StringVar(value="0 records in database")
        tk.Label(inner, textvariable=self._footer_db_var,
                 font=("Segoe UI", 8), fg=COLORS["text_muted"],
                 bg=COLORS["header_bg"]).pack(side="left", padx=8)

        # Center: session timer
        self._footer_session_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self._footer_session_var,
                 font=("Segoe UI", 8, "bold"), fg=COLORS["accent"],
                 bg=COLORS["header_bg"]).pack(side="left", padx=20)

        # Right: clock
        self._footer_clock_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self._footer_clock_var,
                 font=("Segoe UI", 8), fg=COLORS["text_muted"],
                 bg=COLORS["header_bg"]).pack(side="right", padx=12)

    def _update_clock(self):
        now = datetime.now()
        self._footer_clock_var.set(now.strftime("%A, %d %b %Y  •  %H:%M:%S"))

        # Session timer
        if self._running and self._session_start:
            elapsed = now - self._session_start
            mins, secs = divmod(int(elapsed.total_seconds()), 60)
            hrs, mins = divmod(mins, 60)
            self._footer_session_var.set(
                f"⏱  Session: {hrs:02d}:{mins:02d}:{secs:02d}  •  "
                f"{self._session_count} detections")
        elif not self._running:
            self._footer_session_var.set("")

        self.after(ANIM["clock_update_ms"], self._update_clock)

    # ── Tab 1: Live Detection ─────────────────────────────────────────────────

    def _build_live_tab(self):
        outer = self._tab_live
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # Left sidebar ─────────────────────────────────────────────────────
        sidebar_outer = tk.Frame(outer, bg=COLORS["sidebar"], width=280)
        sidebar_outer.grid(row=0, column=0, sticky="ns", padx=0, pady=0)
        sidebar_outer.grid_propagate(False)
        sidebar_outer.columnconfigure(0, weight=1)
        sidebar_outer.rowconfigure(0, weight=1)

        # Scrollable canvas inside sidebar
        self._sidebar_canvas = tk.Canvas(
            sidebar_outer, bg=COLORS["sidebar"],
            highlightthickness=0, width=264)
        self._sidebar_canvas.grid(row=0, column=0, sticky="nsew")

        sidebar_vsb = ttk.Scrollbar(
            sidebar_outer, orient="vertical",
            command=self._sidebar_canvas.yview)
        sidebar_vsb.grid(row=0, column=1, sticky="ns")
        self._sidebar_canvas.configure(yscrollcommand=sidebar_vsb.set)

        # Inner frame that holds all sidebar content
        sidebar = tk.Frame(self._sidebar_canvas, bg=COLORS["sidebar"])
        self._sidebar_window = self._sidebar_canvas.create_window(
            (0, 0), window=sidebar, anchor="nw")

        # Update scroll region when sidebar content changes size
        def _on_sidebar_configure(event):
            self._sidebar_canvas.configure(
                scrollregion=self._sidebar_canvas.bbox("all"))
        sidebar.bind("<Configure>", _on_sidebar_configure)

        # Make canvas width follow the outer frame
        def _on_canvas_configure(event):
            self._sidebar_canvas.itemconfig(
                self._sidebar_window, width=event.width)
        self._sidebar_canvas.bind("<Configure>", _on_canvas_configure)

        # Mousewheel scrolling on sidebar
        def _on_mousewheel(event):
            self._sidebar_canvas.yview_scroll(
                int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel(event):
            self._sidebar_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(event):
            self._sidebar_canvas.unbind_all("<MouseWheel>")

        self._sidebar_canvas.bind("<Enter>", _bind_mousewheel)
        self._sidebar_canvas.bind("<Leave>", _unbind_mousewheel)

        # Right border on sidebar
        tk.Frame(sidebar_outer, bg=COLORS["border"], width=1).place(
            relx=1.0, rely=0, relheight=1, anchor="ne")

        label(sidebar, "SOURCE", 9, bold=True,
              color=COLORS["text_dim"]).pack(anchor="w", padx=18, pady=(18, 4))

        src_frame = tk.Frame(sidebar, bg=COLORS["sidebar"])
        src_frame.pack(fill="x", padx=12, pady=4)
        self._src_var = tk.StringVar(value="camera")
        for val, text, icon in [("camera", "Live Camera", "📷"),
                                 ("video",  "Video File",  "🎬")]:
            rb = tk.Radiobutton(
                src_frame, text=f" {icon}  {text}", variable=self._src_var,
                value=val, bg=COLORS["sidebar"], fg=COLORS["text"],
                selectcolor=COLORS["card"], activebackground=COLORS["sidebar"],
                activeforeground=COLORS["text"],
                font=("Segoe UI", 10), indicatoron=True,
                command=self._on_source_change,
            )
            rb.pack(anchor="w", pady=3, padx=6)

        # Video file selector
        self._file_frame = tk.Frame(sidebar, bg=COLORS["sidebar"])
        self._file_frame.pack(fill="x", padx=12, pady=4)
        self._file_var = tk.StringVar(value="")
        btn(self._file_frame, "📂  Browse Video",
            self._browse_video).pack(fill="x", pady=(0, 4))
        ttk.Entry(self._file_frame, textvariable=self._file_var,
                  font=("Segoe UI", 10), width=30).pack(fill="x")
        self._file_frame.pack_forget()  # hidden until "video" selected

        ttk.Separator(sidebar, orient="horizontal").pack(
            fill="x", padx=12, pady=12)

        # Camera index
        cam_row = tk.Frame(sidebar, bg=COLORS["sidebar"])
        cam_row.pack(fill="x", padx=12, pady=4)
        label(cam_row, "Camera Index:", 9,
              color=COLORS["text_dim"]).pack(side="left")
        self._cam_idx = tk.IntVar(value=0)
        tk.Spinbox(cam_row, from_=0, to=9, textvariable=self._cam_idx,
                   width=4, bg=COLORS["card"], fg=COLORS["text"],
                   buttonbackground=COLORS["border"],
                   font=("Segoe UI", 10), relief="flat").pack(side="right")

        ttk.Separator(sidebar, orient="horizontal").pack(
            fill="x", padx=12, pady=12)

        # Controls
        label(sidebar, "CONTROLS", 9, bold=True,
              color=COLORS["text_dim"]).pack(anchor="w", padx=18, pady=(0, 8))

        self._start_btn = btn(sidebar, "▶  Start Detection", self._start)
        self._start_btn.pack(padx=12, pady=4, fill="x")

        self._stop_btn = btn(sidebar, "⏹  Stop", self._stop)
        self._stop_btn.pack(padx=12, pady=4, fill="x")
        self._stop_btn.config(state="disabled")

        ttk.Separator(sidebar, orient="horizontal").pack(
            fill="x", padx=12, pady=12)

        # Stats cards
        label(sidebar, "SESSION STATS", 9, bold=True,
              color=COLORS["text_dim"]).pack(anchor="w", padx=18, pady=(0, 8))

        cards_frame = tk.Frame(sidebar, bg=COLORS["sidebar"])
        cards_frame.pack(fill="x", padx=8)
        cards_frame.columnconfigure(0, weight=1)
        cards_frame.columnconfigure(1, weight=1)

        self._card_total   = StatCard(cards_frame, "Total",   0, "🚘", COLORS["accent"])
        self._card_today   = StatCard(cards_frame, "Today",   0, "📅", COLORS["success"])
        self._card_unique  = StatCard(cards_frame, "Unique",  0, "🔑", COLORS["warning"])
        self._card_session = StatCard(cards_frame, "Session", 0, "⏱",  COLORS["accent2"])

        for i, c in enumerate([self._card_total, self._card_today,
                                self._card_unique, self._card_session]):
            c.grid(row=i // 2, column=i % 2, padx=4, pady=4, sticky="ew")

        # Right area ───────────────────────────────────────────────────────
        right = tk.Frame(outer, bg=COLORS["bg"])
        right.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # Video canvas
        video_card = make_card(right)
        video_card.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        video_card.rowconfigure(0, weight=1)
        video_card.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(video_card, bg="#050710", cursor="crosshair",
                                 highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._draw_placeholder()

        # Loading overlay container
        self._loading = LoadingOverlay(video_card)

        # Recent detections mini-log
        log_card = make_card(right)
        log_card.grid(row=1, column=0, sticky="nsew")
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)
        label(log_card, "  Recent Detections", 10, bold=True,
              color=COLORS["accent"]).grid(
                  row=0, column=0, sticky="w", padx=10, pady=(8, 0))

        cols = ("Time", "Plate", "Type", "Score", "Source")
        self._live_tree = ttk.Treeview(
            log_card, columns=cols, show="headings", height=6,
            selectmode="browse",
        )
        self._setup_treeview(self._live_tree, cols,
                             widths=[90, 130, 120, 70, 80])
        self._live_tree.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

        vsb = ttk.Scrollbar(log_card, orient="vertical",
                            command=self._live_tree.yview)
        vsb.grid(row=1, column=1, sticky="ns", pady=6)
        self._live_tree.configure(yscrollcommand=vsb.set)

    def _on_canvas_resize(self, event):
        """Redraw placeholder when canvas is resized."""
        if not self._running:
            self._draw_placeholder()

    def _draw_placeholder(self):
        self._canvas.delete("all")
        cw = max(self._canvas.winfo_width(), 200)
        ch = max(self._canvas.winfo_height(), 200)

        self._canvas.create_rectangle(0, 0, cw, ch, fill="#050710", outline="")

        # Subtle grid pattern
        for x in range(0, cw, 40):
            self._canvas.create_line(x, 0, x, ch, fill="#0d1020", width=1)
        for y in range(0, ch, 40):
            self._canvas.create_line(0, y, cw, y, fill="#0d1020", width=1)

        # Center content
        cx, cy = cw // 2, ch // 2
        self._canvas.create_text(
            cx, cy - 20,
            text="📷",
            fill=COLORS["text_dim"], font=("Segoe UI", 32),
        )
        self._canvas.create_text(
            cx, cy + 25,
            text="Press  ▶ Start Detection  to begin",
            fill=COLORS["text_dim"], font=("Segoe UI", 13),
        )
        self._canvas.create_text(
            cx, cy + 50,
            text="Select a camera or video source from the sidebar",
            fill=COLORS["text_muted"], font=("Segoe UI", 9),
        )

    # ── Tab 2: Detection Log ──────────────────────────────────────────────────

    def _build_log_tab(self):
        outer = self._tab_log
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        # Toolbar
        tb = tk.Frame(outer, bg=COLORS["bg"])
        tb.grid(row=0, column=0, sticky="ew", padx=10, pady=10)

        label(tb, "🔍", 12).pack(side="left", padx=(0, 4))

        self._search_entry = PlaceholderEntry(
            tb, placeholder="Search plates, vehicle types…",
            bg=COLORS["card"], fg=COLORS["text"],
            insertbackground=COLORS["text"],
            font=("Segoe UI", 10), relief="flat", width=28)
        self._search_entry.pack(side="left", ipady=4)
        self._search_entry.bind("<KeyRelease>", lambda _: self._refresh_log())

        btn(tb, "📤  Export CSV", self._export_csv).pack(
            side="left", padx=(12, 4))
        btn(tb, "🗑  Clear All", self._clear_db).pack(side="left", padx=4)

        self._log_count_var = tk.StringVar(value="0 records")
        tk.Label(tb, textvariable=self._log_count_var,
                 bg=COLORS["bg"], fg=COLORS["text_dim"],
                 font=("Segoe UI", 9)).pack(side="right", padx=10)

        # Main log table
        log_card = make_card(outer)
        log_card.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(0, weight=1)

        cols = ("ID", "Timestamp", "Plate", "Type", "Plate Score",
                "Confidence", "Region", "Source")
        self._log_tree = ttk.Treeview(
            log_card, columns=cols, show="headings",
            selectmode="extended",
        )
        self._setup_treeview(self._log_tree, cols,
                             widths=[50, 160, 130, 120, 90, 90, 70, 80])
        self._log_tree.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        vsb = ttk.Scrollbar(log_card, orient="vertical",
                            command=self._log_tree.yview)
        vsb.grid(row=0, column=1, sticky="ns", pady=6)
        self._log_tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(log_card, orient="horizontal",
                            command=self._log_tree.xview)
        hsb.grid(row=1, column=0, sticky="ew", padx=6)
        self._log_tree.configure(xscrollcommand=hsb.set)

        # Right-click context menu
        cm = tk.Menu(self, tearoff=0, bg=COLORS["card"], fg=COLORS["text"],
                     activebackground=COLORS["accent"],
                     font=("Segoe UI", 10))
        cm.add_command(label="🗑  Delete selected", command=self._delete_selected)

        def post_cm(e):
            iid = self._log_tree.identify_row(e.y)
            if iid and iid not in self._log_tree.selection():
                self._log_tree.selection_set(iid)
            cm.post(e.x_root, e.y_root)
        self._log_tree.bind("<Button-3>", post_cm)

        # Vehicle type breakdown (bottom)
        bt_frame = tk.Frame(outer, bg=COLORS["bg"])
        bt_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        self._type_labels: dict[str, tk.Label] = {}
        for vtype, icon in VEHICLE_ICONS.items():
            f = tk.Frame(bt_frame, bg=COLORS["card"],
                         highlightbackground=COLORS["border"],
                         highlightthickness=1)
            f.pack(side="left", padx=4)
            tk.Label(f, text=icon, bg=COLORS["card"],
                     font=("Segoe UI", 16)).pack(side="left", padx=6, pady=6)
            lbl = tk.Label(f, text=f"{vtype}\n0",
                           bg=COLORS["card"], fg=COLORS["text"],
                           font=("Segoe UI", 8), justify="center")
            lbl.pack(side="left", padx=(0, 8), pady=6)
            self._type_labels[vtype] = lbl

    # ── Tab 3: Settings ───────────────────────────────────────────────────────

    def _build_settings_tab(self):
        outer = self._tab_cfg
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        # Scrollable canvas for settings
        settings_canvas = tk.Canvas(outer, bg=COLORS["bg"],
                                    highlightthickness=0)
        settings_canvas.grid(row=0, column=0, sticky="nsew")

        settings_vsb = ttk.Scrollbar(outer, orient="vertical",
                                     command=settings_canvas.yview)
        settings_vsb.grid(row=0, column=1, sticky="ns")
        settings_canvas.configure(yscrollcommand=settings_vsb.set)

        wrapper = tk.Frame(settings_canvas, bg=COLORS["bg"])
        settings_win = settings_canvas.create_window(
            (0, 0), window=wrapper, anchor="nw")

        def _on_settings_configure(event):
            settings_canvas.configure(
                scrollregion=settings_canvas.bbox("all"))
        wrapper.bind("<Configure>", _on_settings_configure)

        def _on_settings_canvas_configure(event):
            settings_canvas.itemconfig(settings_win, width=event.width)
        settings_canvas.bind("<Configure>", _on_settings_canvas_configure)

        # Mousewheel scrolling
        def _on_sw(event):
            settings_canvas.yview_scroll(
                int(-1 * (event.delta / 120)), "units")
        def _bind_sw(event):
            settings_canvas.bind_all("<MouseWheel>", _on_sw)
        def _unbind_sw(event):
            settings_canvas.unbind_all("<MouseWheel>")
        settings_canvas.bind("<Enter>", _bind_sw)
        settings_canvas.bind("<Leave>", _unbind_sw)

        # Inner padding frame
        inner_pad = tk.Frame(wrapper, bg=COLORS["bg"])
        inner_pad.pack(expand=True, fill="both", padx=60, pady=30)

        def section(title):
            f = make_card(wrapper)
            f.pack(fill="x", pady=10)
            label(f, f"  {title}", 11, bold=True,
                  color=COLORS["accent"]).pack(anchor="w", padx=16, pady=(12, 4))
            ttk.Separator(f, orient="horizontal").pack(fill="x", padx=12)
            inner = tk.Frame(f, bg=COLORS["card"])
            inner.pack(fill="x", padx=16, pady=12)
            return inner

        # Local Model Settings Section
        ocr_sec = section("🔑  YOLOv11 + EasyOCR Settings")

        row1 = tk.Frame(ocr_sec, bg=COLORS["card"])
        row1.pack(fill="x", pady=6)
        label(row1, "Min Confidence:", 10,
              color=COLORS["text_dim"], width=15).pack(side="left", anchor="w")
        self._conf_var = tk.DoubleVar(
            value=self.cfg.get("easyocr_confidence", 0.3))
        tk.Scale(row1, variable=self._conf_var,
                 from_=0.0, to=1.0, resolution=0.05, orient="horizontal",
                 length=220, bg=COLORS["card"],
                 fg=COLORS["text"], troughcolor=COLORS["border"],
                 activebackground=COLORS["accent"],
                 highlightthickness=0).pack(side="left")

        row2 = tk.Frame(ocr_sec, bg=COLORS["card"])
        row2.pack(fill="x", pady=6)
        label(row2, "Min Plate Length:", 10,
              color=COLORS["text_dim"], width=15).pack(side="left", anchor="w")
        self._len_var = tk.IntVar(
            value=self.cfg.get("easyocr_min_length", 4))
        tk.Scale(row2, variable=self._len_var,
                 from_=1, to=10, orient="horizontal",
                 length=220, bg=COLORS["card"],
                 fg=COLORS["text"], troughcolor=COLORS["border"],
                 activebackground=COLORS["accent"],
                 highlightthickness=0).pack(side="left")

        # Detection section
        det_sec = section("🎯  Detection Settings")

        row4 = tk.Frame(det_sec, bg=COLORS["card"])
        row4.pack(fill="x", pady=6)
        label(row4, "Frame Skip:", 10,
              color=COLORS["text_dim"], width=15).pack(side="left", anchor="w")
        self._fskip_var = tk.IntVar(
            value=self.cfg.get("frame_skip", 10))
        tk.Scale(row4, variable=self._fskip_var,
                 from_=1, to=60, orient="horizontal",
                 length=220, bg=COLORS["card"],
                 fg=COLORS["text"], troughcolor=COLORS["border"],
                 activebackground=COLORS["accent"],
                 highlightthickness=0).pack(side="left")
        label(row4, "(higher = better performance)", 9,
              color=COLORS["text_dim"]).pack(side="left", padx=8)

        # Save button
        btn(wrapper, "💾  Save Settings",
            self._save_settings).pack(pady=16)

        label(wrapper, "Using local YOLOv11 plate detection & EasyOCR extraction.",
              9, color=COLORS["text_dim"]).pack()

    # ── Source toggle ─────────────────────────────────────────────────────────

    def _on_source_change(self):
        if self._src_var.get() == "video":
            self._file_frame.pack(fill="x", padx=12, pady=4)
        else:
            self._file_frame.pack_forget()

    def _browse_video(self):
        path = filedialog.askopenfilename(
            title="Select Video File",
            filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv *.wmv *.flv"),
                       ("All files", "*.*")],
        )
        if path:
            self._file_var.set(path)

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def _start(self):
        source = (self._cam_idx.get() if self._src_var.get() == "camera"
                  else self._file_var.get().strip(' \'"'))
        if self._src_var.get() == "video" and (not source):
            self._toast.show("Please select or paste a video file path first.",
                             "warning")
            return

        self._session_count = 0
        self._session_start = datetime.now()
        self._session_id = self.db.start_session(
            "camera" if isinstance(source, int) else "video"
        )
        self._running = True
        self._start_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._set_status("● Running…", COLORS["success"])
        self._start_pulse()

        # Show loading overlay
        self._loading.show("Initializing detection models…")

        self._processor = VideoProcessor(
            source       = source,
            frame_skip   = self._fskip_var.get(),
            conf_thresh  = self._conf_var.get(),
            min_len      = self._len_var.get(),
            on_detection = self._q_detection,
            on_error     = self._q_error,
            on_finished  = self._q_finished,
            on_progress  = self._q_progress,
        )
        self._processor.start()

    def _stop(self):
        # Guard against double-stop (user click + on_finished race)
        if not self._running:
            return
        self._running = False

        if self._processor:
            self._processor.stop()
            self._processor = None

        self._start_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._set_status("● Stopped", COLORS["warning"])
        self._stop_pulse()
        self._loading.hide()

        # Drain any leftover queue items
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

        if self._session_id:
            self.db.end_session(self._session_id, self._session_count)
            self._session_id = None
        self._session_start = None
        self._draw_placeholder()
        self._refresh_stats()
        self._refresh_log()

    # ── Status Helpers ────────────────────────────────────────────────────────

    def _set_status(self, text: str, color: str):
        """Actually update the status label text AND color."""
        self._status_var.set(text)
        self._status_label.config(fg=color)

    def _start_pulse(self):
        """Pulse the status dot while running."""
        self._stop_pulse()
        self._pulse_on = True
        self._do_pulse()

    def _do_pulse(self):
        if not self._running:
            return
        if self._pulse_on:
            self._status_label.config(fg=COLORS["success"])
        else:
            self._status_label.config(fg=COLORS["success_dim"])
        self._pulse_on = not self._pulse_on
        self._pulse_id = self.after(ANIM["pulse_interval_ms"], self._do_pulse)

    def _stop_pulse(self):
        if self._pulse_id:
            self.after_cancel(self._pulse_id)
            self._pulse_id = None

    # ── Queue callbacks (from detector thread) ────────────────────────────────

    def _q_detection(self, det):
        self._q.put(("detection", det))

    def _q_error(self, msg):
        self._q.put(("error", msg))

    def _q_finished(self):
        self._q.put(("finished", None))

    def _q_progress(self, msg):
        self._q.put(("progress", msg))

    def _poll_queue(self):
        # 1. Poll latest display frame directly from processor (no queue)
        if self._running and self._processor:
            frame = self._processor.get_latest_frame()
            if frame is not None:
                self._show_frame(frame)

        # 2. Process event queue (detections, errors, progress — NOT frames)
        try:
            for _ in range(10):
                kind, data = self._q.get_nowait()
                if kind == "detection":
                    self._handle_detection(data)
                elif kind == "error":
                    self._set_status(f"⚠  {data[:50]}", COLORS["danger"])
                    self._toast.show(str(data)[:80], "error")
                elif kind == "finished":
                    self.after_idle(self._stop)
                elif kind == "progress":
                    self._loading.update_text(str(data))
        except queue.Empty:
            pass
        self.after(ANIM["poll_ms"], self._poll_queue)

    # ── Frame display ─────────────────────────────────────────────────────────

    def _show_frame(self, frame_bgr):
        # Hide loading overlay on first frame
        self._loading.hide()

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)

        # Fit to canvas – use BILINEAR (fast) instead of LANCZOS (slow)
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw > 1 and ch > 1:
            pil = pil.resize((cw, ch), Image.BILINEAR)

        img = ImageTk.PhotoImage(pil)
        self._last_frame = img
        self._canvas.delete("all")
        self._canvas.create_image(
            cw // 2, ch // 2,
            image=img, anchor="center",
        )

    # ── Detection handling ────────────────────────────────────────────────────

    def _handle_detection(self, det: dict):
        self._session_count += 1
        ts = det.get("timestamp", datetime.now())

        self.db.add_detection(
            plate        = det["plate"],
            vehicle_type = det["vehicle_type"],
            confidence   = det["confidence"],
            plate_score  = det["plate_score"],
            source       = det.get("source", "camera"),
            snapshot_path= det.get("snapshot"),
            region       = det.get("region"),
            timestamp    = ts,
        )

        # Add to live mini-log
        icon  = VEHICLE_ICONS.get(det["vehicle_type"], "🚙")
        score = f"{det['plate_score']:.0%}"
        self._live_tree.insert(
            "", 0,
            values=(ts.strftime("%H:%M:%S"),
                    det["plate"],
                    f"{icon} {det['vehicle_type']}",
                    score,
                    det.get("source", "-")),
            tags=("odd" if len(self._live_tree.get_children()) % 2 else "even",),
        )
        # Keep only last 50 rows in mini-log
        children = self._live_tree.get_children()
        if len(children) > 50:
            self._live_tree.delete(children[-1])

        self._card_session.update_val(self._session_count)

        # Toast for first few detections
        if self._session_count <= 5:
            self._toast.show(
                f"Plate detected: {det['plate']}  ({score})", "success")

        # Debounced stats/log refresh
        self._schedule_stats_refresh()

    # ── Debounced refresh ─────────────────────────────────────────────────────

    def _schedule_stats_refresh(self):
        """Schedule a stats + log refresh, debounced to avoid overload."""
        if self._stats_timer_id is not None:
            self.after_cancel(self._stats_timer_id)
        self._stats_timer_id = self.after(
            ANIM["stats_debounce_ms"], self._do_deferred_refresh)

    def _do_deferred_refresh(self):
        self._stats_timer_id = None
        self._refresh_stats()
        self._refresh_log()

    # ── Stats refresh ─────────────────────────────────────────────────────────

    def _refresh_stats(self):
        stats = self.db.get_stats()
        self._card_total.update_val(stats["total"])
        self._card_today.update_val(stats["today"])
        self._card_unique.update_val(stats["unique_plates"])

        self._footer_db_var.set(f"{stats['total']} records in database")

        by_type = stats.get("by_type", {})
        for vtype, lbl in self._type_labels.items():
            cnt = by_type.get(vtype, 0)
            lbl.config(text=f"{vtype}\n{cnt}")

    # ── Log refresh ───────────────────────────────────────────────────────────

    def _refresh_log(self):
        q = self._search_entry.get_value() if hasattr(self, '_search_entry') else ""
        rows = self.db.search(q, 500) if q else self.db.get_recent(500)
        self._log_count_var.set(f"{len(rows)} records")

        self._log_tree.delete(*self._log_tree.get_children())
        for idx, r in enumerate(rows):
            icon = VEHICLE_ICONS.get(r["vehicle_type"], "🚙")
            tag = "odd" if idx % 2 else "even"
            self._log_tree.insert(
                "", "end",
                iid=str(r["id"]),
                values=(
                    r["id"],
                    r["timestamp"],
                    r["plate"],
                    f"{icon} {r['vehicle_type']}",
                    f"{r['plate_score']:.0%}",
                    f"{r['confidence']:.0%}",
                    r.get("region") or "-",
                    r["source"],
                ),
                tags=(tag,),
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _setup_treeview(self, tv: ttk.Treeview, cols, widths=None):
        """Configure columns and alternating row tags for a treeview."""
        for i, col in enumerate(cols):
            w = widths[i] if widths else 100
            tv.heading(col, text=col,
                       command=lambda c=col, t=tv: self._sort_tree(t, c, False))
            tv.column(col, width=w, anchor="w")

        # Alternating row colors
        tv.tag_configure("even", background=COLORS["row_even"])
        tv.tag_configure("odd",  background=COLORS["row_odd"])

    def _sort_tree(self, tv, col, reverse):
        items = [(tv.set(k, col), k) for k in tv.get_children("")]
        items.sort(reverse=reverse)
        for i, (_, k) in enumerate(items):
            tv.move(k, "", i)
        tv.heading(col, command=lambda: self._sort_tree(tv, col, not reverse))

    def _save_settings(self):
        self.cfg["easyocr_confidence"] = self._conf_var.get()
        self.cfg["easyocr_min_length"] = self._len_var.get()
        self.cfg["frame_skip"] = self._fskip_var.get()
        save_config(self.cfg)
        self._toast.show("Settings saved successfully!", "success")

    def _export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=f"vline_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        if not path:
            return
        rows = self.db.get_recent(10_000)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else [])
            w.writeheader()
            w.writerows(rows)
        self._toast.show(f"Exported {len(rows)} records to CSV", "success")

    def _delete_selected(self):
        selected = self._log_tree.selection()
        if not selected:
            return
        if messagebox.askyesno("Delete", f"Delete {len(selected)} record(s)?"):
            for iid in selected:
                self.db.delete_detection(int(iid))
            self._refresh_log()
            self._refresh_stats()
            self._toast.show(f"Deleted {len(selected)} record(s)", "info")

    def _clear_db(self):
        if messagebox.askyesno(
                "Clear All",
                "⚠️  Delete ALL detection records?\nThis cannot be undone."):
            self.db.clear_all()
            self._live_tree.delete(*self._live_tree.get_children())
            self._refresh_log()
            self._refresh_stats()
            self._toast.show("All records cleared", "warning")

    def on_closing(self):
        if self._running:
            self._stop()
        self.destroy()
        import sys
        sys.exit(0)
