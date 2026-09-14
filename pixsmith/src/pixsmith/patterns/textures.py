"""纹理类图案：星空、半调网点、扫描线。

介于「背景」与「插画」之间 —— 单独放一层是因为它们**既要铺满画布**，
**又要靠随机/调制产生细节**，用参数控制密度比用多张图拼更划算。
"""

from __future__ import annotations

import numpy as np

from ..color import parse_color
from . import Param, pattern
from ._util import radial_field, rng

__all__ = []


def _split_colors(spec: str) -> list[str]:
    return [s.strip() for s in str(spec).split(",") if s.strip()]


@pattern("starfield", "星空：随机星点 + 光晕（可叠银河带）", [
    Param("bg", "color", "#05070F", "底色"),
    Param("count", "int", 420, "星点数量"),
    Param("seed", "int", 21, "随机种子"),
    Param("colors", "str", "#FFFFFF,#FFE9AF,#FFC9C9,#BDD8FF", "星色池（逗号分隔）"),
    Param("max_radius", "float", 2.6, "最大星半径 px"),
    Param("glow", "bool", True, "大星是否带光晕"),
    Param("milky", "float", 0.0, "银河带强度 0–0.35"),
], category="texture",
   requires_fn=lambda p: ("paint",) if float(p.get("milky") or 0) > 0 else ())
def starfield(c, *, bg, count, seed, colors, max_radius, glow, milky):
    c.fill(bg)
    if float(milky) > 0:
        band = np.exp(-((np.linspace(0, 1, c.h, dtype=np.float32)[:, None] - 0.42) ** 2)
                      / (2 * 0.16 ** 2)).astype(np.float32)
        c.paint(np.broadcast_to(np.asarray(parse_color("#8FB7E8")[:3], np.float32),
                                (c.h, c.w, 3)),
                band * float(milky))
    g = rng(seed)
    pool = [parse_color(s) for s in _split_colors(colors)]
    n = max(0, int(count))
    for _ in range(n):
        x = float(g.uniform(0, c.w))
        y = float(g.uniform(0, c.h))
        s = float(g.choice([0.7, 1.0, 1.3, 1.8]) * float(max_radius) / 2.6)
        col = pool[int(g.integers(0, len(pool)))]
        a = float(g.uniform(0.35, 0.98))
        c.disc(x, y, s, (col[0], col[1], col[2], a))
        if glow and s > float(max_radius) * 0.68:
            c.disc(x, y, s * 2.6, (col[0], col[1], col[2], a * 0.22), feather=2.4)
    return c


@pattern("halftone", "半调网点：点径随参数场变化（径向/线性）", [
    Param("bg", "color", "#FFFFFF", "底色"),
    Param("dot", "color", "#1B2230", "网点色"),
    Param("cell", "int", 26, "网点间距 px"),
    Param("mode", "str", "radial", "调制方式：radial | linear"),
    Param("angle", "float", 90.0, "linear 模式的角度"),
    Param("min_ratio", "float", 0.10, "最暗处点径系数"),
    Param("max_ratio", "float", 0.98, "最亮处点径系数"),
], category="texture")
def halftone(c, *, bg, dot, cell, mode, angle, min_ratio, max_ratio):
    c.fill(bg)
    cell = max(4, int(cell))
    if str(mode) == "linear":
        from ._util import dir_field
        field = dir_field(c.w, c.h, angle)
    else:
        field = radial_field(c.w, c.h)
    ratio = float(min_ratio) + (float(max_ratio) - float(min_ratio)) * field
    base_r = cell / 2.0
    for iy in range(int(c.h / cell) + 2):
        y = iy * cell + cell / 2.0
        if y > c.h + base_r:
            break
        for ix in range(int(c.w / cell) + 2):
            x = ix * cell + cell / 2.0
            if x > c.w + base_r:
                break
            r = base_r * float(ratio[min(c.h - 1, int(y)), min(c.w - 1, int(x))])
            if r > 0.25:
                c.disc(x, y, r, dot)
    return c


@pattern("scanlines", "扫描线 / 屏幕栅格", [
    Param("bg", "color", "#0A0F18", "底色"),
    Param("line", "color", "#39FF88", "线色"),
    Param("gap", "int", 6, "线间距 px"),
    Param("alpha", "float", 0.28, "线不透明度"),
    Param("width", "float", 1.6, "线宽 px"),
    Param("seed", "int", 5, "随机种子（决定个别亮线）"),
    Param("hot", "int", 8, "额外亮线数量"),
], category="texture")
def scanlines(c, *, bg, line, gap, alpha, width, seed, hot):
    c.fill(bg)
    gap = max(2, int(gap))
    col = parse_color(line)
    for y in range(0, c.h, gap):
        c.capsule(0, y + 0.5, c.w, y + 0.5, float(width) / 2.0,
                  (col[0], col[1], col[2], float(alpha)))
    if int(hot) > 0:
        g = rng(seed)
        for _ in range(int(hot)):
            y = float(g.uniform(0, c.h))
            c.capsule(0, y, c.w, y, float(width) * 0.9,
                      (col[0], col[1], col[2], min(1.0, float(alpha) * 2.6)))
    return c
