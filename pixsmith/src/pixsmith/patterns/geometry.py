"""几何类图案：光芒阵列、齿轮、透视地板、星形。

这一类是「**用一个函数画出一个符号**」—— 参数就是几何量，
所以尺寸改了形状不走样，可以直接喂给不同画布。
"""

from __future__ import annotations

import math

import numpy as np

from ..color import parse_color
from . import Param, pattern
from ._util import rng

__all__ = []


@pattern("ray_burst", "放射光芒阵列（烟花底 / 光晕）", [
    Param("bg", "color", "#00000000", "底色（默认透明）"),
    Param("count", "int", 72, "光芒条数"),
    Param("cx", "float", None, "中心 x（省略取画布中心）"),
    Param("cy", "float", None, "中心 y"),
    Param("inner", "float", 0.0, "从中心多远开始（占比 0–1）"),
    Param("length", "float", 1.0, "最大长度占比 0–1"),
    Param("color", "color", "#FFE9AF", "光芒颜色"),
    Param("width", "float", 3.0, "光芒宽度 px"),
    Param("jitter", "float", 0.012, "角度抖动（弧度）"),
    Param("seed", "int", 5, "随机种子"),
    Param("core", "bool", True, "中心是否画实心核"),
], category="shape")
def ray_burst(c, *, bg, count, cx, cy, inner, length, color, width, jitter, seed, core):
    col = parse_color(bg)
    if col[3] > 0:
        c.fill(bg)
    cx = c.w / 2.0 if cx is None else float(cx)
    cy = c.h / 2.0 if cy is None else float(cy)
    n = max(1, int(count))
    g = rng(seed)
    reach = max(c.w, c.h) * 0.5 * min(1.0, max(0.05, float(length)))
    r0 = reach * min(1.0, max(0.0, float(inner)))
    for i in range(n):
        a = 2 * math.pi * i / n + float(g.uniform(-jitter, jitter))
        L = reach * float(g.uniform(0.55, 1.0))
        w = float(width) * float(g.uniform(0.6, 1.6))
        c.capsule(cx + math.cos(a) * r0, cy + math.sin(a) * r0,
                  cx + math.cos(a) * L, cy + math.sin(a) * L, w, color)
    if core:
        cc = parse_color(color)
        c.disc(cx, cy, float(width) * 2.2, color)
        c.disc(cx, cy, float(width) * 7.0, (cc[0], cc[1], cc[2], 0.10),
               feather=max(2.0, float(width) * 4.0))
    return c


@pattern("gear", "齿轮：中空外圈 + 渐开齿 + 辐条 + 轮毂", [
    Param("bg", "color", "#00000000", "底色（默认透明）"),
    Param("color", "color", "#F2C14E", "齿轮颜色"),
    Param("teeth", "int", 18, "齿数"),
    Param("cx", "float", None, "中心 x"),
    Param("cy", "float", None, "中心 y"),
    Param("radius", "float", None, "外半径（省略按画布自适应）"),
    Param("tooth", "float", 0.20, "齿高 / 外半径"),
    Param("spokes", "int", 6, "辐条数（0 = 不画）"),
    Param("hub", "float", 0.22, "轮毂半径 / 外半径"),
    Param("hole", "float", 0.40, "中心孔半径 / 轮毂半径"),
], category="shape")
def gear(c, *, bg, color, teeth, cx, cy, radius, tooth, spokes, hub, hole):
    if parse_color(bg)[3] > 0:
        c.fill(bg)
    cx = c.w / 2.0 if cx is None else float(cx)
    cy = c.h / 2.0 if cy is None else float(cy)
    R = float(radius) if radius else min(c.w, c.h) * 0.42
    n = max(3, int(teeth))
    t_h = max(0.02, float(tooth))
    r_out = R / (1.0 + t_h)          # 齿顶 = R，齿根按 tooth 反推
    r_in = r_out * 0.80
    c.ring(cx, cy, r_out, r_in, color)
    half = 0.40 * math.pi / n
    for i in range(n):
        a = 2 * math.pi * i / n
        pts = [(cx + math.cos(a - half) * r_out, cy + math.sin(a - half) * r_out),
               (cx + math.cos(a - half * 0.82) * R, cy + math.sin(a - half * 0.82) * R),
               (cx + math.cos(a + half * 0.82) * R, cy + math.sin(a + half * 0.82) * R),
               (cx + math.cos(a + half) * r_out, cy + math.sin(a + half) * r_out)]
        c.polygon(pts, color, ss=3)
    sp = int(spokes)
    for i in range(sp):
        a = 2 * math.pi * i / sp
        c.capsule(cx, cy, cx + math.cos(a) * r_in * 0.99,
                  cy + math.sin(a) * r_in * 0.99, R * 0.055, color)
    r_hub = R * min(0.9, max(0.02, float(hub)))
    c.disc(cx, cy, r_hub, color)
    r_hole = r_hub * min(0.95, max(0.0, float(hole)))
    if r_hole > 0.5:
        c.erase_disc(cx, cy, r_hole)      # 中心孔：真透明，不冒充底色
    return c


