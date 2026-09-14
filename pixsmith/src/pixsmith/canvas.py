"""NumPy 版画布：图元 + 覆盖率抗锯齿 + Alpha 合成。

与参考实现（`benchmarks/pure_python_reference.py`，纯 Python 的 `PixelCanvas`）的差别只有一个：
**同一套覆盖率公式改用 NumPy 在整个包围盒上一次性算完**。逐像素的合成公式没变，
所以两者的输出可以逐像素互相校验。

两条工程约束（都是踩过坑才加的）：

1. **只在包围盒上开数组**，不要开整幅画布。2560×1440 的一次全画布浮点运算是
   4 个 44MB 的临时数组，配方里循环几次就爆内存。
2. **长线段要分块**。一条 2560px 长的斜线，包围盒就是整幅画布 —— 纯 Python 版
   在这里跑到分钟级（所以它当年改成了「逐点盖章」）；NumPy 版把线段切成小段，
   每段的包围盒只有几十像素见方，既保持**精确的胶囊几何**，又不吃内存。
"""

from __future__ import annotations

import math

import numpy as np

from .codec import to_png, write_png
from .color import RGBA, gradient_stops, parse_color, to_rgba8
from .field import dir_field, radial_field
from .geometry import regular_polygon_points, rounded_rect_points, star_points
from . import blend as _blend_mod
from . import filters as _filters

__all__ = ["Canvas"]

# 单个图元允许的最大包围盒像素数（约 1MB/数组），超过就分块
_MAX_BBOX_PIXELS = 262_144
# 胶囊分块的目标段长（px）
_CAPSULE_CHUNK = 96.0

#: 本后端支持的能力集合。**显式列举**而不是靠 `dir(self)` 推断 ——
#: 推断会把私有方法和无关属性也算进去，能力校验就失去意义了。
_CAPABILITIES = frozenset((
    "fill", "paint", "new_layer", "composite", "to_png", "save",
    "rect", "disc", "ring", "ellipse", "capsule", "arc", "polygon", "line",
    "regular_polygon", "star", "erase_disc",
    "linear_gradient", "radial_gradient",
    "blur", "adjust", "posterize", "solarize", "invert", "grayscale", "grain",
))


