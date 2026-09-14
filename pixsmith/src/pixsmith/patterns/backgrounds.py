"""背景类图案：渐变、条纹、网格、噪点…… 大幅面底图与版式背景的主力。

这一类是**最通用**的 —— 不挑主题，任何海报 / 汇报材料 / 界面图都用得上。
"""

from __future__ import annotations

import numpy as np

from ..color import gradient_stops, parse_color
from . import Param, pattern
from ._util import dir_field, pct, radial_field, rng

__all__ = []


@pattern("gradient", "线性渐变底色（可加中段色标）", [
    Param("begin", "color", "#0A1730", "起始色"),
    Param("end", "color", "#C8102E", "结束色"),
    Param("mid", "color", None, "中段色（留空则纯双色渐变）"),
    Param("mid_at", "float", 0.5, "中段色位置 0–1"),
    Param("angle", "float", 90.0, "角度：0=从左到右，90=从上到下"),
], category="background")
def gradient(c, *, begin, end, mid, mid_at, angle):
    """走后端协议（位图铺像素场 / 矢量写 <linearGradient>），所以**双后端通用**。"""
    c.linear_gradient(begin, end, angle, mid, mid_at)
    return c


@pattern("radial", "径向渐变（中心到边缘）", [
    Param("inner", "color", "#F2C14E", "中心色"),
    Param("outer", "color", "#0A1730", "边缘色"),
    Param("cx", "float", None, "中心 x（省略取画布中心）"),
    Param("cy", "float", None, "中心 y（省略取画布中心）"),
    Param("radius", "float", None, "渐变半径（省略取到最远角）"),
], category="background")
def radial(c, *, inner, outer, cx, cy, radius):
    c.radial_gradient(inner, outer, cx, cy, radius)
    return c


@pattern("stripes", "等宽斜/直条纹", [
    Param("c0", "color", "#12161F", "底色"),
    Param("c1", "color", "#1E2430", "条纹色"),
    Param("count", "int", 24, "条纹条数"),
    Param("angle", "float", 90.0, "角度：0=竖条纹，90=横条纹"),
    Param("ratio", "float", 0.5, "条纹占空比 0–1"),
    Param("soft", "float", 0.0, "边缘羽化（0=硬边）"),
], category="background", requires=("paint",))
def stripes(c, *, c0, c1, count, angle, ratio, soft):
    t = dir_field(c.w, c.h, angle) * max(1, int(count))
    frac = np.mod(t, 1.0)
    ratio = min(1.0, max(0.0, float(ratio)))
    if soft > 0:
        edge = max(1e-6, float(soft)) * 0.5
        mask = 1.0 - np.clip((frac - ratio) / edge, 0.0, 1.0)
        mask *= np.clip(frac / edge, 0.0, 1.0)
    else:
        mask = (frac < ratio).astype(np.float32)
    c.paint(np.broadcast_to(np.asarray(parse_color(c0)[:3], np.float32),
                            (c.h, c.w, 3)))
    a = np.asarray(parse_color(c1)[3], np.float32) * mask
    c.paint(np.broadcast_to(np.asarray(parse_color(c1)[:3], np.float32),
                            (c.h, c.w, 3)), a)
    return c


