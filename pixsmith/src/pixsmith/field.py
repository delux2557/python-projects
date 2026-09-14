"""参数场：把「空间位置」变成 0→1 的数，供渐变与图案上色。

为什么单独一层（而不是塞在 patterns/ 里）
----------------------------------------
`Canvas.linear_gradient()` 需要方向场，`patterns/` 的条纹/棋盘也需要方向场。
如果这个工具住在 `patterns/`，能力层（canvas）就得反过来 import 素材层 —— **依赖方向错了**。
所以它落在这里：一个不依赖任何东西的纯函数模块。

术语上这叫 **parameter field**（参数场）：先把空间映射成一个标量场，
再把标量场喂给色标表上色。这样"空间形状"与"颜色"解耦 ——
同一个方向场，可以用在渐变上，也可以用在蒙版、透明度、位移上。
"""

from __future__ import annotations

import math

import numpy as np

__all__ = ["xaxis", "yaxis", "dir_field", "radial_field"]


def xaxis(w: int) -> np.ndarray:
    """像素中心 x 坐标（列向量语义：``(w,)``）。"""
    return np.arange(w, dtype=np.float32) + 0.5


def yaxis(h: int) -> np.ndarray:
    """像素中心 y 坐标（``(h,)``）。"""
    return np.arange(h, dtype=np.float32) + 0.5


def dir_field(w: int, h: int, angle: float) -> np.ndarray:
    """方向渐变参数场：返回 ``(h, w)`` 的 0→1。

    ``angle`` 按屏幕直觉：0° = 从左到右、90° = 从上到下、180° = 从右到左。
    投影后按实际跨度归一化，所以任意角度都能用满整个 [0, 1]。
    """
    a = math.radians(float(angle))
    dx, dy = math.cos(a), math.sin(a)
    proj = xaxis(w)[None, :] * dx + yaxis(h)[:, None] * dy
    lo = float(proj.min())
    span = float(proj.max()) - lo
    return ((proj - lo) / (span if span > 1e-6 else 1.0)).astype(np.float32)


def radial_field(w: int, h: int, cx: float | None = None, cy: float | None = None,
                 radius: float | None = None) -> np.ndarray:
    """径向参数场：中心 0 → 边缘 1（``radius`` 省略时取到最远角的距离）。"""
    cx = w / 2.0 if cx is None else float(cx)
    cy = h / 2.0 if cy is None else float(cy)
    dx = xaxis(w)[None, :] - cx
    dy = yaxis(h)[:, None] - cy
    d = np.sqrt(dx * dx + dy * dy)
    if radius:
        r = float(radius)
    else:
        r = float(max(np.hypot(cx, cy), np.hypot(w - cx, cy),
                      np.hypot(cx, h - cy), np.hypot(w - cx, h - cy)))
    return np.clip(d / max(r, 1e-6), 0.0, 1.0).astype(np.float32)
