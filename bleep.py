# -*- coding: utf-8 -*-
"""
哔哔啵啵 · 声音引擎
====================

把一段文字变成「一字一声」的哔啵叫声（动物森友会那种感觉），
所有音色参数都可调，也可以直接导出 WAV。

单独使用：
    python bleep.py "你好呀，今天也要开心！" -p 蓝白·哔啵 -o hello.wav
    python bleep.py --list                 # 看内置音色
    python bleep.py "..." --random --seed 7  # 随机捏一个音色

作为库使用：
    import bleep
    u = bleep.render("你好", bleep.PRESETS["蓝白·哔啵"])
    bleep.write_wav("a.wav", u.audio)
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import wave
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

import numpy as np

SR = 44100

# 元音共振峰（F1, F2, F3），单位 Hz，按「标准嗓音」给的近似值
VOWELS = {
    "a": (800.0, 1150.0, 2900.0),
    "e": (480.0, 1750.0, 2600.0),
    "i": (320.0, 2200.0, 3000.0),
    "o": (460.0, 820.0, 2800.0),
    "u": (340.0, 720.0, 2500.0),
}

# 停顿表（秒）
PAUSES = {
    "，": 0.11, ",": 0.11,
    "、": 0.09,
    "；": 0.14, ";": 0.14,
    "：": 0.14, ":": 0.14,
    "。": 0.26, ".": 0.26,
    "！": 0.26, "!": 0.26,
    "？": 0.26, "?": 0.26,
    "…": 0.30,
    "—": 0.16, "-": 0.10,
    "～": 0.12, "~": 0.12,
    "\n": 0.32,
    "　": 0.20,
}

END_PUNCT = "。！？!?….～~"


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


@dataclass
class Voice:
    """一个音色的全部参数。"""

    name: str = "自定义"

    f0: float = 460.0          # 基调 Hz：整串叫声的基准音高
    range_semi: float = 6.0    # 音域：随机走音的最大跨度（半音）
    length_ms: float = 72.0    # 每一声多长
    gap_ms: float = 32.0       # 两声之间空多久
    jitter_ms: float = 12.0    # 每一声长度的随机抖动
    glide: float = -0.8        # 一声之内滑音多少半音（负=往下滑）
    vibrato: float = 0.0       # 颤音幅度（半音）
    vibrato_hz: float = 6.0    # 颤音速度
    buzz: float = 0.55         # 谐波量：0 接近纯正弦，1 很方很复古
    vowel: float = 0.6         # 元音感：0 是纯电子音，1 明显在"说话"
    formant: float = 1.12      # 共振峰整体缩放（>1 更小只更脆）
    breath: float = 0.04       # 气声/噪声
    drive: float = 0.08        # 颗粒感（软削波）
    sub: float = 0.0           # 低八度混合，加厚
    volume: float = 0.85       # 播放音量

    def clamp(self) -> "Voice":
        self.f0 = _clamp(self.f0, 80.0, 1200.0)
        self.range_semi = _clamp(self.range_semi, 0.0, 24.0)
        self.length_ms = _clamp(self.length_ms, 18.0, 300.0)
        self.gap_ms = _clamp(self.gap_ms, 0.0, 300.0)
        self.jitter_ms = _clamp(self.jitter_ms, 0.0, 120.0)
        self.glide = _clamp(self.glide, -12.0, 12.0)
        self.vibrato = _clamp(self.vibrato, 0.0, 4.0)
        self.vibrato_hz = _clamp(self.vibrato_hz, 1.0, 30.0)
        self.buzz = _clamp(self.buzz, 0.0, 1.0)
        self.vowel = _clamp(self.vowel, 0.0, 1.0)
        self.formant = _clamp(self.formant, 0.4, 2.5)
        self.breath = _clamp(self.breath, 0.0, 1.0)
        self.drive = _clamp(self.drive, 0.0, 1.0)
        self.sub = _clamp(self.sub, 0.0, 1.0)
        self.volume = _clamp(self.volume, 0.0, 1.0)
        return self

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known}).clamp()


def _preset(name, **kw):
    return Voice(name=name, **kw).clamp()


PRESETS = {
    "蓝白·哔啵": _preset(
        "蓝白·哔啵", f0=520, range_semi=6, length_ms=70, gap_ms=30, jitter_ms=10,
        glide=-0.9, buzz=0.55, vowel=0.66, formant=1.14, breath=0.035, drive=0.05,
    ),
    "黑白·哔啵": _preset(
        "黑白·哔啵", f0=330, range_semi=4.5, length_ms=84, gap_ms=34, jitter_ms=12,
        glide=-0.6, buzz=0.42, vowel=0.55, formant=0.96, breath=0.055, drive=0.10, sub=0.15,
    ),
    "小黄鸭": _preset(
        "小黄鸭", f0=760, range_semi=9, length_ms=56, gap_ms=22, jitter_ms=10,
        glide=1.6, buzz=0.70, vowel=0.80, formant=1.55, breath=0.10, drive=0.15,
    ),
    "电子宠物": _preset(
        "电子宠物", f0=620, range_semi=8, length_ms=46, gap_ms=18, jitter_ms=4,
        glide=0.0, buzz=1.0, vowel=0.0, formant=1.0, breath=0.0, drive=0.25,
    ),
    "老机器人": _preset(
        "老机器人", f0=210, range_semi=2, length_ms=92, gap_ms=26, jitter_ms=6,
        glide=-1.2, buzz=0.82, vowel=0.10, formant=0.72, breath=0.0, drive=0.35, sub=0.3,
    ),
    "耳语小幽灵": _preset(
        "耳语小幽灵", f0=480, range_semi=5, length_ms=96, gap_ms=36, jitter_ms=18,
        glide=-0.2, buzz=0.22, vowel=0.72, formant=1.2, breath=0.52, drive=0.0, volume=0.7,
    ),
}

PRESET_ORDER = list(PRESETS)


def random_voice(rng: random.Random | None = None) -> Voice:
    """随便捏一个音色（但保证能听）。"""
    rng = rng or random.Random()
    f0 = math.exp(rng.uniform(math.log(240), math.log(760)))
    return Voice(
        name="随机·%02d" % rng.randint(10, 99),
        f0=f0,
        range_semi=rng.uniform(0, 9),
        length_ms=rng.uniform(45, 100),
        gap_ms=rng.uniform(15, 55),
        jitter_ms=rng.uniform(3, 18),
        glide=rng.uniform(-2.5, 2.5),
        vibrato=rng.choice([0, 0, rng.uniform(0.1, 0.6)]),
        vibrato_hz=rng.uniform(4, 9),
        buzz=rng.uniform(0.15, 1.0),
        vowel=rng.uniform(0.0, 0.9),
        formant=rng.uniform(0.8, 1.5),
        breath=rng.uniform(0.0, 0.25),
        drive=rng.uniform(0.0, 0.35),
        sub=rng.choice([0, 0, rng.uniform(0.1, 0.3)]),
        volume=0.85,
    ).clamp()


# ---------------------------------------------------------------- 合成核心

def _formant_gain(freqs, vowel_key, voice, jitter=1.0):
    """给每个谐波算一个共振峰增益。"""
    scale = voice.formant * jitter * (voice.f0 / 400.0) ** 0.25
    fmt = np.array(VOWELS[vowel_key]) * scale
    gain = np.ones_like(freqs)
    for F in fmt:
        width = max(70.0, F * 0.16)
        gain += voice.vowel * 3.2 * np.exp(-0.5 * ((freqs - F) / width) ** 2)
    return gain


def _render_blip(voice: Voice, sr: int, dur: float, semi_a: float, semi_b: float,
                 vowel_key: str, rng: random.Random, gain: float = 1.0):
    n = max(24, int(round(dur * sr)))
    t = np.arange(n, dtype=np.float64) / sr
    prog = t / max(dur, 1e-6)

    semi = semi_a + (semi_b - semi_a) * prog
    if voice.vibrato > 0:
        ramp = np.minimum(1.0, t / 0.025)
        semi = semi + voice.vibrato * ramp * np.sin(2 * math.pi * voice.vibrato_hz * t)

    f = voice.f0 * np.exp2(semi / 12.0)
    phase = 2 * math.pi * np.cumsum(f) / sr

    # 谐波加法合成：K 个正弦，按 1/k^tilt 衰减
    f_mid = float(np.mean(f))
    tilt = 2.3 - 1.75 * voice.buzz
    K = int(min(40, (sr * 0.45) / max(f_mid, 1.0)))
    K = max(1, K)
    ks = np.arange(1, K + 1, dtype=np.float64)
    amps = 1.0 / ks ** tilt
    amps *= _formant_gain(ks * f_mid, vowel_key, voice, jitter=rng.uniform(0.94, 1.06))
    amps /= max(1e-9, float(np.sum(amps)))
    gain *= rng.uniform(0.88, 1.04)

    wave_out = np.sin(phase[None, :] * ks[:, None]) * amps[:, None]
    sig = wave_out.sum(axis=0)

    if voice.sub > 0:
        sig += voice.sub * 0.55 * np.sin(phase * 0.5)

    if voice.breath > 0:
        noise = np.array([rng.gauss(0.0, 1.0) for _ in range(n)])
        kernel = np.exp(-np.arange(48) / 10.0)
        noise = np.convolve(noise, kernel, mode="same")
        noise /= max(1e-9, np.max(np.abs(noise)))
        sig += voice.breath * 0.55 * noise

    # 包络：快起、指数衰减、尾巴淡出，避免爆音
    env = np.ones(n)
    attack = max(1, min(int(0.004 * sr), n // 3))
    env[:attack] = np.linspace(0.0, 1.0, attack) ** 0.7
    env *= np.exp(-2.1 * prog)
    tail = max(1, min(int(0.006 * sr), n // 3))
    env[-tail:] *= np.linspace(1.0, 0.0, tail)

    sig *= env

    if voice.drive > 0:
        k = 1.0 + voice.drive * 7.0
        sig = np.tanh(sig * k) / math.tanh(k)

    peak = float(np.max(np.abs(sig))) or 1.0
    return (sig / peak * gain).astype(np.float32)


def _vowel_for(ch: str, idx: int) -> str:
    low = ch.lower()
    if low in VOWELS:
        return low
    # 中文/其它字符：按码点稳定映射，同一个字永远是同一个口型
    return "aeiou"[(ord(ch) * 7 + idx * 3) % 5]


@dataclass
class Event:
    pos: int      # 在原文里的下标
    t: float      # 开始时间（秒）
    dur: float    # 这一声多长
    f0: float     # 实际频率
    ch: str


@dataclass
class Utterance:
    text: str
    audio: np.ndarray
    events: list
    duration: float


PUNCT_SET = set(PAUSES.keys())


def _build_plan(text: str, voice: Voice, rng: random.Random, rate: float):
    """把文本排成时间线：每一段要么是停顿，要么是一声。"""
    units = []
    for i, ch in enumerate(text):
        if ch in PAUSES:
            units.append({"kind": "pause", "pos": i, "ch": ch, "dur": PAUSES[ch] * rate})
        elif ch.isspace():
            units.append({"kind": "pause", "pos": i, "ch": ch, "dur": 0.07 * rate})
        elif ch in "\"'“”‘’()（）[]【】《》<>`*#@":
            units.append({"kind": "pause", "pos": i, "ch": ch, "dur": 0.02 * rate})
        else:
            units.append({"kind": "blip", "pos": i, "ch": ch})

    blips = [u for u in units if u["kind"] == "blip"]

    # 分句：遇到句末标点就切一段
    sentences = []
    cur = []
    for u in units:
        if u["kind"] == "blip":
            cur.append(u)
        elif u["ch"] in END_PUNCT and cur:
            sentences.append((cur, u["ch"]))
            cur = []
    if cur:
        sentences.append((cur, ""))

    # 五声音阶随机走音
    scale = [0.0, 2.0, 4.0, 7.0, 9.0, 12.0]
    stretch = voice.range_semi / 12.0

    for sents, end in sentences:
        idx = rng.randint(1, 3)
        prev = None
        for j, u in enumerate(sents):
            if j == 0:
                idx = rng.randint(1, 3)
            else:
                idx = int(_clamp(idx + rng.choice([-2, -1, 0, 0, 1, 1, 2]), 0, 5))
            semi = scale[idx] * stretch
            u["semi"] = semi
            u["vowel"] = _vowel_for(u["ch"], u["pos"])

        # 句末语调
        sents[-1]["last"] = True
        n = len(sents)
        if end in "？?":
            for k, u in enumerate(sents[-min(3, n):]):
                u["semi"] += 0.9 * (k + 1) * min(1.0, 2.0 / max(1, n - 2))
        elif end in "！!":
            for k, u in enumerate(sents[-min(2, n):]):
                u["semi"] += 0.7 * (k + 1)
        elif end in "。.":
            for k, u in enumerate(sents[-min(2, n):]):
                u["semi"] -= 0.9 * (k + 1)

    t = 0.06
    events = []
    for u in units:
        if u["kind"] == "pause":
            events.append(Event(u["pos"], t, 0.0, 0.0, u["ch"]))
            t += u["dur"]
        else:
            dur_ms = voice.length_ms * rate + rng.uniform(-voice.jitter_ms, voice.jitter_ms)
            dur_ms = max(20.0, dur_ms)
            dur = dur_ms / 1000.0
            gap = max(0.0, voice.gap_ms * rate + rng.uniform(-4, 4)) / 1000.0
            semi_a = u["semi"]
            semi_b = semi_a + voice.glide
            f0 = voice.f0 * 2 ** (semi_a / 12)
            u.update(dur=dur, start=t, semi_a=semi_a, semi_b=semi_b)
            events.append(Event(u["pos"], t, dur, f0, u["ch"]))
            t += dur + gap
    return units, events, t


def render(text: str, voice: Voice | None = None, sr: int = SR,
           seed: int | None = None, rate: float = 1.0) -> Utterance:
    """把文字渲染成一整段音频。rate>1 更慢，rate<1 更快。"""
    text = (text or "").strip()
    if voice is None:
        voice = PRESETS["蓝白·哔啵"]
    voice.clamp()
    rng = random.Random(seed) if seed is not None else random.Random()

    if not text:
        return Utterance(text="", audio=np.zeros(int(0.1 * sr), dtype=np.float32),
                         events=[], duration=0.1)

    units, events, total = _build_plan(text, voice, rng, rate)
    total += 0.12
    buf = np.zeros(int(total * sr) + 1, dtype=np.float32)

    for u in units:
        if u["kind"] != "blip":
            continue
        start = int(u["start"] * sr)
        seg = _render_blip(voice, sr, u["dur"], u["semi_a"], u["semi_b"],
                           u["vowel"], rng)
        end = min(len(buf), start + len(seg))
        buf[start:end] += seg[:end - start]

    peak = float(np.max(np.abs(buf))) or 1.0
    buf = buf / peak * 0.92
    # 整句首尾淡入淡出，避免咔哒
    fade = min(int(0.004 * sr), len(buf) // 4)
    if fade > 0:
        buf[:fade] *= np.linspace(0, 1, fade)
        buf[-fade:] *= np.linspace(1, 0, fade)

    buf *= max(0.0, min(1.0, voice.volume))
    return Utterance(text=text, audio=buf, events=events, duration=len(buf) / sr)


def write_wav(path: str | Path, audio: np.ndarray, sr: int = SR):
    """16bit 单声道 PCM。"""
    data = np.clip(audio, -1.0, 1.0)
    pcm = (data * 32767.0).astype("<i2")
    path = str(path)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def render_to_wav(text: str, path: str | Path, voice: Voice | None = None,
                  sr: int = SR, seed: int | None = None, rate: float = 1.0):
    u = render(text, voice, sr=sr, seed=seed, rate=rate)
    write_wav(path, u.audio, sr)
    return u


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="把文字变成哔哔啵啵的叫声")
    ap.add_argument("text", nargs="?", help="要念的文字")
    ap.add_argument("-p", "--preset", default="蓝白·哔啵", help="音色名，见 --list")
    ap.add_argument("-o", "--out", default="bleep.wav", help="输出 wav 路径")
    ap.add_argument("--rate", type=float, default=1.0, help="语速倍率，>1 更慢")
    ap.add_argument("--seed", type=int, default=None, help="随机种子，固定后音高走向可复现")
    ap.add_argument("--random", action="store_true", help="随机捏一个音色")
    ap.add_argument("--list", action="store_true", help="列出内置音色")
    ap.add_argument("--json", action="store_true", help="把音色参数打成 JSON 打印出来")
    args = ap.parse_args(argv)

    if args.list:
        for name in PRESET_ORDER:
            v = PRESETS[name]
            print(f"{name:<10} 基调 {v.f0:>4.0f}Hz  字长 {v.length_ms:>3.0f}ms  "
                  f"音域 {v.range_semi:>3.1f}半音  谐波 {v.buzz:.2f}")
        return 0

    if args.random:
        voice = random_voice(random.Random(args.seed))
        if args.seed is not None:
            voice.name = "随机·%d" % args.seed
    else:
        if args.preset not in PRESETS:
            print("没有这个音色：%s\n可用的有：%s" % (args.preset, "、".join(PRESET_ORDER)))
            return 2
        voice = replace(PRESETS[args.preset])

    text = args.text or "你好呀，我是哔哔啵啵。"
    u = render_to_wav(text, args.out, voice, seed=args.seed, rate=args.rate)
    if args.json:
        print(voice.to_dict())
    print("已生成 %s  (%.2f 秒, %d 声)" % (args.out, u.duration, len(u.events)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