@pattern("checker", "棋盘格", [
    Param("c0", "color", "#0F1420", "深格"),
    Param("c1", "color", "#1B2230", "浅格"),
    Param("cell", "int", 48, "格子边长 px"),
    Param("angle", "float", 0.0, "整体旋转角（0=正交）"),
], category="background", requires=("paint",))
def checker(c, *, c0, c1, cell, angle):
    cell = max(2, int(cell))
    if abs(float(angle)) < 1e-6:
        ix = (np.arange(c.w) // cell)
        iy = (np.arange(c.h) // cell)
        parity = (ix[None, :] + iy[:, None]) % 2
    else:
        t = dir_field(c.w, c.h, angle) * c.w
        u = np.mod(t, cell) / cell
        v = np.mod(dir_field(c.w, c.h, angle + 90.0) * c.h, cell) / cell
        parity = ((u < 0.5).astype(np.int8) ^ (v < 0.5).astype(np.int8))
    stops = [(0.0, c0), (1.0, c1)]
    c.paint(gradient_stops(stops, parity.astype(np.float32)))
    return c


@pattern("dots", "点阵底纹", [
    Param("bg", "color", "#0B1020", "底色"),
    Param("dot", "color", "#3A4A70", "点色"),
    Param("cell", "int", 44, "点阵间距 px"),
    Param("radius", "float", 6.0, "点半径 px"),
    Param("stagger", "bool", True, "是否错行排列"),
], category="background")
def dots(c, *, bg, dot, cell, radius, stagger):
    c.fill(bg)
    cell = max(4, int(cell))
    oy = cell / 2.0
    rows = int(c.h / cell) + 2
    cols = int(c.w / cell) + 2
    for r in range(rows):
        shift = (cell / 2.0) if (stagger and r % 2) else 0.0
        for i in range(cols):
            c.disc(i * cell + shift, r * cell + oy, float(radius), dot)
    return c


@pattern("noise", "颗粒噪点叠加", [
    Param("base", "color", "#0A1730", "底色"),
    Param("amount", "float", 0.10, "噪点强度 0–1"),
    Param("seed", "int", 7, "随机种子（决定可复现）"),
    Param("mono", "bool", True, "是否灰度噪点（否则彩色）"),
], category="background", requires=("paint",))
def noise(c, *, base, amount, seed, mono):
    c.fill(base)
    g = rng(seed)
    amount = min(1.0, max(0.0, float(amount)))
    r = (g.random((c.h, c.w), dtype=np.float32) - 0.5) * amount
    if mono:
        delta = r
    else:
        delta = (g.random((c.h, c.w, 3), dtype=np.float32) - 0.5) * amount
    rgb = np.broadcast_to(np.asarray(parse_color(base)[:3], np.float32),
                          (c.h, c.w, 3)) + (delta[..., None] if mono else delta)
    c.paint(np.clip(rgb, 0.0, 1.0))
    return c


@pattern("grid", "网格 / 蓝图底纹", [
    Param("bg", "color", "#0A1730", "底色"),
    Param("line", "color", "#3E6FA8", "细线色"),
    Param("major", "color", "#E8B33C", "主线色"),
    Param("step", "int", 48, "细线间距 px"),
    Param("every", "int", 5, "每几格一根主线"),
    Param("width", "float", 1.2, "细线宽"),
    Param("major_width", "float", 2.4, "主线宽"),
], category="background")
def grid(c, *, bg, line, major, step, every, width, major_width):
    c.fill(bg)
    step = max(2, int(step))
    every = max(1, int(every))
    coords = list(range(0, max(c.w, c.h) + 1, step))
    for i, p in enumerate(coords):
        col = major if (i % every == 0) else line
        w = float(major_width) if (i % every == 0) else float(width)
        # 用 capsule 而不是 hline/vline：后者是 Canvas 的便利方法，不在后端协议里。
        # 图案只用协议方法，才能同时跑在位图与矢量两个后端上。
        if p <= c.w:
            c.capsule(p + 0.5, 0, p + 0.5, c.h, w / 2.0, col)
        if p <= c.h:
            c.capsule(0, p + 0.5, c.w, p + 0.5, w / 2.0, col)
    return c


@pattern("rings", "同心圆环底纹", [
    Param("bg", "color", "#0A1730", "底色"),
    Param("ring", "color", "#F2C14E", "环色"),
    Param("count", "int", 12, "环数"),
    Param("cx", "float", None, "圆心 x"),
    Param("cy", "float", None, "圆心 y"),
    Param("radius", "float", None, "最外环半径"),
    Param("width", "float", 2.0, "环宽 px"),
], category="background")
def rings(c, *, bg, ring, count, cx, cy, radius, width):
    c.fill(bg)
    cx = c.w / 2.0 if cx is None else float(cx)
    cy = c.h / 2.0 if cy is None else float(cy)
    R = float(radius) if radius else max(c.w, c.h) * 0.62
    n = max(1, int(count))
    half = float(width) / 2.0
    for i in range(1, n + 1):
        r = R * i / n
        c.ring(cx, cy, r + half, max(0.0, r - half), ring)
    return c


@pattern("vignette", "四角压暗（叠在已有内容上）", [
    Param("color", "color", "#000000", "暗角颜色"),
    Param("strength", "float", 0.55, "最暗处不透明度 0–1"),
    Param("power", "float", 1.6, "收缩陡度（越大暗角越小）"),
], category="background", requires=("paint",))
def vignette(c, *, color, strength, power):
    t = radial_field(c.w, c.h)
    a = np.clip(t, 0.0, 1.0) ** max(0.05, float(power))
    c.paint(np.broadcast_to(np.asarray(parse_color(color)[:3], np.float32),
                            (c.h, c.w, 3)),
            a * min(1.0, max(0.0, float(strength))))
    return c
