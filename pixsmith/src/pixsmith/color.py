"""颜色解析与插值。

统一约定：**内部一律用「单位浮点 RGBA」**（每通道 0.0–1.0），
只在写出 PNG 的那一刻才转成 0–255 整数 —— 与参考实现的边缘行为一致。
"""

from __future__ import annotations

from typing import Iterable

RGBA = tuple[float, float, float, float]
RGB = tuple[float, float, float]

__all__ = ["parse_color", "to_rgba8", "lerp", "with_alpha", "darken", "lighten",
           "gradient_stops"]


def _hex_to_rgb(s: str) -> RGB:
    s = s.lstrip("#")
    if len(s) == 3:                                  # #abc → #aabbcc
        s = "".join(ch * 2 for ch in s)
    if len(s) not in (6, 8):
        raise ValueError(f"颜色字面量长度不合法：{s!r}（应为 #RGB / #RRGGBB / #RRGGBBAA）")
    if not all(ch in "0123456789abcdefABCDEF" for ch in s):
        raise ValueError(f"颜色字面量含非法字符：{s!r}")
    return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0)


def _hex_alpha(s: str) -> float | None:
    s = s.lstrip("#")
    if len(s) == 8:
        return int(s[6:8], 16) / 255.0
    return None


def parse_color(c, alpha: float | None = None) -> RGBA:
    """把多种写法归一成单位浮点 RGBA。

    接受：``"#RGB"`` / ``"#RRGGBB"`` / ``"#RRGGBBAA"`` / ``"rgba?"`` 不解析、
    ``(r, g, b)`` / ``(r, g, b, a)``；整数元组按 **0–255** 解释，
    浮点元组按 **0.0–1.0** 解释。``alpha`` 显式给出时覆盖字面量里的 alpha。
    """
    if isinstance(c, str):
        rgb = _hex_to_rgb(c)
        a = _hex_alpha(c)
        a = 1.0 if a is None else a
    elif isinstance(c, (tuple, list)):
        vals = tuple(c)
        if len(vals) not in (3, 4):
            raise ValueError(f"颜色元组长度不合法：{c!r}（应为 3 或 4 元组）")
        if all(isinstance(v, int) for v in vals):
            rgb = tuple(v / 255.0 for v in vals[:3])
            a = vals[3] / 255.0 if len(vals) == 4 else 1.0
        else:
            rgb = tuple(float(v) for v in vals[:3])
            a = float(vals[3]) if len(vals) == 4 else 1.0
    else:
        raise TypeError(f"不支持的颜色写法：{type(c).__name__}")
    if alpha is not None:
        a = float(alpha)
    return (rgb[0], rgb[1], rgb[2], min(1.0, max(0.0, a)))


def to_rgba8(c: RGBA) -> tuple[int, int, int, int]:
    """单位浮点 RGBA → 0–255 整数（四舍五入，与参考实现一致）。"""
    return tuple(int(round(max(0.0, min(1.0, v)) * 255)) for v in c)  # type: ignore[return-value]


def lerp(c1, c2, t: float) -> RGBA:
    """两个颜色之间线性插值，``t`` 自动夹到 [0, 1]。"""
    a, b = parse_color(c1), parse_color(c2)
    t = 0.0 if t < 0 else 1.0 if t > 1 else float(t)
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))  # type: ignore[return-value]


def with_alpha(c, a: float) -> RGBA:
    r, g, b, _ = parse_color(c)
    return (r, g, b, min(1.0, max(0.0, float(a))))


def darken(c, amount: float = 0.2) -> RGBA:
    r, g, b, a = parse_color(c)
    k = 1.0 - min(1.0, max(0.0, amount))
    return (r * k, g * k, b * k, a)


def lighten(c, amount: float = 0.2) -> RGBA:
    r, g, b, a = parse_color(c)
    k = min(1.0, max(0.0, amount))
    return (r + (1 - r) * k, g + (1 - g) * k, b + (1 - b) * k, a)


def gradient_stops(stops: Iterable[tuple[float, object]], t):
    """按色标表对 ``t``（标量或 ndarray）求值，返回形状 ``(..., 4)`` 的数组。

    这是给渐变类配方用的底层工具：先用 NumPy 算出 ``t`` 场，再一次性上色。
    """
    import numpy as np

    pts = sorted(((float(p), parse_color(c)) for p, c in stops), key=lambda p: p[0])
    if len(pts) < 2:
        raise ValueError("色标表至少需要两个色标")
    ts = np.asarray(t, dtype=np.float32)
    out = np.empty(ts.shape + (4,), dtype=np.float32)
    idx = np.clip(np.searchsorted([p for p, _ in pts], ts, side="right") - 1,
                  0, len(pts) - 2)
    t0 = np.array([p for p, _ in pts], dtype=np.float32)[idx]
    t1 = np.array([p for p, _ in pts], dtype=np.float32)[idx + 1]
    span = np.where(t1 - t0 == 0, 1.0, t1 - t0)
    f = np.clip((ts - t0) / span, 0.0, 1.0)[..., None]
    c0 = np.array([c for _, c in pts], dtype=np.float32)[idx]
    c1 = np.array([c for _, c in pts], dtype=np.float32)[idx + 1]
    np.copyto(out, c0 + (c1 - c0) * f)
    return out
