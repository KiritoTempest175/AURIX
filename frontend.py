#!/usr/bin/env python3
"""
AURIX // Interface — Desktop Edition
--------------------------------------
A self-contained Tkinter desktop app: live date/time, real CPU/RAM/CPU-temp
readings, a rotating radar core, and a simple chat-style command box with a
mic mute/unmute toggle.

Requirements: Python 3.8+, Tkinter (ships with the standard CPython
installer on Windows/macOS; on Linux install `python3-tk` if it's missing,
e.g. `sudo apt install python3-tk`).

For LIVE cpu / ram / temperature readings, also install psutil:
    pip install psutil
Without psutil the app still runs, but those three fields fall back to
demo values and say so on screen.

Run:
    python3 frontend.py
"""

from __future__ import annotations

import logging
import math
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from typing import Optional

# Ensure project root is on sys.path for subsystem imports
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# UTF-8 safety for Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aurix.frontend")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ── Backend Subsystem Imports (graceful fallback if unavailable) ──────────

# Gemma 3n E4B Inference Engine
try:
    from ai_engine.inference.gemma_e4b import get_default_gemma_runner
    HAS_GEMMA = True
except ImportError as e:
    logger.warning("Gemma inference engine unavailable: %s", e)
    HAS_GEMMA = False

# Student-5B QLoRA Training Controller
try:
    from ai_engine.training.student_qlora_loop import get_default_student_trainer
    HAS_TRAINER = True
except ImportError as e:
    logger.warning("Student trainer unavailable: %s", e)
    HAS_TRAINER = False

# Checkpoint Manager
try:
    from ai_engine.training.checkpoint_manager import get_default_checkpoint_manager
    HAS_CHECKPOINT = True
except ImportError as e:
    logger.warning("Checkpoint manager unavailable: %s", e)
    HAS_CHECKPOINT = False

# Telemetry Ingestion Daemon
try:
    from data_pipeline.storage.telemetry_daemon import get_default_telemetry_daemon
    HAS_TELEMETRY = True
except ImportError as e:
    logger.warning("Telemetry daemon unavailable: %s", e)
    HAS_TELEMETRY = False

# Audio Subsystem — Voice Pipeline (STT, TTS, Wake-Word, State Machine)
try:
    from native_ui.audio import (
        AssistantState,
        get_assistant_state_machine,
        get_default_wakeword_detector,
        is_cancel_phrase,
        record_audio,
        speak,
        transcribe_audio,
    )
    HAS_AUDIO = True
except ImportError as e:
    logger.warning("Audio subsystem unavailable: %s", e)
    HAS_AUDIO = False

# AI Brain — Central Intelligence Dispatcher (app control, shell exec, etc.)
try:
    from ai_brain import BrainDispatcher
    HAS_BRAIN = True
except ImportError as e:
    logger.warning("AI Brain dispatcher unavailable: %s", e)
    BrainDispatcher = None
    HAS_BRAIN = False

# Rust Core Engine (Power Governor, Hardware Monitor)
try:
    import core_engine
    if not hasattr(core_engine, "SystemState"):
        raise ImportError(
            "core_engine imported as namespace package — compiled .pyd not found."
        )
    HAS_RUST_CORE = True
except ImportError as e:
    logger.warning("Rust core_engine not available: %s", e)
    core_engine = None
    HAS_RUST_CORE = False

# ---------------------------------------------------------------- palette --
BG = "#050b10"
PANEL_BG = "#081319"
LINE = "#1c3a42"
LINE_BRIGHT = "#3f7d8c"
CYAN = "#5fd8e8"
CYAN_BRIGHT = "#9df3ff"
CYAN_DIM = "#2c5a66"
TEXT_DIM = "#5a7b83"
AMBER = "#e8b95f"
GREEN = "#3ee88a"
RED = "#e85f5f"
FONT = "Consolas"
if "Consolas" not in ():
    pass  # Consolas is used on Windows; fallback handled below at runtime

# Pre-cached font tuples — avoids re-allocating in animation hot paths
_FONT_CACHE: dict[tuple, tuple] = {}


def mono(size, weight="normal"):
    key = (size, weight)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = (FONT, size, weight)
    return _FONT_CACHE[key]


# ============================================================== WIDGETS ===

class Panel(tk.Frame):
    """A bordered console panel with corner brackets and a header row."""

    def __init__(self, master, tag, title, sub, **kw):
        super().__init__(master, bg=PANEL_BG, highlightthickness=1,
                          highlightbackground=LINE, highlightcolor=LINE, **kw)
        head = tk.Frame(self, bg=PANEL_BG)
        head.pack(fill="x", padx=14, pady=(10, 6))

        left = tk.Frame(head, bg=PANEL_BG)
        left.pack(side="left")
        tk.Label(left, text=tag, bg=PANEL_BG, fg=TEXT_DIM,
                  font=mono(8)).pack(anchor="w")
        tk.Label(left, text=title, bg=PANEL_BG, fg=CYAN_BRIGHT,
                  font=mono(11, "bold")).pack(anchor="w")

        tk.Label(head, text=sub, bg=PANEL_BG, fg=TEXT_DIM,
                  font=mono(8)).pack(side="right", anchor="n")

        rule = tk.Frame(self, bg=LINE, height=1)
        rule.pack(fill="x", padx=14, pady=(0, 10))

        self.body = tk.Frame(self, bg=PANEL_BG)
        self.body.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        # corner brackets drawn on a thin canvas overlay
        self._corners = tk.Canvas(self, bg=PANEL_BG, highlightthickness=0,
                                   width=1, height=1)

    def draw_corners(self):
        c = tk.Canvas(self, bg=PANEL_BG, highlightthickness=0, bd=0)
        c.place(relx=0, rely=0, relwidth=1, relheight=1)
        tk.Widget.lower(c)

        def redraw(event=None):
            c.delete("all")
            w = c.winfo_width()
            h = c.winfo_height()
            s = 9
            c.create_line(0, s, 0, 0, w=1, fill=CYAN_BRIGHT)
            c.create_line(0, 0, s, 0, w=1, fill=CYAN_BRIGHT)
            c.create_line(w - s, h, w, h, w=1, fill=CYAN_BRIGHT)
            c.create_line(w, h - s, w, h, w=1, fill=CYAN_BRIGHT)

        self.bind("<Configure>", redraw)


