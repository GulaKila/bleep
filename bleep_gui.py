# -*- coding: utf-8 -*-
"""
哔哔啵啵 · 文字转叫声
======================

输入一段文字，点「试听」，它就变成一字一声的哔哔啵啵。
左边的滑条随便拧：基调、音域、语速、元音、气声、音量……
满意了导出 WAV。

命令行也能用：
    python bleep_gui.py                # 打开界面
    python bleep.py "你好" -o a.wav    # 直接生成文件，不打开界面
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import tkinter as tk
import winsound
from tkinter import filedialog, messagebox, simpledialog, ttk

import bleep

APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "设置.json"
MY_PRESETS_FILE = APP_DIR / "我的音色.json"
TMP_DIR = Path(tempfile.gettempdir()) / "bleep_voice"

# ---------------- 配色 ----------------
THEMES = {
    "cream": {
        "bg": "#FAF6EF", "card": "#FFFFFF", "ink": "#2E2B3A", "muted": "#8D8798",
        "accent": "#5B7CFA", "accent_dark": "#4664DE", "border": "#E7DFD2",
        "trough": "#EEE7DB", "ghost": "#F1EADF", "ghost_hover": "#E6DDCE",
        "hover": "#F4EEE4", "knob": "#FFFFFF", "knob_shadow": "#E4DCCE",
        "axis": "#F0E9DD", "hint": "#C9C0B2", "on_accent": "#FFFFFF",
    },
    "night": {
        "bg": "#14121A", "card": "#1E1B26", "ink": "#F3EFF8", "muted": "#9C93AC",
        "accent": "#7C9CFF", "accent_dark": "#5F7FE8", "border": "#2E2839",
        "trough": "#2B2634", "ghost": "#241F2E", "ghost_hover": "#2F2839",
        "hover": "#2A2534", "knob": "#F3EFF8", "knob_shadow": "#0D0B12",
        "axis": "#262130", "hint": "#5F5870", "on_accent": "#0F0D15",
    },
    "candy": {
        "bg": "#FFF4F7", "card": "#FFFFFF", "ink": "#3B2A33", "muted": "#A0808E",
        "accent": "#FF6FA5", "accent_dark": "#EE5A92", "border": "#F5DCE5",
        "trough": "#F9E3EA", "ghost": "#FBEAF0", "ghost_hover": "#F7DCE6",
        "hover": "#FDEDF2", "knob": "#FFFFFF", "knob_shadow": "#F0D3DD",
        "axis": "#FBE7EE", "hint": "#C9A6B3", "on_accent": "#FFFFFF",
    },
}
THEME_LABELS = {"cream": "奶油", "night": "夜间", "candy": "糖果"}

# 这几个全局变量会被 apply_palette() 改，所以下面所有控件都读它们
BG = CARD = INK = MUTED = ACCENT = ACCENT_DARK = BORDER = TROUGH = ""
GHOST = GHOST_HOVER = HOVER = KNOB = KNOB_SHADOW = AXIS = HINT = ON_ACCENT = ""
_theme_name = "cream"


def apply_palette(name):
    global BG, CARD, INK, MUTED, ACCENT, ACCENT_DARK, BORDER, TROUGH
    global GHOST, GHOST_HOVER, HOVER, KNOB, KNOB_SHADOW, AXIS, HINT, ON_ACCENT, _theme_name
    if name not in THEMES:
        name = "cream"
    t = THEMES[name]
    _theme_name = name
    BG, CARD, INK, MUTED = t["bg"], t["card"], t["ink"], t["muted"]
    ACCENT, ACCENT_DARK, BORDER, TROUGH = t["accent"], t["accent_dark"], t["border"], t["trough"]
    GHOST, GHOST_HOVER, HOVER = t["ghost"], t["ghost_hover"], t["hover"]
    KNOB, KNOB_SHADOW, AXIS, HINT = t["knob"], t["knob_shadow"], t["axis"], t["hint"]
    ON_ACCENT = t["on_accent"]


apply_palette(os.environ.get("BLEEP_THEME", "cream"))

FONT = "Microsoft YaHei UI"

SAMPLE_TEXT = "你好呀，我是哔哔啵啵。今天也要开心！"

# 滑条：(字段, 名称, 最小, 最大, 小数位, 单位)
PARAMS = [
    ("f0", "基调", 120, 900, 0, "Hz"),
    ("range_semi", "音域", 0, 12, 1, "半音"),
    ("length_ms", "字长", 30, 160, 0, "ms"),
    ("gap_ms", "间隔", 0, 140, 0, "ms"),
    ("glide", "滑音", -6, 6, 1, "半音"),
    ("vowel", "元音", 0, 1, 2, ""),
    ("buzz", "谐波", 0, 1, 2, ""),
    ("formant", "共鸣", 0.5, 1.8, 2, "x"),
    ("breath", "气声", 0, 0.6, 2, ""),
    ("drive", "颗粒", 0, 0.8, 2, ""),
    ("sub", "厚度", 0, 0.5, 2, ""),
    ("volume", "音量", 0.05, 1.0, 2, ""),
]

# 滑条名字的解释：调什么、听起来会怎样
PARAM_TIPS = {
    "__speed__": ("语速", "整句念得快还是慢。往右像机关枪，往左就一个字一个字地往外蹦。"),
    "f0": ("基调", "整句的基准音高。越高越像小动物或小孩，越低越像大只的机器人。"),
    "range_semi": ("音域", "每个字之间音高跳动的幅度。0 是一条直线，越大越像在乱蹦。"),
    "length_ms": ("字长", "每一声持续多久。短一点干脆、电子味重；长一点黏糊，像拖着尾音。"),
    "gap_ms": ("间隔", "字和字之间空多久。太小会连成一片，太大就变成一个字一个字往外蹦。"),
    "glide": ("滑音", "一声之内音高往哪滑。负数往下掉，更可爱；正数往上挑，像在反问。"),
    "vowel": ("元音", "口型有多明显。0 是纯电子音，越大越像真的在说 a、e、i、o、u。"),
    "buzz": ("谐波", "声音的毛刺感。0 圆润接近纯音，1 很方、很复古的电子味。"),
    "formant": ("共鸣", "整体音色的粗细。往右更小只更脆，往左更闷更厚。"),
    "breath": ("气声", "混进去多少呼吸声。多一点像在耳朵边上说悄悄话。"),
    "drive": ("颗粒", "加一点破音和脏脏的感觉，电子味更重。"),
    "sub": ("厚度", "叠一个低八度进去，声音更厚更沉。"),
    "volume": ("音量", "播放和导出的音量，只改大小，不改音色。"),
}


def safe_name(text: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", text.strip())[:14]
    return s or "哔哔啵啵"


def load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class Slider(tk.Canvas):
    """自绘滑条：圆角槽 + 进度 + 圆钮，比 ttk 的好看一点。"""

    def __init__(self, master, lo, hi, value, decimals=0, step=None,
                 command=None, accent=None, bg=None, height=26):
        accent = accent or ACCENT
        bg = bg or CARD
        super().__init__(master, height=height, bg=bg, highlightthickness=0,
                         bd=0, cursor="hand2")
        self.lo, self.hi = float(lo), float(hi)
        self.value = float(value)
        self.decimals = decimals
        self.step = step if step else 10 ** (-decimals)
        self.command = command
        self.accent = accent
        self.bg = bg
        self._dragging = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<MouseWheel>", self._on_wheel)

    # ---- 对外
    def set(self, value, notify=False):
        self.value = self._quantize(float(value))
        self._draw()
        if notify and self.command:
            self.command(self.value)

    def get(self):
        return self.value

    # ---- 内部
    def _quantize(self, v):
        v = max(self.lo, min(self.hi, v))
        if self.step:
            v = round((v - self.lo) / self.step) * self.step + self.lo
        return round(v, 6)

    def _geom(self):
        w = max(40, self.winfo_width())
        h = max(16, self.winfo_height())
        return w, h, 11.0, 7.0

    def _value_to_x(self, v):
        w, h, pad, r = self._geom()
        t = (v - self.lo) / (self.hi - self.lo or 1)
        return pad + t * (w - 2 * pad)

    def _x_to_value(self, x):
        w, h, pad, r = self._geom()
        t = (x - pad) / max(1.0, (w - 2 * pad))
        return self._quantize(self.lo + t * (self.hi - self.lo))

    def _on_press(self, e):
        self._dragging = True
        self._apply(self._x_to_value(e.x))

    def _on_drag(self, e):
        if self._dragging:
            self._apply(self._x_to_value(e.x))

    def _on_release(self, e):
        self._dragging = False

    def _on_wheel(self, e):
        step = self.step * (1 if e.delta > 0 else -1)
        self._apply(self._quantize(self.value + step))

    def _apply(self, v):
        if v != self.value:
            self.value = v
            self._draw()
            if self.command:
                self.command(v)
        else:
            self._draw()

    def _draw(self):
        self.delete("all")
        w, h, pad, r = self._geom()
        y = h / 2
        th = 3.0
        # 槽
        self.create_rectangle(pad, y - th, w - pad, y + th, fill=TROUGH, outline="")
        self.create_oval(pad - th, y - th, pad + th, y + th, fill=TROUGH, outline="")
        self.create_oval(w - pad - th, y - th, w - pad + th, y + th, fill=TROUGH, outline="")
        # 已选部分
        x = self._value_to_x(self.value)
        if x > pad + 1:
            self.create_rectangle(pad, y - th, x, y + th, fill=self.accent, outline="")
            self.create_oval(pad - th, y - th, pad + th, y + th, fill=self.accent, outline="")
        # 圆钮
        self.create_oval(x - r + 1, y - r + 2, x + r + 1, y + r + 2,
                         fill=KNOB_SHADOW, outline="")
        self.create_oval(x - r, y - r, x + r, y + r,
                         fill=KNOB, outline=self.accent, width=2)


class Tooltip:
    """鼠标停在参数名上时，弹出一句「这是调什么的、听起来会怎样」。"""

    def __init__(self, widgets, title, text):
        self.widgets = widgets
        self.title = title
        self.text = text
        self.tip = None
        self._after = None
        for w in widgets:
            w.bind("<Enter>", self._enter, add="+")
            w.bind("<Leave>", self._leave, add="+")
            w.bind("<ButtonPress>", self._hide, add="+")

    def _enter(self, event=None):
        self._cancel()
        self._after = self.widgets[0].after(260, self._show)

    def _leave(self, event=None):
        self._cancel()
        self._after = self.widgets[0].after(80, self._hide)

    def _cancel(self):
        if self._after:
            try:
                self.widgets[0].after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _show(self):
        self._after = None
        w = self.widgets[0]
        try:
            if not w.winfo_exists() or self.tip is not None:
                return
        except Exception:
            return
        self.tip = tk.Toplevel(w)
        self.tip.wm_overrideredirect(True)
        try:
            self.tip.attributes("-topmost", True)
        except Exception:
            pass
        border = tk.Frame(self.tip, bg=BORDER)
        border.pack()
        box = tk.Frame(border, bg=CARD)
        box.pack(padx=1, pady=1)
        tk.Label(box, text=self.title, bg=CARD, fg=ACCENT,
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(box, text=self.text, bg=CARD, fg=INK, font=(FONT, 9),
                 justify="left", anchor="w", wraplength=250).pack(fill="x", padx=10, pady=(3, 9))
        self.tip.update_idletasks()
        tw = self.tip.winfo_reqwidth()
        th = self.tip.winfo_reqheight()
        x = w.winfo_rootx()
        y = w.winfo_rooty() + w.winfo_height() + 7
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        if x + tw > sw - 10:
            x = sw - tw - 10
        if y + th > sh - 10:
            y = w.winfo_rooty() - th - 7
        self.tip.wm_geometry("+%d+%d" % (int(x), int(y)))

    def _hide(self, event=None):
        self._cancel()
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None


class Player:
    """winsound 播 WAV；每次渲染写临时文件，旧文件顺手清掉。"""

    def __init__(self):
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        self.files = []

    def play(self, audio, sr=bleep.SR):
        path = TMP_DIR / ("play_%d.wav" % time.time_ns())
        bleep.write_wav(path, audio, sr)
        try:
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            pass
        self.files.append(path)
        while len(self.files) > 20:
            old = self.files.pop(0)
            try:
                old.unlink()
            except Exception:
                pass

    def stop(self):
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.player = Player()
        self.voice = replace(bleep.PRESETS["蓝白·哔啵"])
        self.speed = 1.0
        self.my_presets = load_json(MY_PRESETS_FILE, {})
        self.last_audio = None
        self.last_text = ""
        self.last_duration = 0.0
        self.wave_audio = None
        self.dirty = True
        self._loading = False
        self._preview_job = None

        saved = load_json(SETTINGS_FILE, {})
        self.theme_name = saved.get("theme") if saved.get("theme") in THEMES else "cream"
        apply_palette(self.theme_name)

        self._setup_style()
        self._build()
        self._load_settings()
        self._refresh_preset_list()
        self._apply_voice_to_ui(self.voice)
        self.speed_slider.set(self.speed)
        self.speed_value.config(text=f"{self.speed:.2f}×")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(150, lambda: self.text.focus_set())

    # ------------------------------------------------------------ 外观
    def _setup_style(self):
        self.root.title("哔哔啵啵 · 文字转叫声")
        self.root.configure(bg=BG)
        self.root.geometry("1040x690")
        self.root.minsize(940, 640)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TButton", font=(FONT, 9), padding=(10, 6),
                        background=GHOST, foreground=INK, borderwidth=0)
        style.map("TButton", background=[("active", GHOST_HOVER)])
        style.configure("Accent.TButton", font=(FONT, 10, "bold"), padding=(22, 9),
                        background=ACCENT, foreground=ON_ACCENT, borderwidth=0)
        style.map("Accent.TButton", background=[("active", ACCENT_DARK)])
        style.configure("Ghost.TButton", font=(FONT, 9), padding=(9, 5),
                        background=CARD, foreground=MUTED, borderwidth=0)
        style.map("Ghost.TButton", background=[("active", HOVER)])
        style.configure("TCombobox", padding=5, arrowsize=14,
                        fieldbackground=CARD, background=GHOST, foreground=INK,
                        arrowcolor=INK, bordercolor=BORDER,
                        lightcolor=CARD, darkcolor=CARD)
        style.map("TCombobox",
                  fieldbackground=[("readonly", CARD)],
                  background=[("readonly", GHOST)],
                  foreground=[("readonly", INK)],
                  arrowcolor=[("readonly", INK)],
                  selectbackground=[("readonly", CARD)],
                  selectforeground=[("readonly", INK)])
        self.root.option_add("*TCombobox*Listbox.background", CARD)
        self.root.option_add("*TCombobox*Listbox.foreground", INK)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", ON_ACCENT)

    def _card(self, parent):
        return tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)

    # ------------------------------------------------------------ 主题
    def cycle_theme(self):
        order = ["cream", "night", "candy"]
        i = order.index(self.theme_name) if self.theme_name in order else 0
        self.set_theme(order[(i + 1) % len(order)])

    def set_theme(self, name):
        if name not in THEMES or name == self.theme_name:
            return
        self.theme_name = name
        apply_palette(name)
        self._rebuild_ui()
        self.status.config(text=f"配色：{THEME_LABELS[name]}")

    def _rebuild_ui(self):
        text = self.text.get("1.0", "end").rstrip("\n")
        status = self.status.cget("text")
        auto = self.auto_preview.get()
        if self._preview_job:
            try:
                self.root.after_cancel(self._preview_job)
            except Exception:
                pass
            self._preview_job = None
        for t in getattr(self, "tooltips", []):
            try:
                t._hide()
            except Exception:
                pass
        for w in self.root.winfo_children():
            w.destroy()
        self.sliders = {}
        self.value_labels = {}
        self._setup_style()
        self._build()
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.auto_preview.set(auto)
        self._refresh_preset_list()
        self.preset_var.set(self.voice.name if self.voice.name in self._all_presets() else "自定义")
        self._apply_voice_to_ui(self.voice)
        self.speed_slider.set(self.speed)
        self.speed_value.config(text=f"{self.speed:.2f}×")
        self.status.config(text=status)
        self._draw_wave()
        self.text.focus_set()

    def _build(self):
        self.tooltips = []
        # ---------- 标题 ----------
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=24, pady=(16, 10))
        tk.Label(header, text="哔哔啵啵", bg=BG, fg=INK,
                 font=(FONT, 20, "bold")).pack(side="left")
        tk.Label(header, text="  文字 → 一字一声的叫声", bg=BG, fg=MUTED,
                 font=(FONT, 9)).pack(side="left", pady=(9, 0))
        self.theme_btn = ttk.Button(header, text="◐  换配色", style="Ghost.TButton",
                                    command=self.cycle_theme)
        self.theme_btn.pack(side="right", pady=(4, 0))

        # ---------- 文本框 ----------
        box = self._card(self.root)
        box.pack(fill="x", padx=24)
        self.text = tk.Text(box, height=4, wrap="word", bd=0, relief="flat",
                            bg=CARD, fg=INK, insertbackground=ACCENT,
                            font=(FONT, 12), padx=14, pady=12, undo=True,
                            spacing1=2, spacing3=3)
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", SAMPLE_TEXT)
        self.text.bind("<Control-Return>", lambda e: (self.do_play(), "break")[1])
        self.text.bind("<KeyRelease>", self._on_text_change)
        self.text.bind("<<Modified>>", self._on_text_modified)

        # ---------- 按钮 ----------
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=24, pady=(12, 0))
        ttk.Button(bar, text="▶  试听", style="Accent.TButton",
                   command=self.do_play).pack(side="left")
        ttk.Button(bar, text="■  停止", style="Ghost.TButton",
                   command=self.do_stop).pack(side="left", padx=8)
        ttk.Button(bar, text="⬇  导出 WAV", style="TButton",
                   command=self.do_export).pack(side="left")
        ttk.Button(bar, text="恢复默认", style="Ghost.TButton",
                   command=self.do_reset_voice).pack(side="right")

        # ---------- 波形 ----------
        wave_card = self._card(self.root)
        wave_card.pack(fill="x", padx=24, pady=(12, 0))
        self.canvas = tk.Canvas(wave_card, height=84, bg=CARD, highlightthickness=0)
        self.canvas.pack(fill="x", padx=2, pady=2)
        self.canvas.bind("<Configure>", lambda e: self._draw_wave())

        # ---------- 状态栏（先占住底部） ----------
        self.status = tk.Label(self.root, text="就绪 · 输入文字后点「试听」", bg=BG, fg=MUTED,
                               font=(FONT, 9), anchor="w")
        self.status.pack(side="bottom", fill="x", padx=24, pady=(8, 10))

        # ---------- 参数面板 ----------
        panel = self._card(self.root)
        panel.pack(fill="both", expand=True, padx=24, pady=(12, 0))

        phead = tk.Frame(panel, bg=CARD)
        phead.pack(fill="x", padx=14, pady=(10, 4))
        preset_lbl = tk.Label(phead, text="音色", bg=CARD, fg=INK, font=(FONT, 9),
                              cursor="question_arrow")
        preset_lbl.pack(side="left")
        self.preset_var = tk.StringVar(value="蓝白·哔啵")
        self.preset_box = ttk.Combobox(phead, textvariable=self.preset_var, width=13,
                                       state="readonly", font=(FONT, 9))
        self.preset_box.pack(side="left", padx=(8, 8))
        self.preset_box.bind("<<ComboboxSelected>>", self._on_preset_select)
        ttk.Button(phead, text="🎲 随机捏一个", style="Ghost.TButton",
                   command=self.do_random).pack(side="left")
        ttk.Button(phead, text="收藏", style="Ghost.TButton",
                   command=self.do_save_preset).pack(side="left", padx=4)

        self.auto_preview = tk.BooleanVar(value=False)
        auto_chk = tk.Checkbutton(phead, text="拖动后自动试听", variable=self.auto_preview,
                                  bg=CARD, fg=MUTED, activebackground=CARD, activeforeground=INK,
                                  selectcolor=CARD, font=(FONT, 8), bd=0,
                                  highlightthickness=0)
        auto_chk.pack(side="right")

        self.tooltips.append(Tooltip(
            [preset_lbl, self.preset_box], "音色",
            "选一个现成的音色。每个预设的基调、口型、气声都不一样；右边可以随机捏一个。"))
        self.tooltips.append(Tooltip(
            [auto_chk], "自动试听",
            "勾上以后，拖完滑条松手，会用一小段「哔哔啵啵」自动试音，不用每次都点试听。"))
        preset_lbl.bind("<Enter>", lambda e: preset_lbl.config(fg=ACCENT), add="+")
        preset_lbl.bind("<Leave>", lambda e: preset_lbl.config(fg=INK), add="+")

        grid = tk.Frame(panel, bg=CARD)
        grid.pack(fill="both", expand=True, padx=10, pady=(2, 8))
        self.sliders = {}
        self.value_labels = {}

        # 语速单独放第一个，其他按表排
        items = [("__speed__", "语速", 0.5, 2.0, 2, "×")] + PARAMS
        for i, (key, label, lo, hi, dec, unit) in enumerate(items):
            row, col = i % 5, (i // 5) * 3
            name_lbl = tk.Label(grid, text=label, bg=CARD, fg=INK, width=5, anchor="w",
                                font=(FONT, 9), cursor="question_arrow")
            name_lbl.grid(row=row, column=col, sticky="w", padx=(8, 2), pady=4)
            sl = Slider(grid, lo, hi, lo, decimals=dec,
                        step=(0.05 if key == "__speed__" else None),
                        command=lambda v, k=key: self._on_slider(k, v))
            sl.grid(row=row, column=col + 1, sticky="we", padx=2, pady=4)
            vl = tk.Label(grid, text="", bg=CARD, fg=MUTED, width=7, anchor="e",
                          font=(FONT, 9))
            vl.grid(row=row, column=col + 2, sticky="e", padx=(2, 12))
            if key == "__speed__":
                self.speed_slider = sl
                self.speed_value = vl
            else:
                self.sliders[key] = sl
                self.value_labels[key] = vl

            tip_title, tip_text = PARAM_TIPS.get(key, (label, ""))
            if tip_text:
                self.tooltips.append(Tooltip([name_lbl, sl], tip_title, tip_text))
                name_lbl.bind("<Enter>", lambda e, w=name_lbl: w.config(fg=ACCENT), add="+")
                name_lbl.bind("<Leave>", lambda e, w=name_lbl: w.config(fg=INK), add="+")
        for c in (1, 4, 7):
            grid.columnconfigure(c, weight=1)
        for r in range(5):
            grid.rowconfigure(r, weight=1)

    # ------------------------------------------------------------ 数据
    def _all_presets(self):
        d = dict(bleep.PRESETS)
        for name, data in self.my_presets.items():
            try:
                d[name] = bleep.Voice.from_dict(data)
            except Exception:
                pass
        return d

    def _refresh_preset_list(self):
        names = list(bleep.PRESETS) + list(self.my_presets) + ["自定义"]
        self.preset_box["values"] = names

    def _fmt(self, key, val):
        if key == "__speed__":
            return f"{val:.2f}×"
        dec, unit = self._meta[key]
        return f"{val:.{dec}f}{unit}"

    _meta = {p[0]: (p[4], p[5]) for p in PARAMS}

    def _apply_voice_to_ui(self, voice: bleep.Voice):
        self._loading = True
        for key, sl in self.sliders.items():
            val = getattr(voice, key)
            sl.set(val)
            self.value_labels[key].config(text=self._fmt(key, val))
        self._loading = False

    # ------------------------------------------------------------ 交互
    def _on_text_change(self, event=None):
        self.dirty = True
        if event is not None and event.keysym == "Return":
            return
        self.status.config(text="文字改过了，点「试听」")

    def _on_text_modified(self, event=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.dirty = True

    def _on_preset_select(self, event=None):
        name = self.preset_var.get()
        presets = self._all_presets()
        if name in presets:
            self.voice = replace(presets[name])
            self.voice.name = name
            self._apply_voice_to_ui(self.voice)
            self.dirty = True
            self.status.config(text=f"音色：{name}")

    def _on_slider(self, key, value):
        if self._loading:
            return
        self.dirty = True
        if key == "__speed__":
            self.speed = max(0.5, min(2.0, float(value)))
            self.speed_value.config(text=f"{self.speed:.2f}×")
            self.status.config(text="语速改过了，点「试听」")
        else:
            setattr(self.voice, key, value)
            self.voice.clamp()
            self.voice.name = "自定义"
            self.value_labels[key].config(text=self._fmt(key, value))
            if self.preset_var.get() != "自定义":
                self.preset_var.set("自定义")
            self.status.config(text="参数改过了，点「试听」")
        self._schedule_preview()

    def _schedule_preview(self):
        if not self.auto_preview.get():
            return
        if self._preview_job:
            try:
                self.root.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self.root.after(380, self._auto_preview)

    def _auto_preview(self):
        self._preview_job = None
        try:
            u = bleep.render("哔哔啵啵", self.voice, rate=1.0 / self.speed)
            self.player.play(u.audio)
        except Exception:
            pass

    def do_random(self):
        self.voice = bleep.random_voice()
        self._apply_voice_to_ui(self.voice)
        self.preset_var.set("自定义")
        self.dirty = True
        self.status.config(text="捏了一个随机音色，点「试听」看看喜不喜欢")

    def do_reset_voice(self):
        self.voice = replace(bleep.PRESETS["蓝白·哔啵"])
        self._apply_voice_to_ui(self.voice)
        self.preset_var.set("蓝白·哔啵")
        self.dirty = True
        self.status.config(text="已恢复默认音色")

    def do_save_preset(self):
        name = simpledialog.askstring("收藏音色", "给这个音色起个名字：", parent=self.root)
        if not name:
            return
        name = name.strip()[:12]
        if not name:
            return
        if name in bleep.PRESETS:
            messagebox.showinfo("提示", "这是内置音色的名字，换一个吧。", parent=self.root)
            return
        self.my_presets[name] = self.voice.to_dict()
        self.voice.name = name
        save_json(MY_PRESETS_FILE, self.my_presets)
        self._refresh_preset_list()
        self.preset_var.set(name)
        self.status.config(text=f"已收藏音色「{name}」")

    # ------------------------------------------------------------ 播放 / 导出
    def _current_text(self) -> str:
        return self.text.get("1.0", "end").strip()

    def _render(self):
        text = self._current_text()
        if not text:
            self.status.config(text="先把文字写上呀")
            return None
        rate = 1.0 / max(0.5, min(2.0, self.speed))
        u = bleep.render(text, self.voice, rate=rate)
        self.last_audio = u.audio
        self.last_text = text
        self.last_duration = u.duration
        self.wave_audio = u.audio
        self.dirty = False
        self._draw_wave()
        return u

    def do_play(self):
        try:
            u = self._render()
        except Exception as exc:
            messagebox.showerror("渲染失败", str(exc), parent=self.root)
            return
        if u is None:
            return
        self.player.play(u.audio)
        n = len([e for e in u.events if e.dur > 0])
        self.status.config(text=f"正在播放 · {u.duration:.2f} 秒 · {n} 声 · 44.1kHz")
        self.root.after(int(u.duration * 1000) + 300, self._done_playing)

    def _done_playing(self):
        if self.status.cget("text").startswith("正在播放"):
            self.status.config(text=f"播完了 · {self.last_duration:.2f} 秒 · 想调就拖滑条再试")

    def do_stop(self):
        self.player.stop()
        self.status.config(text="已停止")

    def do_export(self):
        text = self._current_text()
        if not text:
            self.status.config(text="先把文字写上呀")
            return
        if self.last_audio is None or self.last_text != text or self.dirty:
            u = self._render()
            if u is None:
                return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="导出 WAV",
            defaultextension=".wav",
            initialfile=safe_name(text) + ".wav",
            filetypes=[("WAV 音频", "*.wav")],
        )
        if not path:
            return
        bleep.write_wav(path, self.last_audio)
        self.status.config(text=f"已导出：{path}")

    # ------------------------------------------------------------ 波形
    def _draw_wave(self):
        c = self.canvas
        c.delete("all")
        w = max(100, c.winfo_width())
        h = max(50, c.winfo_height())
        c.create_line(0, h / 2, w, h / 2, fill=AXIS)
        if self.wave_audio is None or len(self.wave_audio) == 0:
            c.create_text(w / 2, h / 2, text="试听后这里会出现波形", fill=HINT,
                          font=(FONT, 9))
            return
        x = self.wave_audio
        n = len(x)
        peak = float(max(1e-4, abs(x).max()))
        step = max(1, n // w)
        bars = []
        for i in range(0, n - step, step):
            chunk = x[i:i + step] / peak
            bars.append((float(chunk.max()), float(chunk.min())))
        bw = w / max(1, len(bars))
        for i, (hi, lo) in enumerate(bars):
            xx = i * bw + bw / 2
            c.create_line(xx, h / 2 - hi * (h / 2 - 6), xx, h / 2 - lo * (h / 2 - 6),
                          fill=ACCENT, width=max(1, bw * 0.72))
        c.create_text(w - 8, 10, text=f"{self.last_duration:.2f}s", anchor="e",
                      fill=MUTED, font=(FONT, 8))

    # ------------------------------------------------------------ 设置
    def _load_settings(self):
        data = load_json(SETTINGS_FILE, {})
        try:
            if "voice" in data:
                self.voice = bleep.Voice.from_dict(data["voice"])
            if "speed" in data:
                self.speed = float(data["speed"])
                self.speed_slider.set(self.speed)
        except Exception:
            pass
        if self.voice.name in self._all_presets():
            self.preset_var.set(self.voice.name)
        else:
            self.preset_var.set("自定义")

    def on_close(self):
        save_json(SETTINGS_FILE, {"voice": self.voice.to_dict(),
                                  "speed": self.speed, "theme": self.theme_name})
        self.player.stop()
        self.root.destroy()


def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
