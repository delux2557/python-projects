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
           "gear_points", "capsule_bounds", "polar",
           "Affine", "affine_identity", "affine_mul", "affine_invert",
           "affine_apply", "affine_is_identity", "affine_matrix"]


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


# ==================================================================== 仿射
#: 2D 仿射矩阵：``(a, b, c, d, e, f)`` —— 与 SVG 的 ``matrix(a b c d e f)`` **逐字对应**：
#:
#:     x' = a·x + c·y + e
#:     y' = b·x + d·y + f
#:
#: 刻意沿用 SVG 的写法而不是"3×3 数组"：矢量后端拿到它一个 ``matrix(…)`` 就写完了，
#: 位图后端用同一份数字求逆 —— **两个后端共用一份几何**，
#: 从根上杜绝"位图的旋转中心和矢量的差半个像素"这类对不上的问题。
#: 这里只用 ``math``，不碰 numpy：几何是后端无关的，两个后端都要用。
Affine = tuple[float, float, float, float, float, float]

#: `flip` 参数的别名表 → 两个轴的符号。
#: 用 h/v 而不是 x/y，因为"沿 x 轴翻转"到底指左右还是上下，两种读法都说得通 —— 有歧义的参数名是坑。
_FLIP_SIGNS: dict[str, tuple[float, float]] = {
    "none": (1.0, 1.0), "": (1.0, 1.0), "no": (1.0, 1.0),
    "h": (-1.0, 1.0), "horizontal": (-1.0, 1.0), "水平": (-1.0, 1.0),
    "v": (1.0, -1.0), "vertical": (1.0, -1.0), "垂直": (1.0, -1.0),
    "both": (-1.0, -1.0), "hv": (-1.0, -1.0), "vh": (-1.0, -1.0),
    "两个": (-1.0, -1.0),
}


def affine_identity() -> Affine:
    return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def affine_mul(m: Affine, n: Affine) -> Affine:
    """``m ∘ n``：**先把 ``n`` 作用上去，再作用 ``m``**（与矩阵乘法同序）。"""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def affine_invert(m: Affine) -> Affine:
    """解析求逆。行列式退化时**抛错**，不返回一个会把图算成垃圾的"差不多"矩阵。"""
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise ValueError(
            f"仿射矩阵不可逆（行列式 {det:.3g}）—— 检查 scale 是不是 0")
    ia, ib, ic, idd = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, idd, -(ia * e + ic * f), -(ib * e + idd * f))


def affine_apply(m: Affine, x: float, y: float) -> Point:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def affine_is_identity(m: Affine, tol: float = 1e-9) -> bool:
    """是不是什么都不做 —— 用来**省掉一整轮重采样**（全默认参数时）。"""
    a, b, c, d, e, f = m
    return (abs(a - 1.0) < tol and abs(d - 1.0) < tol
            and abs(b) < tol and abs(c) < tol and abs(e) < tol and abs(f) < tol)


def affine_flip_signs(flip) -> tuple[float, float]:
    """`flip` 参数 → 两个轴的符号；不认识的值报错并列出可用值（不静默当 none）。"""
    key = "none" if flip is None else str(flip).strip().lower()
    if key not in _FLIP_SIGNS:
        raise ValueError(f"flip 不认识 {flip!r}（可用：none / h / v / both）")
    return _FLIP_SIGNS[key]


def affine_matrix(*, size, rotate=0.0, scale=1.0, translate=None, pivot=None,
                  flip="none", crop=None) -> Affine:
    """把「给人看的参数」组装成**源坐标 → 画布坐标**的仿射矩阵。

    复合顺序（矩阵乘法从右往左读）：

        M = T(translate) · T(pivot) · R(rotate) · S(scale) · F(flip) · T(-pivot) · C(crop)

    - ``crop`` 是**最内层**：先把 ``[x, y, w, h]`` 这块取景区线性铺满整张画布，
      后面的旋转 / 缩放 / 平移都作用在"已铺满"的结果上。
      取景区比例 ≠ 画布比例时它天然就是**非等比拉伸** —— 所以 ``scale`` 只做等比，
      非等比请走 ``crop``：**一个参数一种类型**，不让 agent 去猜"这里能不能传数组"。
    - ``rotate`` / ``scale`` / ``flip`` 都绕 ``pivot``（默认画布中心）。
    - 坐标是**连续坐标**：像素 i 的中心在 ``i + 0.5``，所以画布中心正好是 ``(W/2, H/2)``。
    - ``rotate`` 正方向 = 屏幕上顺时针（与 ``polar`` 的"0° 向右、90° 向下"同一套直觉）。

    ⚠️ ``pivot`` / ``translate`` / ``crop`` 都是**绝对像素**（和 ``rect`` 的 ``x``/``y``
    一个路数）。所以 ``export --sizes`` 那种"同一份场景换尺寸再渲染"不会连带缩放它们 ——
    只想改尺寸时保持 ``rotate``/``scale``/``flip`` 就够了（它们本来就绕中心，天然与尺寸无关）。
    """
    w, h = int(size[0]), int(size[1])
    if w < 1 or h < 1:
        raise ValueError(f"画布尺寸必须 ≥ 1，收到 {w}×{h}")
    if not float(scale) > 0:
        raise ValueError(f"scale 必须 > 0，收到 {scale}（想做镜像请用 flip='h'/'v'）")

    m = affine_identity()

    # ① 取景（最内层）：把源坐标系线性映射到画布
    if crop is not None:
        cx, cy, cw, ch = (float(v) for v in crop)
        if cw <= 0 or ch <= 0:
            raise ValueError(f"crop 的宽高必须 > 0，收到 {cw}×{ch}")
        sx, sy = w / cw, h / ch
        m = (sx, 0.0, 0.0, sy, -cx * sx, -cy * sy)

    # ② 绕支点的旋转 · 等比缩放 · 镜像
    fx, fy = affine_flip_signs(flip)
    px, py = ((w / 2.0, h / 2.0) if pivot is None
              else (float(pivot[0]), float(pivot[1])))

    def rot(deg: float) -> Affine:
        r = math.radians(deg)
        co, si = math.cos(r), math.sin(r)
        return (co, si, -si, co, 0.0, 0.0)

    inner = affine_mul(rot(float(rotate)),
                       (float(scale), 0.0, 0.0, float(scale), 0.0, 0.0))
    inner = affine_mul(inner, (fx, 0.0, 0.0, fy, 0.0, 0.0))
    m = affine_mul(affine_mul((1.0, 0.0, 0.0, 1.0, px, py), inner),
                   affine_mul((1.0, 0.0, 0.0, 1.0, -px, -py), m))

    # ③ 平移（最外层）：画布坐标上的纯偏移
    if translate is not None:
        m = affine_mul((1.0, 0.0, 0.0, 1.0, float(translate[0]),
                        float(translate[1])), m)
    return m
