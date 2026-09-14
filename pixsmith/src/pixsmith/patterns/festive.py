"""节日类图案：五星红旗、烟花、月亮。

这一类是**主题件**（中秋 / 国庆 / 春节…）会用到的现成符号。
留在库里当招牌，也顺便证明一件事：**同一套图元能画出「有文化含义的图」**，
而不只是渐变和条纹。
"""

from __future__ import annotations

import math

import numpy as np

from ..color import parse_color
from . import Param, pattern
from ._util import rng

__all__ = []


@pattern("flag_cn", "五星红旗（GB 12982 标准 30×20 网格）", [
    Param("bg", "color", "#DE2910", "旗面红（国旗标准色）"),
    Param("star", "color", "#FFDE00", "星黄（国旗标准色）"),
    Param("padding", "float", 0.0, "四周留白比例 0–0.3"),
], category="festive")
def flag_cn(c, *, bg, star, padding):
    """五颗星的位置与角度都是**算出来的**，不是目测摆的。

    GB 12982 规定旗面为 30×20 网格：大星中心 (5, 5)、外接圆半径 3；
    四颗小星半径 1，中心在 (10,2) (12,4) (12,7) (10,9)，
    **且每颗小星都有一个角尖指向大星中心**。
    """
    pad = min(0.3, max(0.0, float(padding))) * min(c.w, c.h)
    fw, fh = c.w - 2 * pad, c.h - 2 * pad
    # 旗面若比例不是 3:2，按 3:2 居中投放，避免星星被拉变形
    ratio = 3.0 / 2.0
    if fw / fh > ratio:
        fw = fh * ratio
    else:
        fh = fw / ratio
    ox, oy = (c.w - fw) / 2.0, (c.h - fh) / 2.0
    c.rect(ox, oy, fw, fh, bg)

    u = fw / 30.0
    bx, by = ox + 5 * u, oy + 5 * u
    c.star(bx, by, 3 * u, 5, star, ang=-90.0)
    for gx, gy in ((10, 2), (12, 4), (12, 7), (10, 9)):
        sx, sy = ox + gx * u, oy + gy * u
        aim = math.degrees(math.atan2(by - sy, bx - sx))   # 指向大星中心
        c.star(sx, sy, 1 * u, 5, star, ang=aim)
    return c


@pattern("fireworks", "烟花绽放（多组爆发 + 拖尾 + 亮头 + 辉光）", [
    Param("bg", "color", "#05070F", "底色"),
    Param("bursts", "int", 5, "爆发组数"),
    Param("seed", "int", 17, "随机种子"),
    Param("palette", "str", "#FFE9AF,#FFC9C9,#FFF3D6,#FF9E7A,#F2C14E,#9BE7FF",
          "颜色池（逗号分隔）"),
    Param("reach", "float", 0.22, "最大半径 / 画布宽"),
    Param("density", "int", 120, "每组的花瓣条数"),
    Param("core", "bool", True, "是否画中心辉光"),
], category="festive")
def fireworks(c, *, bg, bursts, seed, palette, reach, density, core):
    c.fill(bg)
    g = rng(seed)
    pool = [parse_color(s) for s in str(palette).split(",") if s.strip()]
    if not pool:
        pool = [parse_color("#FFE9AF")]
    n = max(1, int(bursts))
    for _ in range(n):
        cx = float(g.uniform(0.12, 0.88)) * c.w
        cy = float(g.uniform(0.10, 0.55)) * c.h
        base = pool[int(g.integers(0, len(pool)))]
        R = float(g.uniform(0.45, 1.0)) * float(reach) * c.w
        petals = max(8, int(density))
        rot = float(g.uniform(0, math.pi))
        for i in range(petals):
            a = rot + 2 * math.pi * i / petals + float(g.uniform(-0.02, 0.02))
            t = float(g.uniform(0.45, 1.0))
            L = R * t
            alpha = 1.0 - t * 0.55
            c.capsule(cx, cy, cx + math.cos(a) * L, cy + math.sin(a) * L,
                      float(g.uniform(0.8, 1.8)), (base[0], base[1], base[2], alpha))
            c.disc(cx + math.cos(a) * L, cy + math.sin(a) * L,
                   float(g.uniform(1.6, 3.4)),
                   (1.0, 1.0, 1.0, alpha * 0.85))
        if core:
            c.disc(cx, cy, 8.0, (1.0, 1.0, 1.0, 0.86))
            c.disc(cx, cy, 26.0, (base[0], base[1], base[2], 0.35), feather=8.0)
    return c


@pattern("moon", "满月：径向明暗 + 环形山 + 月晕", [
    Param("bg", "color", "#05070F", "底色"),
    Param("body", "color", "#F7F2E2", "月面色"),
    Param("shadow", "color", "#C9C2AE", "背光/暗部色"),
    Param("craters", "int", 11, "环形山数量"),
    Param("seed", "int", 4, "随机种子"),
    Param("glow", "bool", True, "是否画月晕"),
    Param("radius", "float", None, "月面半径（省略按画布自适应）"),
], category="festive")
def moon(c, *, bg, body, shadow, craters, seed, glow, radius):
    c.fill(bg)
    R = float(radius) if radius else min(c.w, c.h) * 0.32
    cx, cy = c.w / 2.0, c.h / 2.0
    if glow:
        for k in range(6, 0, -1):
            c.disc(cx, cy, R * (1.0 + k * 0.075),
                   (*parse_color(shadow)[:3], 0.045), feather=R * 0.30)
    c.disc(cx, cy, R, body)
    # 右下略暗，制造球体感
    c.disc(cx + R * 0.32, cy + R * 0.32, R * 0.82,
           (*parse_color(shadow)[:3], 0.30), feather=R * 0.55)
    g = rng(seed)
    for _ in range(max(0, int(craters))):
        a = float(g.uniform(0, 2 * math.pi))
        rr = R * math.sqrt(float(g.uniform(0.02, 0.86)))
        px, py = cx + math.cos(a) * rr, cy + math.sin(a) * rr
        cr = R * float(g.uniform(0.035, 0.115))
        c.disc(px, py, cr, (*parse_color(shadow)[:3], 0.42), feather=cr * 0.5)
        c.ring(px, py, cr * 1.02, cr * 0.72, (*parse_color(shadow)[:3], 0.30))
    return c
