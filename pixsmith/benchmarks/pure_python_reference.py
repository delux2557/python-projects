"""纯 Python 参考实现：**语义基准 + 性能对照**。

为什么项目里要自带一份"慢的"实现
--------------------------------
1. **语义基准** —— `Canvas` 是把逐像素公式向量化重写的结果，重写就有改错语义的风险，
   而单元测试只覆盖得到你想到的情况。**逐像素对照是唯一能自动证明"公式没变"的手段**
   （见 `tests/test_parity_with_reference.py`）。
2. **性能对照** —— 让"为什么要上 NumPy"有一个可复现的数字，而不是一句口头结论。
3. **可读性** —— 逐像素写法把公式摊开，本身就是 `Canvas` 最好的注释。

这份实现刻意保持朴素：不优化、不取巧，只为把语义写清楚。

⚠️ 它**慢**：图元代价是 O(包围盒面积)，长斜线会跑到分钟级。别在正式代码里用它。

--------------------------------------------------------------------------
已知偏差（参考实现与主实现**故意不一致**的一处）
--------------------------------------------------------------------------
朴素写法的 `ring()`：

    co = (r_out + 0.5 - d) / feather      # 没有归一化
    cov = co * (1 - min(1, max(0, ci)))   # 截断发生在更外层的 over() 里

``feather=1.0`` 时 ``co`` 最大能到 ``r_out + 0.5``（几十量级），乘完再被截到 1，
结果是**内边缘羽化失效、退化成硬边**（实测与修正版最大差 156/255）。

``ring_normalized()`` 是修正版（先把 ``co`` 夹到 [0,1] 再相乘），也就是 `Canvas.ring`
采用的行为。两者都保留，是为了让这处偏差**可被复现、可被断言**，
而不是变成一句没人验得了的口头传说。
"""

from __future__ import annotations

import math


