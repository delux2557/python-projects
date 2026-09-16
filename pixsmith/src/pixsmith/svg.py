"""矢量后端：同一份场景，输出 SVG 而不是 PNG。

它为什么值钱
------------
两个后端各有一条"谁也替代不了"的强项：

| | 位图 (`canvas.py`) | 矢量（本文件） |
|---|---|---|
| 强项 | 逐像素纹理、噪点、非线性滤镜、模糊 | **任意缩放不糊**、文件小、**可编辑**、能放文字 |
| 弱项 | 放大会糊、不可编辑 | 逐像素域的东西表达不了（或极笨重） |
| 典型用途 | 底图、背景、纹理 | **图标、图示、PPT 里要放大的图形** |

（PowerPoint 自 2016 起原生支持 SVG —— 这就是"双后端"对 PPT 场景的直接价值。）

实现机制：**"后处理" = 把已累积的内容包一层**
--------------------------------------------
SVG 里没有"对画布做模糊"这种操作，但有 `<g filter="...">`。
而一元算子（blur / adjust / posterize…）的语义恰好就是"对**目前已画的内容**做变换"，
所以映射是天然的：

    self._content = [f'<g filter="url(#{fid})">' + "".join(self._content) + "</g>"]

`erase_disc`（抠洞）同理，用 `<mask>`：一个白底 + 若干净色圆的 mask，
包住已有内容即可。这样连齿轮的中心孔在矢量后端也是真的透明。

诚实的边界
----------
`capabilities` 里**显式列出**支持的方法。表达不了的两类会在这里被拒，并给出替代方案：
  - `paint`：逐像素场（噪点纹理、半调、暗角）——矢量域没有对应物
  - `grain`：按 seed 的逐像素颗粒 —— SVG 的 `feTurbulence` 是另一回事（不可复现同一粒）
拒绝而不是静默降级，是因为**静默降级会产出"看着对但缺了效果"的图，而 agent 看不见图。**
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

from . import filters as _filters
from .color import parse_color
from .geometry import (regular_polygon_points, rounded_rect_points, star_points)

__all__ = ["SvgBackend"]

_uid = itertools.count(1)

#: 矢量后端支持的能力（= 后端协议里能映射到 SVG 原语的那部分）
SVG_CAPABILITIES = frozenset((
    "fill", "new_layer", "composite", "to_svg", "save",
    "rect", "disc", "ring", "ellipse", "capsule", "arc", "polygon", "line",
    "regular_polygon", "star", "erase_disc",
    "linear_gradient", "radial_gradient",
    "blur", "adjust", "posterize", "solarize", "invert", "grayscale",
    "transform",
))


def _hex8(raw, *, default="#000000FF") -> str:
    """任意颜色写法 → ``#RRGGBBAA``（8 位）。"""
    if raw is None:
        return default
    if isinstance(raw, str) and raw.startswith("var("):
        # CSS 变量原样透传：SVG 本身就能用 CSS 变量（也方便接设计系统的主题色），
        # 变量定义在哪由使用方决定 —— 这里只透传，不解析。
        return raw
    r, g, b, a = parse_color(raw)
    return "#%02X%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255),
                                  round(a * 255))


def _paint(raw) -> str:
    """``#RRGGBBAA`` → ``fill="#RRGGBB" fill-opacity="x"``（不透明时省略 alpha 属性）。"""
    c = _hex8(raw)
    if c.startswith("var("):
        return f'fill="{c}"'
    a = int(c[7:9], 16)
    if a == 255:
        return f'fill="{c[:7]}"'
    return f'fill="{c[:7]}" fill-opacity="{a / 255:.4g}"'


def _n(v) -> str:
    """数字格式化：去掉多余小数位（SVG 体积敏感）。"""
    f = float(v)
    return str(int(f)) if abs(f - round(f)) < 1e-9 else f"{f:.3f}".rstrip("0").rstrip(".")


def _pts(points) -> str:
    return " ".join(f"{_n(x)},{_n(y)}" for x, y in points)