class Bar(tk.Canvas):
    """A thin horizontal meter bar (0-100)."""

    def __init__(self, master, value=0, height=5, **kw):
        super().__init__(master, height=height, bg="#0d1a1f",
                          highlightthickness=0, **kw)
        self.value = value
        self.bind("<Configure>", lambda e: self.redraw())

    def set(self, value):
        self.value = max(0, min(100, value))
        self.redraw()

    def redraw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1:
            return
        fw = w * (self.value / 100.0)
        self.create_rectangle(0, 0, w, h, fill="#0d1a1f", outline="")
        if fw > 0:
            self.create_rectangle(0, 0, fw, h, fill=CYAN, outline="")
            self.create_rectangle(max(0, fw - 3), 0, fw, h,
                                   fill=CYAN_BRIGHT, outline="")


# ============================================================ MAIN APP ====

class JarvisApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AURIX // INTERFACE")
        self.configure(bg=BG)
        self.geometry("1440x900")
        self.minsize(1180, 760)

        # graceful font fallback across platforms
        global FONT
        try:
            self.option_add("*Font", (FONT, 10))
        except tk.TclError:
            FONT = "Courier New"

        self.cpu = 24
        self.mem = 48
        self.power = 98
        self.listening = False
        self.mic_muted = False
        self._current_assistant_state = AssistantState.SLEEPING if HAS_AUDIO else None
        self._conversation_active = False
        self._wave_phase = 0.0

        if HAS_PSUTIL:
            self.mem_total_gb = psutil.virtual_memory().total / (1024 ** 3)
            psutil.cpu_percent(interval=None)  # prime the internal sampler
        else:
            self.mem_total_gb = 12.0

        # ── Backend handles (lazy-loaded on first use to save RAM) ────
        self._response_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._voice_input_queue: queue.Queue[str] = queue.Queue()
        self._gemma_runner = None
        self._student_trainer = None
        self._checkpoint_manager = None
        self._telemetry = None
        self._state_machine = None
        self._wakeword = None
        self._system_state = None
        self._backends_initialized = False

        # ── AI Brain dispatcher (app control, shell exec, etc.) ───────
        self._brain = BrainDispatcher() if HAS_BRAIN else None

        # Only init lightweight subsystems at startup (core_engine, wakeword)
        self._init_lightweight_backends()

        self._build_header()
        self._build_main()

        self.after(250, self._tick_datetime)
        self.after(400, self._tick_system_stats)
        self.after(66, self._tick_radar)  # ~15 FPS instead of 25
        self.after(150, self._poll_response_queue)

    # ── Lazy Properties — backends loaded only when first accessed ───
    @property
    def gemma_runner(self):
        if self._gemma_runner is None and HAS_GEMMA:
            try:
                logger.info("Lazy-loading Gemma 3n E4B Inference Engine...")
                self._gemma_runner = get_default_gemma_runner()
                logger.info("Gemma E4B engine ready.")
            except Exception as e:
                logger.error("Failed to initialize Gemma runner: %s", e)
        return self._gemma_runner

    @property
    def student_trainer(self):
        if self._student_trainer is None and HAS_TRAINER:
            try:
                self._student_trainer = get_default_student_trainer()
            except Exception as e:
                logger.error("Failed to initialize Student trainer: %s", e)
        return self._student_trainer

    @property
    def checkpoint_manager(self):
        if self._checkpoint_manager is None and HAS_CHECKPOINT:
            try:
                self._checkpoint_manager = get_default_checkpoint_manager()
            except Exception as e:
                logger.error("Failed to initialize Checkpoint manager: %s", e)
        return self._checkpoint_manager

    @property
    def telemetry(self):
        if self._telemetry is None and HAS_TELEMETRY:
            try:
                self._telemetry = get_default_telemetry_daemon()
            except Exception as e:
                logger.error("Failed to initialize Telemetry daemon: %s", e)
        return self._telemetry

    @property
    def state_machine(self):
        return self._state_machine

    @property
    def wakeword(self):
        return self._wakeword

    @property
    def system_state(self):
        return self._system_state

    # ── Lightweight Init (startup) ───────────────────────────────────
    def _init_lightweight_backends(self):
        """Initialize only lightweight subsystems at startup. Heavy backends
        (Gemma, trainer, checkpoint manager) are lazy-loaded on first use."""
        # Voice State Machine + Wake-Word Detector (lightweight)
        if HAS_AUDIO:
            try:
                logger.info("Initializing Assistant State Machine...")
                self._state_machine = get_assistant_state_machine()
                self._state_machine.on_state_change = self._on_assistant_state_change

                logger.info("Initializing Wake-Word Detector ('Luna')...")
                self._wakeword = get_default_wakeword_detector()
                self._wakeword.on_wake_detected = self._handle_wakeword_triggered
                self._wakeword.start_listening()
            except Exception as e:
                logger.error("Failed to initialize audio subsystem: %s", e)

        # Rust Core Engine State (lightweight C extension)
        if HAS_RUST_CORE:
            try:
                self._system_state = core_engine.SystemState()
                core_engine.start_hardware_monitor()
                logger.info("Rust Hardware Power Governor started.")
            except Exception as e:
                logger.warning("Could not start hardware monitor: %s", e)

        logger.info("AURIX Frontend — lightweight subsystems initialized. Heavy backends load on demand.")

    # ------------------------------------------------------------- HEADER --
    def _build_header(self):
        header = tk.Frame(self, bg=BG, height=64)
        header.pack(fill="x", padx=18, pady=(14, 8))

        # brand
        brand = tk.Frame(header, bg=BG)
        brand.pack(side="left")
        mark = tk.Canvas(brand, width=34, height=34, bg=BG,
                          highlightthickness=0)
        mark.pack(side="left", padx=(0, 12))
        mark.create_oval(2, 2, 32, 32, outline=CYAN_BRIGHT, width=1)
        mark.create_oval(8, 8, 26, 26, outline=CYAN_DIM, width=1)
        mark.create_rectangle(15, 15, 19, 19, fill=CYAN_BRIGHT, outline="")

        titlewrap = tk.Frame(brand, bg=BG)
        titlewrap.pack(side="left")
        tk.Label(titlewrap, text="A U R I X", bg=BG, fg=CYAN_BRIGHT,
                  font=mono(17, "bold")).pack(anchor="w")
        tk.Label(titlewrap, text="ADVANCED UNIFIED RESPONSE INTELLIGENCE X",
                  bg=BG, fg=TEXT_DIM, font=mono(8)).pack(anchor="w")

        # status cluster
        status = tk.Frame(header, bg=BG)
        status.pack(side="left", padx=60)

        s1 = tk.Frame(status, bg=BG)
        s1.pack(side="left", padx=20)
        tk.Label(s1, text="SYSTEM STATUS", bg=BG, fg=TEXT_DIM,
                  font=mono(8)).pack(anchor="w")
        row = tk.Frame(s1, bg=BG)
        row.pack(anchor="w")
        self.status_dot = tk.Canvas(row, width=8, height=8, bg=BG,
                                     highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 6))
        self.status_dot.create_oval(0, 0, 8, 8, fill=TEXT_DIM, outline="")
        self.status_lbl = tk.Label(row, text="STANDBY", bg=BG, fg=TEXT_DIM,
                                   font=mono(12, "bold"))
        self.status_lbl.pack(side="left")

        # right side: user chip only
        right = tk.Frame(header, bg=BG)
        right.pack(side="right")

        chip = tk.Frame(right, bg=BG, highlightthickness=1,
                         highlightbackground=LINE)
        chip.pack(side="right")
        av = tk.Canvas(chip, width=24, height=24, bg=PANEL_BG,
                        highlightthickness=0)
        av.pack(side="left", padx=6, pady=4)
        av.create_oval(2, 2, 22, 22, fill=CYAN_DIM, outline=CYAN_BRIGHT)
        tk.Label(chip, text="T. STARK", bg=BG, fg=CYAN_BRIGHT,
                  font=mono(10, "bold")).pack(side="left", padx=(0, 14))

        rule = tk.Frame(self, bg=LINE, height=1)
        rule.pack(fill="x", padx=18)

    # --------------------------------------------------------------- MAIN --
    def _build_main(self):
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=18, pady=14)

        main.columnconfigure(0, weight=0, minsize=300)
        main.columnconfigure(1, weight=1)
        main.columnconfigure(2, weight=0, minsize=300)
        main.rowconfigure(0, weight=1)

        left = tk.Frame(main, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        center = tk.Frame(main, bg=BG)
        center.grid(row=0, column=1, sticky="nsew")
        right = tk.Frame(main, bg=BG)
        right.grid(row=0, column=2, sticky="nsew", padx=(16, 0))

        self._build_left(left)
        self._build_center(center)
        self._build_right(right)

    # ------------------------------------------------------------- LEFT ---
    def _build_left(self, parent):
        dt = Panel(parent, "SYSTEM //", "DATE / TIME", "LOCAL CLOCK")
        dt.pack(fill="x", pady=(0, 14))
        dt.draw_corners()

        self.date_lbl = tk.Label(dt.body, text="----------, -- ---- ----",
                                  bg=PANEL_BG, fg="#9fd3dd", font=mono(10))
        self.date_lbl.pack(anchor="w")
        self.time_lbl = tk.Label(dt.body, text="--:--:--", bg=PANEL_BG,
                                  fg=CYAN_BRIGHT, font=mono(28, "bold"))
        self.time_lbl.pack(anchor="w", pady=(4, 0))

        res = Panel(parent, "SYSTEM //", "SYSTEM RESOURCES", "RT-MONITOR")
        res.pack(fill="both", expand=True)
        res.draw_corners()

        self.cpu_lbl, self.cpu_bar = self._resource_row(
            res.body, "CPU Usage", "--%", 0)
        self.mem_lbl, self.mem_bar = self._resource_row(
            res.body, "RAM Usage", f"-- / {self.mem_total_gb:.0f} GB", 0)
        self.temp_lbl, self.temp_bar = self._resource_row(
            res.body, "CPU Temp", "-- \u00b0C", 0, last=True)

        if not HAS_PSUTIL:
            tk.Label(res.body,
                      text="psutil not found \u2014 showing demo values.\n"
                           "Run: pip install psutil for live readings.",
                      bg=PANEL_BG, fg=TEXT_DIM, font=mono(7),
                      justify="left").pack(anchor="w", pady=(8, 0))

    def _resource_row(self, parent, label, value, pct, last=False):
        row = tk.Frame(parent, bg=PANEL_BG)
        row.pack(fill="x", pady=(0, 4 if last else 10))
        top = tk.Frame(row, bg=PANEL_BG)
        top.pack(fill="x")
        tk.Label(top, text=label, bg=PANEL_BG, fg="#9fd3dd",
                  font=mono(9)).pack(side="left")
        vlbl = tk.Label(top, text=value, bg=PANEL_BG, fg=CYAN_BRIGHT,
                         font=mono(9, "bold"))
        vlbl.pack(side="right")
        bar = Bar(row, value=pct)
        bar.pack(fill="x", pady=(6, 0))
        return vlbl, bar

    # ------------------------------------------------------------ CENTER --
    def _build_center(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=0)
        parent.columnconfigure(0, weight=1)

        self.radar = tk.Canvas(parent, bg=BG, highlightthickness=0)
        self.radar.grid(row=0, column=0, sticky="nsew")
        self._radar_angle = 0.0

        bottom = tk.Frame(parent, bg=BG)
        bottom.grid(row=1, column=0, pady=(6, 10))

        self.vbar_canvas = tk.Canvas(bottom, width=280, height=36, bg=BG,
                                      highlightthickness=0)
        self.vbar_canvas.pack()
        self._vbar_phase = [random.uniform(0, math.pi * 2) for _ in range(16)]

        self.cmd_pill = tk.Label(
            bottom, text="\u25cf  STANDBY (Say \"Hey Luna\")", bg=PANEL_BG,
            fg="#6ea4b0", font=mono(11, "bold"), padx=22, pady=10,
            highlightthickness=1, highlightbackground=LINE, cursor="hand2")
        self.cmd_pill.pack(pady=(12, 0))
        self.cmd_pill.bind("<Button-1>", self._toggle_listen)

    def _toggle_listen(self, event=None):
        if not HAS_AUDIO or not self.state_machine:
            return
        if self._conversation_active:
            self._stop_conversation_session(announced=True)
        else:
            self.mic_muted = False
            self.mic_btn.config(text="\U0001F3A4", fg=CYAN_BRIGHT,
                                 highlightbackground=LINE_BRIGHT)
            self.mic_status_lbl.config(text="MIC LIVE", fg=TEXT_DIM)
            self._start_voice_conversation(confirmation="I'm listening.")

    # ------------------------------------------------------------- RIGHT --
    def _build_right(self, parent):
        panel = Panel(parent, "SYSTEM //", "COMMAND", "AURIX")
        panel.pack(fill="both", expand=True)
        panel.draw_corners()

        self.term_text = tk.Text(panel.body, bg=PANEL_BG, fg="#8fc6d0",
                                  font=mono(10), bd=0, highlightthickness=0,
                                  wrap="word", state="disabled")
        self.term_text.pack(fill="both", expand=True, pady=(0, 12))
        self.term_text.tag_config("dim", foreground=TEXT_DIM)
        self.term_text.tag_config("user", foreground=CYAN_BRIGHT)
        self.term_text.tag_config("reply", foreground="#bfe9f0")

        # mic toggle sits on its own row, above the text box, left-aligned
        mic_row = tk.Frame(panel.body, bg=PANEL_BG)
        mic_row.pack(fill="x", pady=(0, 8))
        self.mic_btn = tk.Label(mic_row, text="\U0001F3A4", bg=PANEL_BG,
                                 fg=CYAN_BRIGHT, font=mono(13), width=3,
                                 highlightthickness=1,
                                 highlightbackground=LINE_BRIGHT,
                                 cursor="hand2")
        self.mic_btn.pack(side="left")
        self.mic_btn.bind("<Button-1>", self._toggle_mic)
        self.mic_status_lbl = tk.Label(mic_row, text="MIC LIVE", bg=PANEL_BG,
                                        fg=TEXT_DIM, font=mono(8))
        self.mic_status_lbl.pack(side="left", padx=(10, 0))

        input_row = tk.Frame(panel.body, bg=PANEL_BG)
        input_row.pack(fill="x")

        self.cmd_entry = tk.Entry(
            input_row, bg="#0a161c", fg=CYAN_BRIGHT,
            insertbackground=CYAN_BRIGHT, font=mono(11), relief="flat",
            highlightthickness=1, highlightbackground=LINE,
            highlightcolor=CYAN_BRIGHT)
        self.cmd_entry.pack(side="left", fill="x", expand=True, ipady=8)
        self.cmd_entry.bind("<Return>", self._send_command)

        send_btn = tk.Label(input_row, text="SEND", bg=PANEL_BG, fg=CYAN,
                             font=mono(9, "bold"), padx=14, pady=8,
                             highlightthickness=1, highlightbackground=LINE,
                             cursor="hand2")
        send_btn.pack(side="left", padx=(8, 0))
        send_btn.bind("<Button-1>", self._send_command)

        self._play_welcome_call()

    def _play_welcome_call(self):
        config_path = os.path.join(ROOT_DIR, "welcome_config.json")
        welcome_text = "AURIX is online and ready."
        try:
            import json
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    greeting = data.get("greeting", "Greetings")
                    name = data.get("name", "Creator")
                    message = data.get("message", "AURIX is online and ready for your command.")
                    welcome_text = f"{greeting} {name}. {message}"
        except Exception as e:
            logger.warning("Failed to load welcome config: %s", e)

        self._append_terminal_line(welcome_text, "dim")

        if HAS_AUDIO:
            def speak_worker():
                if self.state_machine:
                    self.state_machine.transition_to(AssistantState.SPEAKING)
                try:
                    speak(welcome_text, interruptible=False)
                finally:
                    if self.state_machine:
                        self.state_machine.transition_to(AssistantState.SLEEPING)
                    if self.wakeword:
                        self.wakeword.resume_listening()
            threading.Thread(target=speak_worker, daemon=True, name="AurixWelcomeTTS").start()

    # ── Mic Toggle → Trigger Voice Pipeline ──────────────────────────
    def _toggle_mic(self, event=None):
        self.mic_muted = not self.mic_muted
        if self.mic_muted:
            self.mic_btn.config(text="\U0001F507", fg=RED,
                                 highlightbackground=RED)
            self.mic_status_lbl.config(text="MIC MUTED", fg=RED)
            if self._conversation_active:
                self._stop_conversation_session(announced=False)
        else:
            self.mic_btn.config(text="\U0001F3A4", fg=CYAN_BRIGHT,
                                 highlightbackground=LINE_BRIGHT)
            self.mic_status_lbl.config(text="MIC LIVE", fg=TEXT_DIM)
            if HAS_AUDIO and self.state_machine:
                self._start_voice_conversation(confirmation="Microphone live.")

    # ── Command Dispatch (Text Entry → Backend AI) ───────────────────
    def _send_command(self, event=None):
        text = self.cmd_entry.get().strip()
        if not text:
            return
        self.cmd_entry.delete(0, "end")
        self._append_terminal_line(text, "user")

        # Log to telemetry
        if self.telemetry:
            try:
                self.telemetry.ingest_execution_log(
                    session_id="aurix_gui_session",
                    action_type="USER_COMMAND",
                    target_command=text,
                    status="EXECUTING",
                    return_code=0,
                )
            except Exception as e:
                logger.error("Telemetry log failed: %s", e)

        # Dispatch inference in background thread
        def generate_job():
            try:
                # Route through AI Brain dispatcher first
                if self._brain:
                    reply, handled = self._brain.dispatch(text)
                    if handled:
                        now_str = datetime.now().strftime("%H:%M:%S")
                        self._response_queue.put((reply, now_str))
                        return

                # Not a brain action — fall through to LLM
                if self.gemma_runner and getattr(
                    self.gemma_runner, "is_available",
                    getattr(self.gemma_runner, "is_loaded", False),
                ):
                    reply = self.gemma_runner.chat(user_message=text)
                else:
                    reply = "AURIX inference engine is standing by."
            except Exception as err:
                reply = f"[Error]: {err}"

            now_str = datetime.now().strftime("%H:%M:%S")
            self._response_queue.put((reply, now_str))

        threading.Thread(target=generate_job, daemon=True, name="AurixInferenceThread").start()

    # ── Trust Token Security Handler ─────────────────────────────────
    def _handle_trust_token_request(self, reply_text: str) -> str:
        """Handle protected AURIX actions with explicit user confirmation."""

        if not reply_text.startswith("TRUST_TOKEN_REQUIRED:"):
            return reply_text

        from tkinter import messagebox

        parts = reply_text.split(":", 2)
        description = parts[2] if len(parts) > 2 else "protected action"

        approved = messagebox.askyesno(
            "AURIX Security Confirmation",
            (
                "AURIX wants permission to perform:\n\n"
                f"{description}\n\n"
                "Allow this action?"
            ),
            parent=self,
        )

        if not approved:
            return "Action cancelled by user."

        if not self._brain:
            return "Security action could not be completed."

        try:
            return self._brain.execute_trust_token(reply_text)
        except Exception as exc:
            logger.exception("Trust Token execution failed: %s", exc)
            return "Protected action failed."

    # ── Poll Response Queue (AI responses + voice input) ─────────────
    def _poll_response_queue(self):
        """Poll async queues on Tk main thread."""
        # Voice input → dispatch as command
        while not self._voice_input_queue.empty():
            spoken_text = self._voice_input_queue.get_nowait()
            if spoken_text:
                self.cmd_entry.delete(0, "end")
                self.cmd_entry.insert(0, spoken_text)
                self._send_command()

        # AI inference responses → show in terminal
        while not self._response_queue.empty():
            reply_text, timestamp = self._response_queue.get_nowait()

            if reply_text.startswith("TRUST_TOKEN_REQUIRED:"):
                reply_text = self._handle_trust_token_request(reply_text)

            self._append_terminal_line(reply_text, "reply")

            # TTS: speak response aloud (non-blocking)
            if HAS_AUDIO and self.state_machine:
                def speak_worker(reply: str):
                    self.state_machine.transition_to(AssistantState.SPEAKING)
                    try:
                        import re
                        clean = re.sub(r"```[\s\S]*?```", "code omitted", reply)
                        clean = re.sub(r"[\*_#\[\]\(\)`]", "", clean).strip()
                        if clean:
                            speak(clean[:300])
                    finally:
                        self.state_machine.transition_to(AssistantState.SLEEPING)
                        if self.wakeword:
                            self.wakeword.resume_listening()

                threading.Thread(
                    target=speak_worker, args=(reply_text,),
                    daemon=True, name="AurixTTSThread",
                ).start()

        self.after(100, self._poll_response_queue)

    # ── Voice State & UI Synchronization ─────────────────────────────
    def _apply_assistant_state_ui(self, state: AssistantState):
        """Update all UI indicators based on AssistantState."""
        self._current_assistant_state = state

        # 1. Update Command Pill
        if state == AssistantState.SLEEPING:
            self.cmd_pill.config(
                text="●  STANDBY (Say 'Hey Luna')",
                fg="#6ea4b0",
                highlightbackground=LINE,
            )
        elif state == AssistantState.LISTENING:
            self.cmd_pill.config(
                text="●  LISTENING... (Speak now)",
                fg=AMBER,
                highlightbackground=AMBER,
            )
        elif state == AssistantState.THINKING:
            self.cmd_pill.config(
                text="●  THINKING...",
                fg=CYAN_BRIGHT,
                highlightbackground=CYAN,
            )
        elif state == AssistantState.EXECUTING:
            self.cmd_pill.config(
                text="●  EXECUTING...",
                fg=CYAN_BRIGHT,
                highlightbackground=CYAN_BRIGHT,
            )
        elif state == AssistantState.SPEAKING:
            self.cmd_pill.config(
                text="●  SPEAKING...",
                fg=GREEN,
                highlightbackground=GREEN,
            )

        # 2. Update Header Status Dot & Label
        if hasattr(self, "status_dot") and hasattr(self, "status_lbl"):
            self.status_dot.delete("all")
            if state == AssistantState.SLEEPING:
                self.status_dot.create_oval(0, 0, 8, 8, fill=TEXT_DIM, outline="")
                self.status_lbl.config(text="STANDBY", fg=TEXT_DIM)
            elif state == AssistantState.LISTENING:
                self.status_dot.create_oval(0, 0, 8, 8, fill=AMBER, outline="")
                self.status_lbl.config(text="LISTENING", fg=AMBER)
            elif state in (AssistantState.THINKING, AssistantState.EXECUTING):
                self.status_dot.create_oval(0, 0, 8, 8, fill=CYAN_BRIGHT, outline="")
                self.status_lbl.config(text="PROCESSING", fg=CYAN_BRIGHT)
            elif state == AssistantState.SPEAKING:
                self.status_dot.create_oval(0, 0, 8, 8, fill=GREEN, outline="")
                self.status_lbl.config(text="SPEAKING", fg=GREEN)

    def _on_assistant_state_change(self, old_state, new_state):
        """Callback fired whenever voice assistant state changes."""
        logger.info("Voice State: %s -> %s", old_state.value, new_state.value)
        self.after(0, lambda: self._apply_assistant_state_ui(new_state))

    # ── Continuous Voice Conversation Pipeline ────────────────────────
    def _execute_user_turn(self, text: str) -> str:
        """Synchronously execute a single command turn during voice interaction."""
        try:
            if self._brain:
                reply, handled = self._brain.dispatch(text)
                if handled:
                    return reply

            if self.gemma_runner and getattr(
                self.gemma_runner, "is_available",
                getattr(self.gemma_runner, "is_loaded", False),
            ):
                return self.gemma_runner.chat(user_message=text)
            else:
                return "AURIX inference engine is standing by."
        except Exception as err:
            return f"[Error]: {err}"

    def _start_voice_conversation(self, confirmation: Optional[str] = None):
        """Starts continuous conversation session."""
        if not HAS_AUDIO or not self.state_machine:
            self._append_terminal_line("Audio subsystem not available.", "dim")
            return
        if self._conversation_active:
            return
        self._conversation_active = True
        self._run_conversation_session(confirmation=confirmation)

    def _stop_conversation_session(self, announced: bool = True):
        """Gracefully stops active session and transitions to standby."""
        self._conversation_active = False
        if announced and HAS_AUDIO:
            def _announce():
                if self.state_machine:
                    self.state_machine.transition_to(AssistantState.SPEAKING)
                try:
                    standby_text = "Going to standby mode."
                    self._append_terminal_line_safe(f"AURIX: {standby_text}", "dim")
                    speak(standby_text, interruptible=False)
                finally:
                    if self.state_machine:
                        self.state_machine.transition_to(AssistantState.SLEEPING)
                    if self.wakeword:
                        self.wakeword.resume_listening()
            threading.Thread(target=_announce, daemon=True, name="AurixStandbyAnnounce").start()
        else:
            if self.state_machine:
                self.state_machine.transition_to(AssistantState.SLEEPING)
            if self.wakeword:
                self.wakeword.resume_listening()

    def _run_conversation_session(self, confirmation: Optional[str] = None):
        """Core continuous voice pipeline: keeps conversation active turn-by-turn."""
        def session_worker():
            self._conversation_active = True
            if self.wakeword:
                self.wakeword.pause_listening()

            first_turn = True
            try:
                while self._conversation_active and not self.mic_muted:
                    self.state_machine.transition_to(AssistantState.LISTENING)

                    if first_turn and confirmation:
                        self._append_terminal_line_safe(f"AURIX: {confirmation}", "reply")
                        speak(confirmation, interruptible=False)

                    audio_dir = os.path.join(ROOT_DIR, "data")
                    os.makedirs(audio_dir, exist_ok=True)
                    wav_path = os.path.join(audio_dir, "input.wav")

                    # Wait up to 8.5s for follow-up turns (10s on first turn)
                    timeout = 10.0 if first_turn else 8.5
                    first_turn = False

                    rec = record_audio(
                        filename=wav_path,
                        sample_rate=16000,
                        silence_limit=2.0,
                        initial_timeout=timeout,
                        min_speech_duration=0.6,
                    )

                    if not rec or not self._conversation_active or self.mic_muted:
                        # User stopped speaking / timeout reached -> Announce standby
                        logger.info("Voice session silence timeout. Transitioning to standby.")
                        standby_text = "Going to standby mode."
                        self._append_terminal_line_safe(f"AURIX: {standby_text}", "dim")
                        self.state_machine.transition_to(AssistantState.SPEAKING)
                        try:
                            speak(standby_text, interruptible=False)
                        except Exception:
                            pass
                        break

                    self.state_machine.transition_to(AssistantState.THINKING)
                    spoken_text = transcribe_audio(rec)

                    if not spoken_text:
                        retry_text = "I didn't catch that."
                        self._append_terminal_line_safe(f"AURIX: {retry_text}", "dim")
                        self.state_machine.transition_to(AssistantState.SPEAKING)
                        speak(retry_text, interruptible=False)
                        continue

                    # Check cancel / standby phrases
                    lower_spoken = spoken_text.lower()
                    if is_cancel_phrase(spoken_text) or any(
                        w in lower_spoken for w in ("standby", "stand by", "go to sleep", "sleep now", "stop listening")
                    ):
                        logger.info("User requested standby: '%s'", spoken_text)
                        cancel_text = "Going to standby mode."
                        self._append_terminal_line_safe(f"User: {spoken_text}", "user")
                        self._append_terminal_line_safe(f"AURIX: {cancel_text}", "dim")
                        self.state_machine.transition_to(AssistantState.SPEAKING)
                        speak(cancel_text, interruptible=False)
                        break

                    self.state_machine.transition_to(AssistantState.EXECUTING)
                    self._append_terminal_line_safe(f"User: {spoken_text}", "user")

                    reply = self._execute_user_turn(spoken_text)

                    if reply.startswith("TRUST_TOKEN_REQUIRED:"):
                        # Voice conversation runs in a worker thread, while Tkinter
                        # dialogs must be created on the main UI thread.
                        result_holder = {}
                        done_event = threading.Event()

                        def _ask_permission():
                            try:
                                result_holder["reply"] = self._handle_trust_token_request(reply)
                            finally:
                                done_event.set()

                        self.after(0, _ask_permission)
                        done_event.wait()
                        reply = result_holder.get("reply", "Action cancelled by user.")

                    self._append_terminal_line_safe(f"AURIX: {reply}", "reply")

                    self.state_machine.transition_to(AssistantState.SPEAKING)
                    try:
                        clean = re.sub(r"```[\s\S]*?```", "code omitted", reply)
                        clean = re.sub(r"[\*_#\[\]\(\)`]", "", clean).strip()
                        if clean:
                            speak(clean[:300])
                    except Exception as err:
                        logger.error("TTS speech error: %s", err)

                    time.sleep(0.3)

            except Exception as e:
                logger.error("Conversation session error: %s", e, exc_info=True)
            finally:
                self._conversation_active = False
                if self.state_machine:
                    self.state_machine.transition_to(AssistantState.SLEEPING)
                if self.wakeword:
                    self.wakeword.resume_listening()

        threading.Thread(target=session_worker, daemon=True, name="AurixConversationSession").start()

    def _handle_wakeword_triggered(self, confirmation: str):
        """Triggered when offline wake-word detector spots 'Luna' or 'Hey Luna'."""
        logger.info("Wake-Word Event: %s", confirmation)
        if not self._conversation_active:
            self._start_voice_conversation(confirmation=confirmation)

    def _append_terminal_line_safe(self, text: str, tag: str = None):
        """Thread-safe version — schedules on Tk main thread."""
        self.after(0, lambda: self._append_terminal_line(text, tag))

    def _append_terminal_line(self, text, tag=None):
        self.term_text.config(state="normal")
        self.term_text.insert("end", text + "\n", tag)
        lines = int(self.term_text.index("end-1c").split(".")[0])
        if lines > 200:
            self.term_text.delete("1.0", "2.0")
        self.term_text.see("end")
        self.term_text.config(state="disabled")

    # ============================================================ TICKS ===
    def _tick_datetime(self):
        now = datetime.now()
        self.date_lbl.config(text=now.strftime("%A, %d %B %Y"))
        self.time_lbl.config(text=now.strftime("%H:%M:%S"))
        self.after(1000, self._tick_datetime)

    def _read_cpu_temp(self):
        """Best-effort CPU temperature. Returns None if unavailable
        (common on Windows/macOS without extra drivers)."""
        if not HAS_PSUTIL or not hasattr(psutil, "sensors_temperatures"):
            return None
        try:
            temps = psutil.sensors_temperatures()
        except (AttributeError, NotImplementedError, OSError):
            return None
        if not temps:
            return None
        for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz", "zenpower"):
            if key in temps and temps[key]:
                return temps[key][0].current
        for entries in temps.values():
            if entries:
                return entries[0].current
        return None

    def _tick_system_stats(self):
        if HAS_PSUTIL:
            cpu = psutil.cpu_percent(interval=None)
            vm = psutil.virtual_memory()
            used_gb = vm.used / (1024 ** 3)
            total_gb = vm.total / (1024 ** 3)
            mem_pct = vm.percent
            temp = self._read_cpu_temp()
        else:
            self.cpu = max(4, min(92, self.cpu + random.uniform(-6, 6)))
            cpu = self.cpu
            self.mem = max(10, min(92, self.mem + random.uniform(-3, 3)))
            total_gb = self.mem_total_gb
            used_gb = self.mem / 100 * total_gb
            mem_pct = self.mem
            temp = 44 + random.uniform(-3, 4)

        self.cpu_bar.set(cpu)
        self.cpu_lbl.config(text=f"{cpu:.0f}%")
        self.mem_bar.set(mem_pct)
        self.mem_lbl.config(text=f"{used_gb:.1f} / {total_gb:.1f} GB")

        if temp is None:
            self.temp_lbl.config(text="N/A")
            self.temp_bar.set(0)
        else:
            self.temp_bar.set(min(100, temp))
            self.temp_lbl.config(text=f"{temp:.0f} \u00b0C")

        # Push telemetry frame to backend (use internal attributes to avoid lazy-loading on every tick)
        if self._telemetry:
            try:
                power_state = "ACTIVE"
                if self._system_state:
                    power_state = self._system_state.get_power_state_name()
                self._telemetry.ingest_hardware_metrics(
                    ram_gb=round(used_gb, 2) if HAS_PSUTIL else 0.0,
                    vram_gb=0.0,
                    power_state=power_state,
                    training_state=(
                        "RUNNING" if self._student_trainer and getattr(self._student_trainer, "is_running", False)
                        else "STOPPED"
                    ),
                )
            except Exception:
                pass

        self.after(1500, self._tick_system_stats)


    def _draw_ring(self, c, cx, cy, rr, color, dash=None, width=1):
        """Draw a ring on canvas — hoisted out of hot loop to avoid closure re-creation."""
        c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                       outline=color, width=width, dash=dash)

    def _tick_radar(self):
        c = self.radar
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()

        state = getattr(self, "_current_assistant_state", None)
        if not HAS_AUDIO or state is None:
            state = AssistantState.SLEEPING

        # Dynamic state styling
        if state == AssistantState.LISTENING:
            core_col = AMBER
            state_text = "LISTEN"
            rot_delta = 2.4
            pulse_color = AMBER
        elif state == AssistantState.THINKING:
            core_col = CYAN_BRIGHT
            state_text = "THINK"
            rot_delta = 3.6
            pulse_color = CYAN_BRIGHT
        elif state == AssistantState.EXECUTING:
            core_col = CYAN
            state_text = "EXEC"
            rot_delta = 2.8
            pulse_color = CYAN
        elif state == AssistantState.SPEAKING:
            core_col = GREEN
            state_text = "SPEAK"
            rot_delta = 2.0
            pulse_color = GREEN
        else:  # SLEEPING / STANDBY
            core_col = CYAN_DIM
            state_text = "STANDBY"
            rot_delta = 0.8
            pulse_color = LINE_BRIGHT

        if w > 10 and h > 10:
            cx, cy = w / 2, h / 2
            R = min(w, h) * 0.42
            ring = self._draw_ring

            ring(c, cx, cy, R, LINE)
            ring(c, cx, cy, R * 0.82, LINE_BRIGHT if state == AssistantState.SLEEPING else core_col, dash=(4, 6))
            ring(c, cx, cy, R * 0.62, LINE)
            ring(c, cx, cy, R * 0.42, CYAN_DIM, dash=(3, 5))

            c.create_line(cx - R - 15, cy, cx + R + 15, cy, fill=LINE)
            c.create_line(cx, cy - R - 15, cx, cy + R + 15, fill=LINE)

            # Rotating orbit brackets
            a = math.radians(self._radar_angle)
            cos_a = math.cos(a)
            sin_a = math.sin(a)
            orbit_r = R * 0.82
            for sign in (1, -1):
                bx = cx + cos_a * sign * orbit_r
                by = cy + sin_a * sign * orbit_r
                c.create_line(bx - 8, by - 8, bx + 8, by + 8,
                              fill=core_col, width=2)

            # Pulse ring
            pulse_phase = (self._radar_angle % 60) / 60
            if pulse_phase < 0.95:
                pulse_r = R * 0.3 + pulse_phase * R * 0.5
                ring(c, cx, cy, pulse_r, pulse_color, width=1)

            # Central Core Box & Label
            s = R * 0.17
            c.create_rectangle(cx - s, cy - s, cx + s, cy + s,
                                outline=core_col, width=2 if state != AssistantState.SLEEPING else 1)
            c.create_text(cx, cy - 10, text="CORE", fill=core_col,
                          font=mono(13, "bold"))
            c.create_text(cx, cy + 10, text=state_text, fill=core_col,
                          font=mono(9 if len(state_text) > 7 else 11, "bold"))

            self._radar_angle = (self._radar_angle + rot_delta) % 360

        # ── Dynamic Multi-Layer Wave Visualizer ───────────────────────
        vc = self.vbar_canvas
        vc.delete("all")
        vw = vc.winfo_width()
        vh = vc.winfo_height()

        if vw > 10 and vh > 5:
            mid_y = vh / 2
            self._wave_phase = getattr(self, "_wave_phase", 0.0) + 0.18
            phase = self._wave_phase

            num_bars = 16
            bar_w = vw / num_bars
            phases = self._vbar_phase

            if state == AssistantState.SLEEPING:
                # Standby: gentle baseline ripple
                wave_pts = []
                for x in range(0, int(vw) + 8, 6):
                    y = mid_y + math.sin(phase * 0.4 + x * 0.035) * 2.5
                    wave_pts.extend([x, y])
                if len(wave_pts) >= 4:
                    vc.create_line(*wave_pts, fill=CYAN_DIM, width=1, smooth=True)

                for i in range(num_bars):
                    phases[i] += 0.08
                    h_bar = 2 + (math.sin(phases[i]) * 0.5 + 0.5) * 4
                    x0 = i * bar_w + bar_w * 0.35
                    x1 = x0 + bar_w * 0.3
                    vc.create_rectangle(x0, vh - h_bar, x1, vh, fill="#0e1f26", outline="")

            elif state == AssistantState.LISTENING:
                # Listening: reactive amber audio wave with microphone bursts
                wave_pts_1 = []
                wave_pts_2 = []
                for x in range(0, int(vw) + 8, 6):
                    y1 = mid_y + (math.sin(phase * 1.1 + x * 0.05) * 0.7 + math.sin(phase * 2.1 + x * 0.11) * 0.4) * 11
                    y2 = mid_y + math.sin(phase * 1.5 + x * 0.08) * 6
                    wave_pts_1.extend([x, y1])
                    wave_pts_2.extend([x, y2])

                if len(wave_pts_1) >= 4:
                    vc.create_line(*wave_pts_1, fill=AMBER, width=2, smooth=True)
                if len(wave_pts_2) >= 4:
                    vc.create_line(*wave_pts_2, fill=CYAN_BRIGHT, width=1, smooth=True)

                for i in range(num_bars):
                    phases[i] += 0.22
                    h_bar = 5 + (math.sin(phases[i]) * 0.5 + 0.5) * 19
                    x0 = i * bar_w + bar_w * 0.3
                    x1 = x0 + bar_w * 0.4
                    vc.create_rectangle(x0, vh - h_bar, x1, vh, fill=AMBER, outline="")

            elif state in (AssistantState.THINKING, AssistantState.EXECUTING):
                # Thinking / Executing: swirling dual computation waves
                wave_pts_1 = []
                wave_pts_2 = []
                for x in range(0, int(vw) + 8, 6):
                    y1 = mid_y + math.sin(phase * 2.2 + x * 0.08) * 8
                    y2 = mid_y + math.cos(phase * 1.6 + x * 0.08) * 8
                    wave_pts_1.extend([x, y1])
                    wave_pts_2.extend([x, y2])

                if len(wave_pts_1) >= 4:
                    vc.create_line(*wave_pts_1, fill=CYAN_BRIGHT, width=2, smooth=True)
                if len(wave_pts_2) >= 4:
                    vc.create_line(*wave_pts_2, fill=CYAN, width=1, dash=(4, 4), smooth=True)

                for i in range(num_bars):
                    phases[i] += 0.28
                    h_bar = 4 + (math.sin(phases[i]) * 0.5 + 0.5) * 14
                    x0 = i * bar_w + bar_w * 0.3
                    x1 = x0 + bar_w * 0.4
                    vc.create_rectangle(x0, vh - h_bar, x1, vh, fill=CYAN_BRIGHT, outline="")

            elif state == AssistantState.SPEAKING:
                # Speaking: rich, energetic speech audio waves
                wave_pts_1 = []
                wave_pts_2 = []
                for x in range(0, int(vw) + 8, 6):
                    env = math.sin((x / max(vw, 1)) * math.pi)
                    y1 = mid_y + (math.sin(phase * 1.7 + x * 0.06) * 0.7 + math.sin(phase * 3.2 + x * 0.12) * 0.5) * (14 * env)
                    y2 = mid_y + math.sin(phase * 1.2 + x * 0.08) * (8 * env)
                    wave_pts_1.extend([x, y1])
                    wave_pts_2.extend([x, y2])

                if len(wave_pts_1) >= 4:
                    vc.create_line(*wave_pts_1, fill=GREEN, width=2, smooth=True)
                if len(wave_pts_2) >= 4:
                    vc.create_line(*wave_pts_2, fill=CYAN_BRIGHT, width=1, smooth=True)

                for i in range(num_bars):
                    phases[i] += 0.24
                    env = math.sin(((i + 1) / (num_bars + 1)) * math.pi)
                    h_bar = 5 + (math.sin(phases[i]) * 0.5 + 0.5) * 23 * env
                    x0 = i * bar_w + bar_w * 0.3
                    x1 = x0 + bar_w * 0.4
                    vc.create_rectangle(x0, vh - h_bar, x1, vh, fill=GREEN, outline="")

        self.after(66, self._tick_radar)  # ~15 FPS — smooth enough, 40% less CPU/RAM churn


if __name__ == "__main__":
    app = JarvisApp()
    app.mainloop()
