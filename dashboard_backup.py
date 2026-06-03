"""
VLINE – Dashboard UI
Vehicle Licence Interpretation and Number Extraction
Full Tkinter-based dashboard with live camera / video feed, detection log,
stats panel, settings, and database management.
"""

import io
import os
import csv
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageTk

from config import (
    COLORS, VEHICLE_ICONS,
    load_config, save_config, DISPLAY_WIDTH, DISPLAY_HEIGHT,
)
from database import VlineDatabase
from detector import VideoProcessor


# ─── Small helper widgets ─────────────────────────────────────────────────────

def _hex(c): return c  # colours already in hex from config


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


def btn(parent, text, cmd, color=None, fg="white", width=16, **kw):
    b = tk.Button(
        parent, text=text, command=cmd,
        bg=color or COLORS["accent"], fg=fg,
        font=("Segoe UI", 10, "bold"),
        relief="flat", cursor="hand2", width=width,
        activebackground=COLORS["accent2"], activeforeground="white",
        padx=8, pady=6, **kw
    )
    return b


# ─── Stats card widget ────────────────────────────────────────────────────────

class StatCard(tk.Frame):
    def __init__(self, parent, title, value, icon, color):
        super().__init__(parent, bg=COLORS["card"],
                         highlightbackground=color, highlightthickness=2)
        tk.Label(self, text=icon, font=("Segoe UI", 22),
                 bg=COLORS["card"], fg=color).pack(pady=(12, 0))
        self._val = tk.StringVar(value=str(value))
        tk.Label(self, textvariable=self._val, font=("Segoe UI", 18, "bold"),
                 bg=COLORS["card"], fg=color).pack()
        tk.Label(self, text=title, font=("Segoe UI", 9),
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(pady=(0, 12))

    def update_val(self, v):
        self._val.set(str(v))


# ─── Main Application ─────────────────────────────────────────────────────────

class VlineApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("VLINE  ·  Vehicle Licence Interpretation and Number Extraction")
        self.configure(bg=COLORS["bg"])
        self.state("zoomed")           # maximise on Windows; on Linux use below
        try: self.attributes("-zoomed", True)
        except Exception: pass

        self.cfg       = load_config()
        self.db        = VlineDatabase()
        self._processor: Optional[VideoProcessor] = None
        self._session_id: Optional[int] = None
        self._session_count = 0
        self._q: queue.Queue = queue.Queue()  # thread → GUI
        self._last_frame: Optional[ImageTk.PhotoImage] = None
        self._running = False

        self._build_ui()
        self._refresh_stats()
        self._refresh_log()
        self._poll_queue()

    # ── Build layout ──────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=COLORS["header_bg"], height=56)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🚘  VLINE",
                 font=("Segoe UI", 18, "bold"),
                 fg=COLORS["accent"], bg=COLORS["header_bg"]).pack(side="left", padx=20, pady=10)
        tk.Label(hdr, text="Vehicle Licence Interpretation and Number Extraction",
                 font=("Segoe UI", 10),
                 fg=COLORS["text_dim"], bg=COLORS["header_bg"]).pack(side="left")
        self._status_var = tk.StringVar(value="● Idle")
        tk.Label(hdr, textvariable=self._status_var,
                 font=("Segoe UI", 10, "bold"),
                 fg=COLORS["text_dim"], bg=COLORS["header_bg"]).pack(side="right", padx=20)

        # Notebook (tabs)
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("VLINE.TNotebook",
                        background=COLORS["bg"], borderwidth=0)
        style.configure("VLINE.TNotebook.Tab",
                        background=COLORS["sidebar"],
                        foreground=COLORS["text_dim"],
                        font=("Segoe UI", 10, "bold"),
                        padding=[18, 8])
        style.map("VLINE.TNotebook.Tab",
                  background=[("selected", COLORS["accent"])],
                  foreground=[("selected", "white")])

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

    # ── Tab 1: Live Detection ─────────────────────────────────────────────────

    def _build_live_tab(self):
        outer = self._tab_live
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # Left sidebar ─────────────────────────────────────────────────────
        sidebar = tk.Frame(outer, bg=COLORS["sidebar"], width=280)
        sidebar.grid(row=0, column=0, sticky="ns", padx=0, pady=0)
        sidebar.pack_propagate(False)

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
                font=("Segoe UI", 10), indicatoron=True,
                command=self._on_source_change,
            )
            rb.pack(anchor="w", pady=3, padx=6)

        # Video file selector
        self._file_frame = tk.Frame(sidebar, bg=COLORS["sidebar"])
        self._file_frame.pack(fill="x", padx=12, pady=4)
        self._file_var = tk.StringVar(value="")
        btn(self._file_frame, "📂  Browse Video", self._browse_video,
            color=COLORS["card"], fg=COLORS["text"], width=22).pack(fill="x", pady=(0, 4))
        tk.Entry(self._file_frame, textvariable=self._file_var,
                 bg=COLORS["card"], fg=COLORS["text"],
                 insertbackground=COLORS["text"],
                 font=("Segoe UI", 9), relief="flat", width=30).pack(fill="x")
        self._file_frame.pack_forget()  # hidden until "video" selected

        ttk.Separator(sidebar, orient="horizontal").pack(fill="x", padx=12, pady=12)

        # Camera index
        cam_row = tk.Frame(sidebar, bg=COLORS["sidebar"])
        cam_row.pack(fill="x", padx=12, pady=4)
        label(cam_row, "Camera Index:", 9, color=COLORS["text_dim"]).pack(side="left")
        self._cam_idx = tk.IntVar(value=0)
        tk.Spinbox(cam_row, from_=0, to=9, textvariable=self._cam_idx,
                   width=4, bg=COLORS["card"], fg=COLORS["text"],
                   buttonbackground=COLORS["border"],
                   font=("Segoe UI", 10), relief="flat").pack(side="right")

        ttk.Separator(sidebar, orient="horizontal").pack(fill="x", padx=12, pady=12)

        # Controls
        label(sidebar, "CONTROLS", 9, bold=True,
              color=COLORS["text_dim"]).pack(anchor="w", padx=18, pady=(0, 8))

        self._start_btn = btn(sidebar, "▶  Start Detection",
                              self._start, color=COLORS["success"], width=24)
        self._start_btn.pack(padx=12, pady=4, fill="x")

        self._stop_btn = btn(sidebar, "⏹  Stop",
                             self._stop, color=COLORS["danger"], width=24)
        self._stop_btn.pack(padx=12, pady=4, fill="x")
        self._stop_btn.config(state="disabled")

        ttk.Separator(sidebar, orient="horizontal").pack(fill="x", padx=12, pady=12)

        # Stats cards
        label(sidebar, "SESSION STATS", 9, bold=True,
              color=COLORS["text_dim"]).pack(anchor="w", padx=18, pady=(0, 8))

        cards_frame = tk.Frame(sidebar, bg=COLORS["sidebar"])
        cards_frame.pack(fill="x", padx=8)
        cards_frame.columnconfigure(0, weight=1)
        cards_frame.columnconfigure(1, weight=1)

        self._card_total   = StatCard(cards_frame, "Total", 0, "🚘", COLORS["accent"])
        self._card_today   = StatCard(cards_frame, "Today", 0, "📅", COLORS["success"])
        self._card_unique  = StatCard(cards_frame, "Unique", 0, "🔑", COLORS["warning"])
        self._card_session = StatCard(cards_frame, "Session", 0, "⏱", COLORS["accent2"])

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

        self._canvas = tk.Canvas(video_card, bg="#000000", cursor="crosshair",
                                 highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._draw_placeholder()

        # Recent detections mini-log
        log_card = make_card(right)
        log_card.grid(row=1, column=0, sticky="nsew")
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)
        label(log_card, " Recent Detections", 10, bold=True,
              color=COLORS["accent"]).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 0))

        cols = ("Time", "Plate", "Type", "Score", "Source")
        self._live_tree = ttk.Treeview(
            log_card, columns=cols, show="headings", height=6,
            selectmode="browse",
        )
        self._style_treeview(self._live_tree, cols,
                             widths=[90, 120, 110, 70, 80])
        self._live_tree.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

        vsb = ttk.Scrollbar(log_card, orient="vertical",
                            command=self._live_tree.yview)
        vsb.grid(row=1, column=1, sticky="ns", pady=6)
        self._live_tree.configure(yscrollcommand=vsb.set)

    def _draw_placeholder(self):
        self._canvas.delete("all")
        self._canvas.create_rectangle(
            0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT, fill="#0a0c12", outline="")
        self._canvas.create_text(
            DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2,
            text="📷  Press  ▶ Start Detection  to begin",
            fill=COLORS["text_dim"], font=("Segoe UI", 14),
        )

    # ── Tab 2: Detection Log ──────────────────────────────────────────────────

    def _build_log_tab(self):
        outer = self._tab_log
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        # Toolbar
        tb = tk.Frame(outer, bg=COLORS["bg"])
        tb.grid(row=0, column=0, sticky="ew", padx=10, pady=10)

        label(tb, "Search:", 10, color=COLORS["text_dim"]).pack(side="left", padx=(0, 6))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._refresh_log())
        tk.Entry(tb, textvariable=self._search_var,
                 bg=COLORS["card"], fg=COLORS["text"],
                 insertbackground=COLORS["text"],
                 font=("Segoe UI", 10), relief="flat", width=25).pack(side="left")

        btn(tb, "📤  Export CSV", self._export_csv,
            color=COLORS["success"], width=14).pack(side="left", padx=8)
        btn(tb, "🗑  Clear All", self._clear_db,
            color=COLORS["danger"], width=12).pack(side="left")

        self._log_count_var = tk.StringVar(value="0 records")
        label(tb, "", color=COLORS["text_dim"]).pack(side="right")
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
        self._style_treeview(self._log_tree, cols,
                             widths=[50, 150, 120, 110, 90, 90, 70, 80])
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
                     activebackground=COLORS["accent"])
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
                     font=("Segoe UI", 16)).pack(side="left", padx=6, pady=4)
            lbl = tk.Label(f, text=f"{vtype}\n0",
                           bg=COLORS["card"], fg=COLORS["text"],
                           font=("Segoe UI", 8), justify="center")
            lbl.pack(side="left", padx=(0, 8), pady=4)
            self._type_labels[vtype] = lbl

    # ── Tab 3: Settings ───────────────────────────────────────────────────────

    def _build_settings_tab(self):
        outer = self._tab_cfg
        outer.columnconfigure(0, weight=1)

        wrapper = tk.Frame(outer, bg=COLORS["bg"])
        wrapper.pack(expand=True, fill="both", padx=60, pady=30)

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
        row1.pack(fill="x", pady=4)
        label(row1, "Min Confidence:", 10, color=COLORS["text_dim"], width=15).pack(side="left", anchor="w")
        self._conf_var = tk.DoubleVar(value=self.cfg.get("easyocr_confidence", 0.3))
        tk.Scale(row1, variable=self._conf_var,
                 from_=0.0, to=1.0, resolution=0.05, orient="horizontal",
                 length=200, bg=COLORS["card"],
                 fg=COLORS["text"], troughcolor=COLORS["border"],
                 highlightthickness=0).pack(side="left")

        row2 = tk.Frame(ocr_sec, bg=COLORS["card"])
        row2.pack(fill="x", pady=4)
        label(row2, "Min Plate Length:", 10, color=COLORS["text_dim"], width=15).pack(side="left", anchor="w")
        self._len_var = tk.IntVar(value=self.cfg.get("easyocr_min_length", 4))
        tk.Scale(row2, variable=self._len_var,
                 from_=1, to=10, orient="horizontal",
                 length=200, bg=COLORS["card"],
                 fg=COLORS["text"], troughcolor=COLORS["border"],
                 highlightthickness=0).pack(side="left")

        # Detection section
        det_sec = section("🎯  Detection Settings")

        row4 = tk.Frame(det_sec, bg=COLORS["card"])
        row4.pack(fill="x", pady=4)
        label(row4, "Frame Skip:", 10, color=COLORS["text_dim"], width=15).pack(side="left", anchor="w")
        self._fskip_var = tk.IntVar(value=self.cfg.get("frame_skip", 10))
        tk.Scale(row4, variable=self._fskip_var,
                 from_=1, to=60, orient="horizontal",
                 length=200, bg=COLORS["card"],
                 fg=COLORS["text"], troughcolor=COLORS["border"],
                 highlightthickness=0).pack(side="left")
        label(row4, "(higher = better performance)", 9,
              color=COLORS["text_dim"]).pack(side="left", padx=8)

        # Save button
        btn(wrapper, "💾  Save Settings", self._save_settings,
            color=COLORS["success"], width=20).pack(pady=16)

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
        source = (0 if self._src_var.get() == "camera"
                  else self._file_var.get().strip(' \'"'))
        if self._src_var.get() == "video" and (not source):
            messagebox.showerror("No File", "Please select or paste a video file path first.")
            return

        # removed obsolete config parse

        self._session_count = 0
        self._session_id = self.db.start_session(
            "camera" if source == 0 else "video"
        )
        self._running = True
        self._start_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._status_var.set("● Running…")
        self._status_var_color(COLORS["success"])

        self._processor = VideoProcessor(
            source        = source,
            frame_skip    = self._fskip_var.get(),
            conf_thresh   = self._conf_var.get(),
            min_len       = self._len_var.get(),
            on_frame      = self._q_frame,
            on_detection  = self._q_detection,
            on_error      = self._q_error,
            on_finished   = self._q_finished,
        )
        self._processor.start()

    def _stop(self):
        if self._processor:
            self._processor.stop()
            self._processor = None
        self._running = False
        self._start_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._status_var.set("● Stopped")
        self._status_var_color(COLORS["warning"])
        if self._session_id:
            self.db.end_session(self._session_id, self._session_count)
            self._session_id = None
        self._draw_placeholder()
        self._refresh_stats()
        self._refresh_log()

    # ── Queue callbacks (from detector thread) ────────────────────────────────

    def _q_frame(self, frame):
        self._q.put(("frame", frame))

    def _q_detection(self, det):
        self._q.put(("detection", det))

    def _q_error(self, msg):
        self._q.put(("error", msg))

    def _q_finished(self):
        self._q.put(("finished", None))

    def _poll_queue(self):
        try:
            while True:
                kind, data = self._q.get_nowait()
                if kind == "frame":
                    self._show_frame(data)
                elif kind == "detection":
                    self._handle_detection(data)
                elif kind == "error":
                    self._status_var.set(f"⚠  {data[:60]}")
                    self._status_var_color(COLORS["danger"])
                elif kind == "finished":
                    self.after_idle(self._stop)
        except queue.Empty:
            pass
        self.after(30, self._poll_queue)

    # ── Frame display ─────────────────────────────────────────────────────────

    def _show_frame(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)

        # Fit to canvas
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw > 1 and ch > 1:
            pil.thumbnail((cw, ch), Image.LANCZOS)

        img = ImageTk.PhotoImage(pil)
        self._last_frame = img
        self._canvas.delete("all")
        self._canvas.create_image(
            self._canvas.winfo_width() // 2,
            self._canvas.winfo_height() // 2,
            image=img, anchor="center",
        )

    # ── Detection handling ────────────────────────────────────────────────────

    def _handle_detection(self, det: dict):
        self._session_count += 1
        ts = det.get("timestamp", datetime.now())

        rec_id = self.db.add_detection(
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
        )
        # Keep only last 50 rows in mini-log
        children = self._live_tree.get_children()
        if len(children) > 50:
            self._live_tree.delete(children[-1])

        self._card_session.update_val(self._session_count)
        self._refresh_stats()
        self._refresh_log()

    # ── Stats refresh ─────────────────────────────────────────────────────────

    def _refresh_stats(self):
        stats = self.db.get_stats()
        self._card_total.update_val(stats["total"])
        self._card_today.update_val(stats["today"])
        self._card_unique.update_val(stats["unique_plates"])

        by_type = stats.get("by_type", {})
        for vtype, lbl in self._type_labels.items():
            cnt = by_type.get(vtype, 0)
            lbl.config(text=f"{vtype}\n{cnt}")

    # ── Log refresh ───────────────────────────────────────────────────────────

    def _refresh_log(self):
        q = self._search_var.get().strip()
        rows = self.db.search(q, 500) if q else self.db.get_recent(500)
        self._log_count_var.set(f"{len(rows)} records")

        self._log_tree.delete(*self._log_tree.get_children())
        for r in rows:
            icon = VEHICLE_ICONS.get(r["vehicle_type"], "🚙")
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
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _style_treeview(self, tv: ttk.Treeview, cols, widths=None):
        style = ttk.Style()
        style.configure("Treeview",
                        background=COLORS["card"],
                        foreground=COLORS["text"],
                        rowheight=26,
                        fieldbackground=COLORS["card"],
                        borderwidth=0,
                        font=("Segoe UI", 9))
        style.configure("Treeview.Heading",
                        background=COLORS["sidebar"],
                        foreground=COLORS["accent"],
                        font=("Segoe UI", 9, "bold"),
                        relief="flat")
        style.map("Treeview",
                  background=[("selected", COLORS["accent"])],
                  foreground=[("selected", "white")])
        for i, col in enumerate(cols):
            w = widths[i] if widths else 100
            tv.heading(col, text=col,
                       command=lambda c=col, t=tv: self._sort_tree(t, c, False))
            tv.column(col, width=w, anchor="w")

    def _sort_tree(self, tv, col, reverse):
        items = [(tv.set(k, col), k) for k in tv.get_children("")]
        items.sort(reverse=reverse)
        for i, (_, k) in enumerate(items):
            tv.move(k, "", i)
        tv.heading(col, command=lambda: self._sort_tree(tv, col, not reverse))

    def _toggle_sdk_url(self):
        pass

    def _status_var_color(self, color):
        # Find status label in header – patch it via trace
        pass  # colour is conveyed by text prefix (●, ⚠, etc.)

    def _save_settings(self):
        self.cfg["easyocr_confidence"] = self._conf_var.get()
        self.cfg["easyocr_min_length"] = self._len_var.get()
        self.cfg["frame_skip"] = self._fskip_var.get()
        save_config(self.cfg)
        messagebox.showinfo("VLINE", "✅  Settings saved successfully!")

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
        messagebox.showinfo("VLINE", f"✅  Exported {len(rows)} records to:\n{path}")

    def _delete_selected(self):
        selected = self._log_tree.selection()
        if not selected:
            return
        if messagebox.askyesno("Delete", f"Delete {len(selected)} record(s)?"):
            for iid in selected:
                self.db.delete_detection(int(iid))
            self._refresh_log()
            self._refresh_stats()

    def _clear_db(self):
        if messagebox.askyesno("Clear All", "⚠️  Delete ALL detection records?\nThis cannot be undone."):
            self.db.clear_all()
            self._live_tree.delete(*self._live_tree.get_children())
            self._refresh_log()
            self._refresh_stats()

    def on_closing(self):
        if self._running:
            self._stop()
        self.destroy()
