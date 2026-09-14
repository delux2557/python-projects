"""后端无关的几何构造：**只算形状，不碰像素**。

为什么要把几何单独拆出来
------------------------
项目要同时服务两种输出（位图 PNG 与矢量 SVG）。同一个齿轮的齿廓，位图后端要拿去
填充像素，矢量后端要拿去写成 `<path d="...">` —— **顶点是共用的，渲染才是分叉的**。

如果顶点计算写在绘制函数里（`c.star(...)` 里现算现画），这个形状就被**锁死在位图后端上**，
以后想加矢量输出就得把每个形状的实现抄一遍。所以这里把"算"和"画"分开：

    geometry.py   算顶点（后端无关，纯函数，可单测）
    backend.py    画（各后端自己实现，只认"给我顶点，我填充"）
"""

from __future__ import annotations

import math

Point = tuple[float, float]

__all__ = ["star_points", "regular_polygon_points", "ring_segment_points",
           "gear_points", "capsule_bounds", "polar"]


def polar(cx: float, cy: float, r: float, ang_deg: float) -> Point:
    """极坐标转直角坐标。``ang_deg`` 按屏幕直觉：0° 向右、90° 向下、-90° 向上。"""
    a = math.radians(ang_deg)
    return (cx + math.cos(a) * r, cy + math.sin(a) * r)


def star_points(cx: float, cy: float, r: float, points: int = 5, *,
                ang: float = -90.0, inner: float = 0.382) -> list[Point]:
    """正 N 角星的 2N 个顶点（外/内半径交替）。

    ``ang`` 是**第一个外顶点**的方向，默认 -90°（一个角朝正上）。
    这一点很重要：国旗的小星需要"一个角尖指向大星中心"，实现方式就是把 ``ang``
    设成 atan2 求出的方位角（见 ``patterns/festive.py``）。
    """
    n = max(3, int(points))
    step = 360.0 / (n * 2)
    out: list[Point] = []
    for i in range(n * 2):
        rr = r if i % 2 == 0 else r * float(inner)
        out.append(polar(cx, cy, rr, ang + i * step))
    return out


def regular_polygon_points(cx: float, cy: float, r: float, sides: int, *,
                           ang: float = -90.0) -> list[Point]:
    """正 N 边形顶点。"""
    n = max(3, int(sides))
    return [polar(cx, cy, r, ang + 360.0 * i / n) for i in range(n)]


def ring_segment_points(cx: float, cy: float, r_out: float, r_in: float,
                        a0: float, a1: float, *, segments: int | None = None
                        ) -> list[Point]:
    """环段（甜甜圈的一段）的外轮廓点列 —— 用多边形近似替代表达不了的"弧带"。

    ``a0`` / ``a1`` 为**弧度**，坐标系 y 向下（0 = 右、π/2 = 下、3π/2 = 上）。
    返回：外弧正向 + 内弧反向，首尾相接成闭合环。
    """
    if r_out <= 0 or r_out <= r_in:
        return []
    sweep = (a1 - a0) % (2 * math.pi)
    if sweep == 0:
        sweep = 2 * math.pi
    n = segments or max(6, int(math.ceil(math.degrees(sweep) / 6.0)))
    outer, inner = [], []
    for i in range(n + 1):
        a = a0 + sweep * i / n
        outer.append((cx + math.cos(a) * r_out, cy + math.sin(a) * r_out))
        inner.append((cx + math.cos(a) * r_in, cy + math.sin(a) * r_in))
    return outer + inner[::-1]


def gear_points(cx: float, cy: float, r: float, teeth: int, *,
                tooth: float = 0.20, taper: float = 0.82) -> list[Point]:
    """齿轮的**完整外轮廓**（含齿），返回单个闭合多边形。

    ``r`` 是齿顶半径；齿根半径由 ``tooth``（齿高 / 外半径）反推。
    相比"一圈小多边形拼齿"，单个多边形的好处：两个后端都只需要一个 `polygon()`，
    而且不会在齿根留下抗锯齿接缝。
    """
    n = max(3, int(teeth))
    r_out = r / (1.0 + max(0.02, float(tooth)))
    half = 0.40 * math.pi / n
    out: list[Point] = []
    for i in range(n):
        a = 2 * math.pi * i / n
        out.append((cx + math.cos(a - half) * r_out, cy + math.sin(a - half) * r_out))
        out.append((cx + math.cos(a - half * taper) * r, cy + math.sin(a - half * taper) * r))
        out.append((cx + math.cos(a + half * taper) * r, cy + math.sin(a + half * taper) * r))
        out.append((cx + math.cos(a + half) * r_out, cy + math.sin(a + half) * r_out))
    return out


def capsule_bounds(x0: float, y0: float, x1: float, y1: float, r: float):
    """胶囊（两端带半圆的线段）的包围盒 —— 两个后端都需要它来定画布范围。"""
    return (min(x0, x1) - r, min(y0, y1) - r, max(x0, x1) + r, max(y0, y1) + r)


def rounded_rect_points(x: float, y: float, w: float, h: float, r: float,
                        *, segments: int = 6) -> list[Point]:
    """圆角矩形的闭合顶点列。

    为什么用顶点而不是"圆角矩形"专用图元：**两个后端更省事**。
    位图后端把它交给 `polygon()`，矢量后端本来就只需要一个带 `rx` 的 `<rect>`
    （那条路径不走这里）。这样"圆角"在两端都只有一处实现。
    """
    rr = max(0.0, min(float(r), min(w, h) / 2.0))
    if rr <= 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    pts: list[Point] = []
    corners = ((x + w - rr, y + rr, -90.0), (x + w - rr, y + h - rr, 0.0),
               (x + rr, y + h - rr, 90.0), (x + rr, y + rr, 180.0))
    for cx, cy, a0 in corners:
        for i in range(segments + 1):
            pts.append(polar(cx, cy, rr, a0 + 90.0 * i / segments))
    return pts