class SvgBackend:
    """矢量后端。接口与 `canvas.Canvas` 对齐 —— 这是"可替换"的全部要求。"""

    capabilities = SVG_CAPABILITIES

    def __init__(self, width: int, height: int):
        self.size = (int(width), int(height))
        self._id = next(_uid)
        self._defs: list[str] = []
        self._content: list[str] = []
        self._erases: list[tuple[float, float, float]] = []

    # ⚠️ 这两个属性不是为了方便，是**协议对称性**：
    # 图案层会写 `c.w` / `c.h`。如果矢量后端没有它们，所有图案都得改成 `c.size[0]`
    # —— 那就是"为了让后端能替换，反而把上层改成最笨的写法"。
    # 双后端的代价应该由后端承担，不该外溢到图案层。（这条是契约测试抓出来的。）
    @property
    def w(self) -> int:
        return self.size[0]

    @property
    def h(self) -> int:
        return self.size[1]

    # ------------------------------------------------------------ 内部
    def _new_id(self, kind: str) -> str:
        return f"ps-{self._id}-{kind}{len(self._defs) + len(self._erases) + 1}"

    def _add_def(self, xml: str) -> None:
        self._defs.append(xml)

    def _add(self, xml: str) -> "SvgBackend":
        self._content.append(xml)
        return self

    def _wrap(self, attr: str) -> "SvgBackend":
        """把"目前已累积的内容"包进一个容器 —— 后处理算子的通用实现。"""
        if self._content:
            inner = "".join(self._content)
            self._content = [f"<g {attr}>{inner}</g>"]
        return self

    # ------------------------------------------------------------ 帧与合成
    def fill(self, color) -> "SvgBackend":
        w, h = self.size
        return self._add(f'<rect x="0" y="0" width="{w}" height="{h}" {_paint(color)}/>')

    def new_layer(self) -> "SvgBackend":
        return SvgBackend(*self.size)

    def composite(self, layer: "SvgBackend", mode: str = "normal",
                  opacity: float = 1.0) -> "SvgBackend":
        if not isinstance(layer, SvgBackend):
            raise TypeError("矢量后端只能合成另一个矢量后端")
        # 子层的 defs 要并入父层；id 已带各自实例前缀，不会撞
        self._defs.extend(layer._defs)
        self._erases.extend(layer._erases)
        style = []
        if str(mode) not in ("normal", "over"):
            style.append(f"mix-blend-mode:{mode}")
        if float(opacity) < 1.0:
            style.append(f"opacity:{float(opacity):.4g}")
        inner = "".join(layer._content)
        attr = f'style="{";".join(style)}"' if style else ""
        return self._add(f"<g {attr}>{inner}</g>" if attr else f"<g>{inner}</g>")

    # ------------------------------------------------------------ 图元
    def rect(self, x, y, w, h, color, *, radius=0) -> "SvgBackend":
        if w <= 0 or h <= 0:
            return self
        r = max(0.0, min(float(radius), min(w, h) / 2.0))
        rx = f' rx="{_n(r)}"' if r > 0 else ""
        return self._add(f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" '
                         f'height="{_n(h)}"{rx} {_paint(color)}/>')

    def disc(self, cx, cy, r, color, *, feather=1.0) -> "SvgBackend":
        if r <= 0:
            return self
        return self._add(f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}" '
                         f'{_paint(color)}/>')

    def ring(self, cx, cy, r_out, r_in, color, *, feather=1.0) -> "SvgBackend":
        if r_out <= 0 or r_out <= r_in:
            return self
        rm = (r_out + r_in) / 2.0
        c = _hex8(color)
        a = int(c[7:9], 16)
        alpha = f' stroke-opacity="{a / 255:.4g}"' if a != 255 else ""
        return self._add(f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(rm)}" '
                         f'fill="none" stroke="{c[:7]}" stroke-width="{_n(r_out - r_in)}"'
                         f'{alpha}/>')

    def ellipse(self, cx, cy, rx, ry, color, *, ang=0.0) -> "SvgBackend":
        if rx <= 0 or ry <= 0:
            return self
        rot = f' transform="rotate({_n(ang)} {_n(cx)} {_n(cy)})"' if ang else ""
        return self._add(f'<ellipse cx="{_n(cx)}" cy="{_n(cy)}" rx="{_n(rx)}" '
                         f'ry="{_n(ry)}"{rot} {_paint(color)}/>')

    def capsule(self, x0, y0, x1, y1, r, color) -> "SvgBackend":
        if r <= 0:
            return self
        c = _hex8(color)
        a = int(c[7:9], 16)
        alpha = f' stroke-opacity="{a / 255:.4g}"' if a != 255 else ""
        return self._add(f'<line x1="{_n(x0)}" y1="{_n(y0)}" x2="{_n(x1)}" '
                         f'y2="{_n(y1)}" stroke="{c[:7]}" stroke-width="{_n(r * 2)}" '
                         f'stroke-linecap="round"{alpha}/>')

    def arc(self, cx, cy, r_out, r_in, a0, a1, color) -> "SvgBackend":
        if r_out <= 0 or r_out <= r_in:
            return self
        sweep = (a1 - a0) % (2 * math.pi)
        if sweep == 0:
            sweep = 2 * math.pi
        ro, ri = (r_out + r_in) / 2.0, (r_out - r_in) / 2.0
        large = 1 if sweep > math.pi else 0
        p0 = (cx + math.cos(a0) * ro, cy + math.sin(a0) * ro)
        p1 = (cx + math.cos(a0 + sweep) * ro, cy + math.sin(a0 + sweep) * ro)
        d = (f"M {_n(p0[0])} {_n(p0[1])} "
             f"A {_n(ro)} {_n(ro)} 0 {large} 1 {_n(p1[0])} {_n(p1[1])}")
        c = _hex8(color)
        a = int(c[7:9], 16)
        alpha = f' stroke-opacity="{a / 255:.4g}"' if a != 255 else ""
        return self._add(f'<path d="{d}" fill="none" stroke="{c[:7]}" '
                         f'stroke-width="{_n(ri * 2)}" stroke-linecap="butt"{alpha}/>')

    def polygon(self, points, color, *, ss: int = 3) -> "SvgBackend":
        pts = list(points)
        if len(pts) < 3:
            return self
        return self._add(f'<polygon points="{_pts(pts)}" {_paint(color)}/>')

    def line(self, points, width, color, *, cap: bool = True) -> "SvgBackend":
        pts = list(points)
        if len(pts) < 2:
            if len(pts) == 1 and cap:
                return self.disc(pts[0][0], pts[0][1], float(width) / 2.0, color)
            return self
        c = _hex8(color)
        a = int(c[7:9], 16)
        alpha = f' stroke-opacity="{a / 255:.4g}"' if a != 255 else ""
        return self._add(f'<polyline points="{_pts(pts)}" fill="none" '
                         f'stroke="{c[:7]}" stroke-width="{_n(width)}" '
                         f'stroke-linecap="round" stroke-linejoin="round"{alpha}/>')

    def regular_polygon(self, cx, cy, r, sides, color, *, ang=-90.0, ss=3):
        return self.polygon(regular_polygon_points(cx, cy, r, sides, ang=ang), color)

    def star(self, cx, cy, r, points, color, *, ang=-90.0, inner=0.382, ss=3):
        return self.polygon(star_points(cx, cy, r, points, ang=ang, inner=inner), color)

    def erase_disc(self, cx, cy, r, *, feather=1.0) -> "SvgBackend":
        """抠透明孔：记下来，最后统一用一个 `<mask>` 罩住全部内容。"""
        if r > 0:
            self._erases.append((float(cx), float(cy), float(r)))
        return self

    # ------------------------------------------------------------ 渐变
    def linear_gradient(self, begin, end, angle=90.0, mid=None, mid_at=0.5):
        w, h = self.size
        gid = self._new_id("lg")
        a = math.radians(float(angle))
        # 把角度换算成 SVG 的对象包围盒单位向量（0°=向右，90°=向下）
        dx, dy = math.cos(a), math.sin(a)
        stops = [(0.0, begin), (1.0, end)]
        if mid:
            stops.insert(1, (float(mid_at), mid))
        body = "".join(
            f'<stop offset="{_n(t * 100)}%" stop-color="{_hex8(c)[:7]}" '
            f'stop-opacity="{int(_hex8(c)[7:9], 16) / 255:.4g}"/>'
            for t, c in stops)
        self._add_def(f'<linearGradient id="{gid}" x1="{_n(50 - dx * 50)}%" '
                      f'y1="{_n(50 - dy * 50)}%" x2="{_n(50 + dx * 50)}%" '
                      f'y2="{_n(50 + dy * 50)}%">{body}</linearGradient>')
        return self._add(f'<rect x="0" y="0" width="{w}" height="{h}" '
                         f'fill="url(#{gid})"/>')

    def radial_gradient(self, inner, outer, cx=None, cy=None, radius=None):
        w, h = self.size
        gid = self._new_id("rg")
        cx = w / 2.0 if cx is None else float(cx)
        cy = h / 2.0 if cy is None else float(cy)
        if radius:
            r = float(radius)
        else:
            r = float(max(math.hypot(cx, cy), math.hypot(w - cx, cy),
                          math.hypot(cx, h - cy), math.hypot(w - cx, h - cy)))
        body = "".join(
            f'<stop offset="{_n(t * 100)}%" stop-color="{_hex8(c)[:7]}" '
            f'stop-opacity="{int(_hex8(c)[7:9], 16) / 255:.4g}"/>'
            for t, c in ((0.0, inner), (1.0, outer)))
        self._add_def(f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" '
                      f'cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(max(r, 1))}">'
                      f'{body}</radialGradient>')
        return self._add(f'<rect x="0" y="0" width="{w}" height="{h}" '
                         f'fill="url(#{gid})"/>')

    # ------------------------------------------------------------ 一元算子
    def blur(self, radius=12.0, passes=3) -> "SvgBackend":
        r = float(radius)
        if r <= 0:
            return self
        fid = self._new_id("blur")
        self._add_def(f'<filter id="{fid}" x="-25%" y="-25%" width="150%" '
                      f'height="150%"><feGaussianBlur stdDeviation="{_n(r / 2.0)}"/>'
                      f"</filter>")
        return self._wrap(f'filter="url(#{fid})"')

    def adjust(self, brightness=1.0, contrast=1.0, saturation=1.0, hue=0.0,
               gamma=1.0) -> "SvgBackend":
        prims: list[str] = []
        if saturation != 1.0 or hue != 0.0:
            m = _filters.hue_saturation_matrix(hue, saturation)
            vals = " ".join(_n(v) for v in m.reshape(-1))
            prims.append(f'<feColorMatrix type="matrix" values="{vals}"/>')
        slope = float(brightness) * float(contrast)
        intercept = float(brightness) * (1.0 - float(contrast)) / 2.0
        if abs(slope - 1.0) > 1e-6 or abs(intercept) > 1e-6:
            funcs = "".join(f'<feFunc{k} type="linear" slope="{_n(slope)}" '
                            f'intercept="{_n(intercept)}"/>' for k in "RGB")
            prims.append(f"<feComponentTransfer>{funcs}</feComponentTransfer>")
        if gamma != 1.0:
            funcs = "".join(f'<feFunc{k} type="gamma" amplitude="1" '
                            f'exponent="{_n(1.0 / max(1e-4, float(gamma)))}" '
                            f'offset="0"/>' for k in "RGB")
            prims.append(f"<feComponentTransfer>{funcs}</feComponentTransfer>")
        if not prims:
            return self
        fid = self._new_id("adj")
        self._add_def(f'<filter id="{fid}">{"".join(prims)}</filter>')
        return self._wrap(f'filter="url(#{fid})"')

    def posterize(self, levels=6) -> "SvgBackend":
        n = max(2, int(levels))
        table = [i / (n - 1) for i in range(n)]
        fid = self._new_id("post")
        funcs = "".join(f'<feFunc{k} type="discrete" '
                        f'tableValues="{" ".join(_n(v) for v in table)}"/>'
                        for k in "RGB")
        self._add_def(f'<filter id="{fid}"><feComponentTransfer>{funcs}'
                      f"</feComponentTransfer></filter>")
        return self._wrap(f'filter="url(#{fid})"')

    def solarize(self, threshold=0.5) -> "SvgBackend":
        t = min(1.0, max(0.0, float(threshold)))
        n = 17
        table = [v / (n - 1) for v in range(n)]
        vec = [v if v <= t else 1.0 - v for v in table]
        fid = self._new_id("sol")
        funcs = "".join(f'<feFunc{k} type="table" '
                        f'tableValues="{" ".join(_n(v) for v in vec)}"/>'
                        for k in "RGB")
        self._add_def(f'<filter id="{fid}"><feComponentTransfer>{funcs}'
                      f"</feComponentTransfer></filter>")
        return self._wrap(f'filter="url(#{fid})"')

    def invert(self) -> "SvgBackend":
        fid = self._new_id("inv")
        funcs = "".join(f'<feFunc{k} type="table" tableValues="1 0"/>' for k in "RGB")
        self._add_def(f'<filter id="{fid}"><feComponentTransfer>{funcs}'
                      f"</feComponentTransfer></filter>")
        return self._wrap(f'filter="url(#{fid})"')

    def grayscale(self, amount=1.0) -> "SvgBackend":
        k = min(1.0, max(0.0, float(amount)))
        if k <= 0:
            return self
        fid = self._new_id("gray")
        self._add_def(f'<filter id="{fid}"><feColorMatrix type="saturate" '
                      f'values="{_n(1.0 - k)}"/></filter>')
        return self._wrap(f'filter="url(#{fid})"')

    # ------------------------------------------------------------ 输出
    def transform(self, *, rotate=0.0, scale=1.0, translate=None, pivot=None,
                  flip="none", crop=None) -> "SvgBackend":
        """整幅仿射变换 —— 矢量端**就这么一下**：把已绘内容包进 ``<g transform="matrix(…)">``。

        这正是本文件开头那条机制的又一次套用：一元算子（blur / adjust / …）的语义是
        "对**目前已画的内容**做变换"，而仿射变换的语义**完全相同**，所以映射是天然的。
        而且矢量端没有"重采样"这回事，所以旋转缩放是**无损、精确**的 ——
        位图端是双线性重采样会略软，这是两端固有的射程差别。

        矩阵来自 `geometry.affine_matrix`，与位图后端**共用同一份**：
        两端的旋转中心、镜像轴因此必然重合（这比"两边各写一遍三角函数"可靠得多）。

        坐标是连续坐标（像素 i 的中心在 i + 0.5），而 SVG 的用户坐标系里像素 i 覆盖
        ``[i, i+1]`` —— 两者的"画布中心"都是 ``(W/2, H/2)``，所以不需要额外补偿。
        """
        from .geometry import affine_is_identity, affine_matrix

        m = affine_matrix(size=self.size, rotate=rotate, scale=scale,
                          translate=translate, pivot=pivot, flip=flip, crop=crop)
        if affine_is_identity(m):
            return self
        a, b, c, d, e, f = m
        return self._wrap(f'transform="matrix({_n(a)} {_n(b)} {_n(c)} '
                          f'{_n(d)} {_n(e)} {_n(f)})"')

    def to_svg(self) -> str:
        w, h = self.size
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
                 f'viewBox="0 0 {w} {h}">']
        if self._defs:
            parts.append(f"<defs>{''.join(self._defs)}</defs>")
        if self._erases:
            mid = self._new_id("mask")
            holes = "".join(f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{_n(r)}" '
                            f'fill="black"/>' for x, y, r in self._erases)
            parts.append(f'<defs><mask id="{mid}">'
                         f'<rect x="0" y="0" width="{w}" height="{h}" fill="white"/>'
                         f"{holes}</mask></defs>")
            parts.append(f'<g mask="url(#{mid})">{"".join(self._content)}</g>')
        else:
            parts.append("".join(self._content))
        parts.append("</svg>")
        return "\n".join(parts)

    def save(self, path) -> str:
        p = Path(path)
        if p.suffix.lower() != ".svg":
            raise ValueError(
                f"矢量后端只能写 .svg（收到 {p.suffix}）。"
                f"要 PNG 请用位图后端：`pixsmith render <场景> --backend raster`。")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_svg(), encoding="utf-8")
        return str(p)
