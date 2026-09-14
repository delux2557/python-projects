"""图案层共用的小工具（色标解析、随机源、尺寸解析）。

坐标场（`dir_field` / `radial_field`）已上移到 `pixsmith/field.py` ——
因为能力层（`canvas.linear_gradient`）也要用它，放在这里会造成反向依赖。
本模块把它们**重新导出**，图案层照旧 `from ._util import dir_field` 即可。
"""

from __future__ import annotations

import numpy as np

from ..field import dir_field, radial_field, xaxis, yaxis

__all__ = ["xaxis", "yaxis", "dir_field", "radial_field", "rng", "as_stops",
           "pct", "fit_size"]


def rng(seed: int | None):
    """确定性随机源 —— 同 seed 必然同输出，这是「可复现」的落点。"""
    return np.random.default_rng(seed)


def as_stops(pairs) -> list[tuple[float, object]]:
    """把 ``[[0, "#000"], [1, "#fff"]]`` / ``[(0, ...), ...]`` 归一成色标列表。"""
    out = []
    for item in pairs:
        t, c = item
        out.append((float(t), c))
    if len(out) < 2:
        raise ValueError("色标至少两个")
    return sorted(out, key=lambda p: p[0])


def pct(v, total: float) -> float:
    """``"40%"`` → ``0.4 * total``；数字原样返回。"""
    if isinstance(v, str) and v.strip().endswith("%"):
        return float(v.strip()[:-1]) / 100.0 * total
    return float(v)


def fit_size(size) -> tuple[int, int]:
    """``[1920, 1080]`` / ``"1920x1080"`` / ``(1920, 1080)`` → ``(1920, 1080)``。"""
    if isinstance(size, str):
        parts = size.lower().replace("*", "x").split("x")
        if len(parts) != 2:
            raise ValueError(f"尺寸写法不合法：{size!r}（用 WxH，如 1920x1080）")
        return int(parts[0]), int(parts[1])
    w, h = size
    return int(w), int(h)