class Canvas:
    """直通道（straight alpha）浮点画布，值域 0.0–1.0。

    ``background`` 省略时是全透明的；给了颜色就相当于先铺一层底。
    """

    __slots__ = ("w", "h", "buf")

    def __init__(self, width: int, height: int, background=None):
        self.w, self.h = int(width), int(height)
        if self.w < 1 or self.h < 1:
            raise ValueError("宽高必须 ≥ 1")
        self.buf = np.zeros((self.h, self.w, 4), dtype=np.float32)
        if background is not None:
            r, g, b, a = parse_color(background)
            self.buf[..., 0] = r
            self.buf[..., 1] = g
            self.buf[..., 2] = b
            self.buf[..., 3] = a

    # ------------------------------------------------------------ 基本信息
    @property
    def size(self) -> tuple[int, int]:
        return (self.w, self.h)

    def __repr__(self) -> str:
        return f"Canvas({self.w}x{self.h})"

    def to_rgba8(self) -> np.ndarray:
        """→ ``(h, w, 4)`` uint8（四舍五入到最近整数，与参考实现一致）。"""
        return np.clip(np.rint(self.buf * 255.0), 0, 255).astype(np.uint8)

    def to_png(self) -> bytes:
        return to_png(self.to_rgba8())

    def save(self, path) -> str:
        return write_png(path, self.to_rgba8())

    # ------------------------------------------------------------ 合成核心
    def _blend(self, x0: int, y0: int, srgb: np.ndarray, sa: np.ndarray) -> None:
        """把「源 RGB 场 + 源 alpha 场」按 over 合成进 ``[y0, x0]`` 起始的区块。"""
        rows, cols = sa.shape
        if rows <= 0 or cols <= 0:
            return
        reg = self.buf[y0:y0 + rows, x0:x0 + cols]
        da = reg[..., 3]
        oa = sa + da * (1.0 - sa)
        nz = oa > 1e-6
        num = srgb * sa[..., None] + reg[..., :3] * (da * (1.0 - sa))[..., None]
        out = np.divide(num, oa[..., None], out=np.zeros_like(num),
                        where=nz[..., None])
        np.copyto(reg[..., :3], out, where=nz[..., None])
        np.copyto(reg[..., 3], oa, where=nz)

    def _region(self, x0f, y0f, x1f, y1f):
        """浮点包围盒 → 裁剪后的整数包围盒 + 中心坐标轴；退化时返回 None。"""
        x0 = max(0, int(math.floor(x0f)))
        y0 = max(0, int(math.floor(y0f)))
        x1 = min(self.w - 1, int(math.ceil(x1f)))
        y1 = min(self.h - 1, int(math.ceil(y1f)))
        if x1 < x0 or y1 < y0:
            return None
        xs = np.arange(x0, x1 + 1, dtype=np.float32) + 0.5
        ys = np.arange(y0, y1 + 1, dtype=np.float32) + 0.5
        return x0, y0, x1, y1, xs, ys

    @staticmethod
    def _fill_src(color: RGBA, cov: np.ndarray):
        """把统一颜色 × 覆盖率展开成 (RGB 场, alpha 场)。"""
        sa = np.ascontiguousarray(cov, dtype=np.float32) * np.float32(color[3])
        srgb = np.empty(sa.shape + (3,), dtype=np.float32)
        srgb[..., 0] = color[0]
        srgb[..., 1] = color[1]
        srgb[..., 2] = color[2]
        return srgb, sa

    # ------------------------------------------------------------ 铺底 / 上色
    def fill(self, color) -> "Canvas":
        """整幅填色（不透明路径，无临时数组）。"""
        r, g, b, a = parse_color(color)
        self.buf[..., 0] = r
        self.buf[..., 1] = g
        self.buf[..., 2] = b
        self.buf[..., 3] = a
        return self

    def paint(self, rgb, alpha=None) -> "Canvas":
        """用 RGB 场覆盖画布 —— 背景类配方的入口。

        ``rgb``：``(3,)`` / ``(4,)`` 常量色，或 ``(h, w, 3)`` / ``(h, w, 4)`` 场
        （4 通道时其 alpha 通道会被用作混合权重）。``alpha``：``None`` 表示
        跟随场自带 alpha（若为全 1 则走不透明快路径），标量或 ``(h, w)`` 场则强制覆盖。
        """
        arr = np.asarray(rgb, dtype=np.float32)
        if arr.ndim == 1:
            if arr.shape[0] == 4:
                if alpha is None:
                    alpha = float(arr[3])
                arr = arr[:3]
            arr = np.broadcast_to(arr, (self.h, self.w, 3))
        elif arr.ndim == 3 and arr.shape[2] == 4:
            if alpha is None:
                alpha = arr[..., 3]
            arr = np.ascontiguousarray(arr[..., :3])
        elif arr.ndim != 3 or arr.shape[2] != 3:
            raise ValueError(f"paint() 需要 (3,)/(4,)/(h,w,3)/(h,w,4)，收到 {arr.shape}")

        if alpha is None:
            self.buf[..., :3] = arr
            self.buf[..., 3] = 1.0
            return self

        a = np.asarray(alpha, dtype=np.float32)
        if a.ndim == 0:
            if float(a) >= 1.0:
                self.buf[..., :3] = arr
                self.buf[..., 3] = 1.0
                return self
            a = np.full((self.h, self.w), float(a), dtype=np.float32)
        elif a.shape != (self.h, self.w):
            # 允许可广播形状（如 (h,1) 的水平条带、(1,w) 的竖直渐变）
            try:
                a = np.broadcast_to(a, (self.h, self.w))
            except ValueError:
                raise ValueError(
                    f"alpha 场形状应为 {(self.h, self.w)} 或可广播到该形状，"
                    f"收到 {a.shape}") from None
        if float(a.min()) >= 1.0:                       # 全不透明 → 免混合
            self.buf[..., :3] = arr
            self.buf[..., 3] = 1.0
            return self

        band = max(1, int(_MAX_BBOX_PIXELS // max(1, self.w)))
        for y0 in range(0, self.h, band):
            y1 = min(self.h, y0 + band)
            self._blend(0, y0, np.ascontiguousarray(arr[y0:y1]),
                        np.ascontiguousarray(a[y0:y1]))
        return self

    # ------------------------------------------------------------ 图元
    def rect(self, x, y, w, h, color, *, radius=0) -> "Canvas":
        """轴对齐矩形（按像素重叠面积算覆盖率，边缘天然抗锯齿）。

        ``radius > 0`` 时走圆角多边形路径 —— 圆角的几何定义在 `geometry.py`，
        两个后端共用同一份顶点，避免"位图的圆角和矢量的圆角对不上"。
        """
        if w <= 0 or h <= 0:
            return self
        if int(radius) > 0:
            return self.polygon(rounded_rect_points(x, y, w, h, radius), color, ss=3)
        reg = self._region(x, y, x + w, y + h)
        if reg is None:
            return self
        x0, y0, _x1, _y1, xs, ys = reg
        ox = np.clip(np.minimum(xs + 0.5, x + w) - np.maximum(xs - 0.5, x), 0, 1)
        oy = np.clip(np.minimum(ys + 0.5, y + h) - np.maximum(ys - 0.5, y), 0, 1)
        cov = oy[:, None] * ox[None, :]
        srgb, sa = self._fill_src(parse_color(color), cov)
        self._blend(x0, y0, srgb, sa)
        return self

    def disc(self, cx, cy, r, color, *, feather=1.0) -> "Canvas":
        if r <= 0:
            return self
        reg = self._region(cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1)
        if reg is None:
            return self
        x0, y0, _x1, _y1, xs, ys = reg
        d = np.hypot(xs[None, :] - cx, ys[:, None] - cy)
        cov = np.clip((r + 0.5 - d) / max(0.4, feather), 0.0, 1.0)
        srgb, sa = self._fill_src(parse_color(color), cov)
        self._blend(x0, y0, srgb, sa)
        return self

    def ring(self, cx, cy, r_out, r_in, color, *, feather=1.0) -> "Canvas":
        if r_out <= 0 or r_out <= r_in:
            return self
        reg = self._region(cx - r_out - 1, cy - r_out - 1,
                           cx + r_out + 1, cy + r_out + 1)
        if reg is None:
            return self
        x0, y0, _x1, _y1, xs, ys = reg
        fe = max(0.4, feather)
        d = np.hypot(xs[None, :] - cx, ys[:, None] - cy)
        co = np.clip((r_out + 0.5 - d) / fe, 0.0, 1.0)
        ci = np.clip((r_in - 0.5 - d) / fe, 0.0, 1.0)
        cov = co * (1.0 - ci)
        srgb, sa = self._fill_src(parse_color(color), cov)
        self._blend(x0, y0, srgb, sa)
        return self

    def ellipse(self, cx, cy, rx, ry, color, *, ang=0.0) -> "Canvas":
        if rx <= 0 or ry <= 0:
            return self
        R = max(rx, ry)
        reg = self._region(cx - R - 1, cy - R - 1, cx + R + 1, cy + R + 1)
        if reg is None:
            return self
        x0, y0, _x1, _y1, xs, ys = reg
        ca, sa_ = math.cos(math.radians(-ang)), math.sin(math.radians(-ang))
        dx = xs[None, :] - cx
        dy = ys[:, None] - cy
        u = (dx * ca - dy * sa_) / rx
        v = (dx * sa_ + dy * ca) / ry
        cov = np.clip((1.0 - np.hypot(u, v)) * min(rx, ry), 0.0, 1.0)
        srgb, s_alpha = self._fill_src(parse_color(color), cov)
        self._blend(x0, y0, srgb, s_alpha)
        return self

    def capsule(self, x0, y0, x1, y1, r, color) -> "Canvas":
        """两端带半圆的线段（任意角）。长线段自动分块，避免包围盒 = 整幅画布。"""
        if r <= 0:
            return self
        x0f, y0f, x1f, y1f = x0, y0, x1, y1
        dx, dy = x1f - x0f, y1f - y0f
        L = math.hypot(dx, dy)
        n_chunks = max(1, int(math.ceil(L / _CAPSULE_CHUNK))) if L > 0 else 1
        col = parse_color(color)
        L2 = dx * dx + dy * dy
        for k in range(n_chunks):
            pad = r + 1.0
            if L > 0:
                t0 = k / n_chunks
                t1 = (k + 1) / n_chunks
                # 以整条线段为参照做分块，保证相邻块严密接续
                bx0 = min(x0f + dx * t0, x0f + dx * t1) - pad
                by0 = min(y0f + dy * t0, y0f + dy * t1) - pad
                bx1 = max(x0f + dx * t0, x0f + dx * t1) + pad
                by1 = max(y0f + dy * t0, y0f + dy * t1) + pad
            else:
                bx0, by0, bx1, by1 = x0f - pad, y0f - pad, x0f + pad, y0f + pad
            reg = self._region(bx0, by0, bx1, by1)
            if reg is None:
                continue
            rx0, ry0, _rx1, _ry1, xs, ys = reg
            if L2 <= 1e-12:
                d = np.hypot(xs[None, :] - x0f, ys[:, None] - y0f)
                cov = np.clip(r + 0.5 - d, 0.0, 1.0)
            else:
                t = np.clip(((xs[None, :] - x0f) * dx + (ys[:, None] - y0f) * dy) / L2,
                            0.0, 1.0)
                d = np.hypot(xs[None, :] - (x0f + t * dx), ys[:, None] - (y0f + t * dy))
                cov = np.clip(r + 0.5 - d, 0.0, 1.0)
                if n_chunks > 1:
                    # 块间**互斥**：按参数 t 把像素判给唯一一块。
                    # 否则重叠带会被合成两次 —— 不透明色看不出来，半透明色就是一条偏色带。
                    if k < n_chunks - 1:
                        cov = np.where((t >= t0) & (t < t1), cov, 0.0)
                    else:
                        cov = np.where(t >= t0, cov, 0.0)
            srgb, sa = self._fill_src(col, cov)
            self._blend(rx0, ry0, srgb, sa)
        return self

    def arc(self, cx, cy, r_out, r_in, a0, a1, color) -> "Canvas":
        """环段（角度用**弧度**，坐标系 y 向下：0 = 右、π/2 = 下、3π/2 = 上）。"""
        if r_out <= 0:
            return self
        reg = self._region(cx - r_out - 1, cy - r_out - 1,
                           cx + r_out + 1, cy + r_out + 1)
        if reg is None:
            return self
        x0, y0, _x1, _y1, xs, ys = reg
        dx = xs[None, :] - cx
        dy = ys[:, None] - cy
        ang = np.mod(np.arctan2(dy, dx), 2 * math.pi)
        lo, hi = a0 % (2 * math.pi), a1 % (2 * math.pi)
        ok = (ang >= lo) & (ang <= hi) if lo <= hi else (ang >= lo) | (ang <= hi)
        d = np.hypot(dx, dy)
        co = np.clip(r_out + 0.5 - d, 0.0, 1.0)
        ci = np.clip(r_in - 0.5 - d, 0.0, 1.0)
        cov = np.where(ok, co * (1.0 - ci), 0.0).astype(np.float32)
        srgb, sa = self._fill_src(parse_color(color), cov)
        self._blend(x0, y0, srgb, sa)
        return self

    def line(self, points, width, color, *, cap: bool = True) -> "Canvas":
        """折线：逐段胶囊，天然带圆头圆角。"""
        pts = list(points)
        if len(pts) == 1:
            if cap:
                self.disc(pts[0][0], pts[0][1], width / 2.0, color)
            return self
        for i in range(len(pts) - 1):
            (ax, ay), (bx, by) = pts[i], pts[i + 1]
            self.capsule(ax, ay, bx, by, width / 2.0, color)
        return self

    def polygon(self, points, color, *, ss: int = 3) -> "Canvas":
        """任意多边形填充（奇偶规则 + ``ss`` 倍超采样抗锯齿）。

        ⚠️ 实现成**逐行扫描**而不是「每个采样点 × 每条边」的朴素写法：
        后者在「顶点数百 + 面积上百万像素」时是上亿次循环 —— 参考实现当年
        （纯 Python）就是在这里跑超时的。逐行扫描是 O(行数 × 边数)，且每行向量化。
        """
        pts = np.asarray(points, dtype=np.float64)
        if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 3:
            raise ValueError("polygon() 需要至少 3 个 (x, y) 顶点")
        reg = self._region(pts[:, 0].min(), pts[:, 1].min(),
                           pts[:, 0].max(), pts[:, 1].max())
        if reg is None:
            return self
        x0, y0, x1, y1, xs, _ys = reg
        col = parse_color(color)
        px, py = pts[:, 0], pts[:, 1]
        qx, qy = np.roll(px, -1), np.roll(py, -1)
        cov = np.zeros(x1 - x0 + 1, dtype=np.float32)
        step = 1.0 / ss
        # x 方向的子采样偏移（保持与参考实现同一套覆盖率口径，便于逐像素对照）
        xoff = [(s + 0.5) * step - 0.5 for s in range(ss)]
        for row in range(y0, y1 + 1):
            cov.fill(0.0)
            for s in range(ss):
                yy = row + (s + 0.5) * step
                cross = (py > yy) != (qy > yy)
                if not cross.any():
                    continue
                xint = (qx[cross] - px[cross]) * (yy - py[cross]) / (qy[cross] - py[cross]) + px[cross]
                xint.sort()
                if len(xint) < 2:
                    continue
                # 奇偶规则：排序后 [0,1)、[2,3) … 区间为内部
                for off in xoff:
                    starts = np.searchsorted(xint, xs + off, side="right")
                    cov += ((starts & 1) == 1)
            cov /= ss * ss
            srgb, sa = self._fill_src(col, cov[None, :])
            self._blend(x0, row, srgb, sa)
        return self

    # ------------------------------------------------------------ 便捷组合
    def erase_disc(self, cx, cy, r, *, feather=1.0) -> "Canvas":
        """抠一个透明圆孔（dst-out）。

        直通道 alpha 下只需按覆盖率衰减 alpha 即可 —— 齿轮中心孔、镂空徽标都用它。
        """
        if r <= 0:
            return self
        reg = self._region(cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1)
        if reg is None:
            return self
        x0, y0, _x1, _y1, xs, ys = reg
        d = np.hypot(xs[None, :] - cx, ys[:, None] - cy)
        cut = np.clip((r + 0.5 - d) / max(0.4, feather), 0.0, 1.0)
        block = self.buf[y0:y0 + cut.shape[0], x0:x0 + cut.shape[1]]
        block[..., 3] *= (1.0 - cut)
        return self

    def hline(self, y, x0, x1, width, color) -> "Canvas":
        return self.capsule(x0, y, x1, y, width / 2.0, color)

    def vline(self, x, y0, y1, width, color) -> "Canvas":
        return self.capsule(x, y0, x, y1, width / 2.0, color)

    def regular_polygon(self, cx, cy, r, sides, color, *, ang=-90.0, ss=3) -> "Canvas":
        return self.polygon(regular_polygon_points(cx, cy, r, sides, ang=ang), color, ss=ss)

    def star(self, cx, cy, r, points, color, *, ang=-90.0, inner=0.382, ss=3) -> "Canvas":
        """正 N 角星。顶点算法在 `geometry.star_points` —— 与矢量后端共用同一份几何。"""
        return self.polygon(
            star_points(cx, cy, r, points, ang=ang, inner=inner), color, ss=ss)

    # ============================================================ 后端能力自述
    @property
    def capabilities(self) -> frozenset[str]:
        """本后端支持的能力集合（供 `backend.check_ops` 做渲染前预检）。"""
        return _CAPABILITIES

    # ============================================================ 渐变
    def linear_gradient(self, begin, end, angle=90.0, mid=None, mid_at=0.5) -> "Canvas":
        """线性渐变铺满整幅。

        这是**后端无关的能力**：位图后端把方向场算成像素，矢量后端写
        `<linearGradient>` —— 语义相同，表达不同。所以图案层调用它，两个后端都能跑。
        """
        stops = [(0.0, begin), (1.0, end)]
        if mid:
            stops.insert(1, (float(mid_at), mid))
        return self.paint(gradient_stops(stops, dir_field(self.w, self.h, angle)))

    def radial_gradient(self, inner, outer, cx=None, cy=None, radius=None) -> "Canvas":
        """径向渐变铺满整幅。参数语义见 `field.radial_field`。"""
        return self.paint(gradient_stops([(0.0, inner), (1.0, outer)],
                                         radial_field(self.w, self.h, cx, cy, radius)))

    # ============================================================ 一元算子
    def blur(self, radius=12.0, passes=3) -> "Canvas":
        """高斯模糊（盒式×3 近似，O(n)，alpha 感知）。"""
        self.buf = _filters.blur(self.buf, radius, passes=int(passes))
        return self

    def adjust(self, brightness=1.0, contrast=1.0, saturation=1.0, hue=0.0,
               gamma=1.0) -> "Canvas":
        """调色（1.0 = 原样，与 Pillow `ImageEnhance` 同语义）。"""
        self.buf = _filters.adjust(self.buf, brightness=float(brightness),
                                   contrast=float(contrast),
                                   saturation=float(saturation), hue=float(hue),
                                   gamma=float(gamma))
        return self

    def posterize(self, levels=6) -> "Canvas":
        self.buf = _filters.posterize(self.buf, int(levels))
        return self

    def solarize(self, threshold=0.5) -> "Canvas":
        self.buf = _filters.solarize(self.buf, float(threshold))
        return self

    def invert(self) -> "Canvas":
        self.buf = _filters.invert(self.buf)
        return self

    def grayscale(self, amount=1.0) -> "Canvas":
        self.buf = _filters.grayscale(self.buf, float(amount))
        return self

    def grain(self, amount=0.05, seed=0, mono=True) -> "Canvas":
        self.buf = _filters.grain(self.buf, float(amount), seed=int(seed),
                                  mono=bool(mono))
        return self

    # ============================================================ 图层与合成
    def new_layer(self) -> "Canvas":
        """新建一个同尺寸的独立帧（供 `Scene` 做"渲染到子层再合成"）。"""
        return Canvas(self.w, self.h)

    def composite(self, layer, mode="normal", opacity=1.0) -> "Canvas":
        """把另一个帧按 `mode` / `opacity` 合成进来（二元算子）。

        公式遵循 CSS Compositing / PDF 混合模型，见 `blend.py` 的模块说明。
        """
        other = layer.buf if isinstance(layer, Canvas) else layer
        self.buf = _blend_mod.blend(other, self.buf, mode, opacity)
        return self