def hex_rgba(h: str, a: int = 255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


class PixelCanvas:
    """逐像素的极小光栅器：坐标系 **y 向下**，颜色是 0–255 的 (r, g, b, a)。"""

    __slots__ = ("w", "h", "b")

    def __init__(self, w: int, h: int, bg=(0, 0, 0, 0)):
        self.w, self.h = w, h
        self.b = bytearray(bytes(bg) * (w * h))

    def get(self, x, y):
        i = (y * self.w + x) * 4
        b = self.b
        return (b[i], b[i + 1], b[i + 2], b[i + 3])

    def over(self, x, y, color, cov=1.0):
        if cov <= 0 or x < 0 or y < 0 or x >= self.w or y >= self.h:
            return
        sa = color[3] / 255.0 * min(1.0, cov)
        if sa <= 0:
            return
        d = self.get(x, y)
        da = d[3] / 255.0
        oa = sa + da * (1 - sa)
        if oa <= 0:
            return
        i = (y * self.w + x) * 4
        self.b[i] = int(round((color[0] * sa + d[0] * da * (1 - sa)) / oa))
        self.b[i + 1] = int(round((color[1] * sa + d[1] * da * (1 - sa)) / oa))
        self.b[i + 2] = int(round((color[2] * sa + d[2] * da * (1 - sa)) / oa))
        self.b[i + 3] = int(round(oa * 255))

    def _bbox(self, x0, y0, x1, y1):
        return (max(0, int(math.floor(x0))), max(0, int(math.floor(y0))),
                min(self.w - 1, int(math.ceil(x1))),
                min(self.h - 1, int(math.ceil(y1))))

    def disc(self, cx, cy, r, color, *, feather=1.0):
        X0, Y0, X1, Y1 = self._bbox(cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1)
        for y in range(Y0, Y1 + 1):
            for x in range(X0, X1 + 1):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                cov = (r + 0.5 - d) / max(0.4, feather)
                if cov > 0:
                    self.over(x, y, color, cov)

    def ring(self, cx, cy, r_out, r_in, color, *, feather=1.0):
        X0, Y0, X1, Y1 = self._bbox(cx - r_out - 1, cy - r_out - 1,
                                    cx + r_out + 1, cy + r_out + 1)
        for y in range(Y0, Y1 + 1):
            for x in range(X0, X1 + 1):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                co = (r_out + 0.5 - d) / max(0.4, feather)
                if co <= 0:
                    continue
                ci = (r_in - 0.5 - d) / max(0.4, feather)
                self.over(x, y, color, co * (1.0 - min(1.0, max(0.0, ci))))

    def ring_normalized(self, cx, cy, r_out, r_in, color, *, feather=1.0):
        """修正版圆环：先把外圈覆盖率归一化再乘 ``(1 - ci)``。

        ``pixsmith.Canvas.ring`` 用的就是这一版 —— 内边缘会有一圈**真正的羽化**，
        而不是被 ``over()`` 截断出来的硬边。差异见模块 docstring。
        """
        X0, Y0, X1, Y1 = self._bbox(cx - r_out - 1, cy - r_out - 1,
                                    cx + r_out + 1, cy + r_out + 1)
        fe = max(0.4, feather)
        for y in range(Y0, Y1 + 1):
            for x in range(X0, X1 + 1):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                co = min(1.0, max(0.0, (r_out + 0.5 - d) / fe))
                ci = min(1.0, max(0.0, (r_in - 0.5 - d) / fe))
                cov = co * (1.0 - ci)
                if cov > 0:
                    self.over(x, y, color, cov)

    def ellipse(self, cx, cy, rx, ry, color, *, ang=0.0):
        ca, sa = math.cos(math.radians(-ang)), math.sin(math.radians(-ang))
        R = max(rx, ry)
        X0, Y0, X1, Y1 = self._bbox(cx - R - 1, cy - R - 1, cx + R + 1, cy + R + 1)
        for y in range(Y0, Y1 + 1):
            for x in range(X0, X1 + 1):
                dx, dy = x + 0.5 - cx, y + 0.5 - cy
                u = (dx * ca - dy * sa) / rx
                v = (dx * sa + dy * ca) / ry
                cov = 1.0 - math.hypot(u, v)
                if cov > 0:
                    self.over(x, y, color, min(1.0, cov * min(rx, ry)))

    def rect(self, x, y, w, h, color):
        X0, Y0, X1, Y1 = self._bbox(x, y, x + w, y + h)
        for py in range(Y0, Y1 + 1):
            oy = min(py + 1, y + h) - max(py, y)
            if oy <= 0:
                continue
            for px in range(X0, X1 + 1):
                ox = min(px + 1, x + w) - max(px, x)
                if ox > 0:
                    self.over(px, py, color, min(1.0, ox * oy))

    def capsule(self, x0, y0, x1, y1, r, color):
        X0, Y0, X1, Y1 = self._bbox(min(x0, x1) - r - 1, min(y0, y1) - r - 1,
                                    max(x0, x1) + r + 1, max(y0, y1) + r + 1)
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy or 1e-9
        for y in range(Y0, Y1 + 1):
            for x in range(X0, X1 + 1):
                t = ((x + 0.5 - x0) * dx + (y + 0.5 - y0) * dy) / L2
                t = 0.0 if t < 0 else 1.0 if t > 1 else t
                d = math.hypot(x + 0.5 - (x0 + t * dx), y + 0.5 - (y0 + t * dy))
                cov = r + 0.5 - d
                if cov > 0:
                    self.over(x, y, color, min(1.0, cov))

    def arc(self, cx, cy, r_out, r_in, a0, a1, color):
        X0, Y0, X1, Y1 = self._bbox(cx - r_out - 1, cy - r_out - 1,
                                    cx + r_out + 1, cy + r_out + 1)
        for y in range(Y0, Y1 + 1):
            for x in range(X0, X1 + 1):
                dx, dy = x + 0.5 - cx, y + 0.5 - cy
                ang = math.atan2(dy, dx) % (2 * math.pi)
                lo, hi = a0 % (2 * math.pi), a1 % (2 * math.pi)
                ok = (lo <= ang <= hi) if lo <= hi else (ang >= lo or ang <= hi)
                if not ok:
                    continue
                d = math.hypot(dx, dy)
                co = r_out + 0.5 - d
                if co <= 0:
                    continue
                ci = r_in - 0.5 - d
                self.over(x, y, color, min(1.0, co) * (1.0 - min(1.0, max(0.0, ci))))

    def polygon(self, pts, color, *, ss=3):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        X0, Y0, X1, Y1 = self._bbox(min(xs), min(ys), max(xs), max(ys))
        n = len(pts)
        step = 1.0 / ss
        for y in range(Y0, Y1 + 1):
            for x in range(X0, X1 + 1):
                hit = 0
                for sy in range(ss):
                    py = y + (sy + 0.5) * step
                    for sx in range(ss):
                        px = x + (sx + 0.5) * step
                        inside = False
                        j = n - 1
                        for i in range(n):
                            xi, yi = pts[i]
                            xj, yj = pts[j]
                            if (yi > py) != (yj > py):
                                if px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                                    inside = not inside
                            j = i
                        if inside:
                            hit += 1
                if hit:
                    self.over(x, y, color, hit / float(ss * ss))

    def to_rgba(self):
        """→ ``(h, w, 4)`` 的嵌套 tuple，便于与 NumPy 版逐像素比较。"""
        return [[self.get(x, y) for x in range(self.w)] for y in range(self.h)]