@pattern("perspective_grid", "透视地板（透视纵深网格）", [
    Param("bg", "color", "#05070F", "底色"),
    Param("line", "color", "#F2C14E", "线色"),
    Param("vanish", "float", 0.5, "消失点横向位置 0–1"),
    Param("horizon", "float", 0.0, "地平线 y 位置占比 0–1"),
    Param("rays", "int", 15, "每侧射线数"),
    Param("spread", "float", 0.16, "底部散开系数"),
    Param("rows", "int", 22, "横向行数"),
    Param("growth", "float", 1.31, "行距等比放大系数（决定纵深）"),
    Param("width", "float", 1.6, "线宽 px"),
    Param("alpha", "float", 0.45, "线不透明度"),
], category="shape")
def perspective_grid(c, *, bg, line, vanish, horizon, rays, spread, rows, growth,
                     width, alpha):
    c.fill(bg)
    col = parse_color(line)
    a = float(alpha)
    stroke = (col[0], col[1], col[2], a)
    vx = c.w * min(1.0, max(0.0, float(vanish)))
    y0 = c.h * min(1.0, max(0.0, float(horizon)))
    n = max(1, int(rays))
    for i in range(-n, n + 1):
        x_top = vx + i * (c.w * 0.030)
        x_bot = vx + i * (c.w * float(spread))
        c.capsule(x_top, y0, x_bot, c.h, float(width) / 2.0, stroke)
    y = y0 + max(3.0, c.h * 0.01)
    step = max(3.0, c.h * 0.01)
    for _ in range(max(1, int(rows))):
        if y >= c.h:
            break
        c.capsule(0, y, c.w, y, float(width) / 2.0, stroke)
        step *= float(growth)
        y += step
    return c


@pattern("star", "正星形（五角星 / N 角星）", [
    Param("bg", "color", "#00000000", "底色（默认透明）"),
    Param("color", "color", "#FFDE00", "星色"),
    Param("points", "int", 5, "角数"),
    Param("cx", "float", None, "中心 x"),
    Param("cy", "float", None, "中心 y"),
    Param("radius", "float", None, "外接圆半径（省略按画布自适应）"),
    Param("inner", "float", 0.382, "内接半径比例（0.382 = 标准五角星）"),
    Param("rotate", "float", -90.0, "旋转角（-90 = 一个角朝正上）"),
    Param("outline", "color", None, "描边色（留空则不描边）"),
    Param("outline_width", "float", 4.0, "描边宽度 px"),
], category="shape")
def star(c, *, bg, color, points, cx, cy, radius, inner, rotate, outline,
         outline_width):
    if parse_color(bg)[3] > 0:
        c.fill(bg)
    cx = c.w / 2.0 if cx is None else float(cx)
    cy = c.h / 2.0 if cy is None else float(cy)
    R = float(radius) if radius else min(c.w, c.h) * 0.45
    pts = []
    n = max(3, int(points))
    step = 360.0 / (n * 2)
    for i in range(n * 2):
        rr = R if i % 2 == 0 else R * float(inner)
        a = math.radians(float(rotate) + i * step)
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    c.polygon(pts, color, ss=3)
    if outline:
        oc = parse_color(outline)
        for i in range(len(pts)):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % len(pts)]
            c.capsule(ax, ay, bx, by, float(outline_width) / 2.0, outline)
    return c
