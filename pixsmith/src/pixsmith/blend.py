"""二元算子：把两块像素合起来（合成 / 混合）。

一元算子（`filters.py`）是「一块像素 → 一块像素」；这里是**两块 → 一块**。
这个区分不是学究：它对应两个完全不同的语义层，也就是 PS 里
「滤镜/调整」（一元）与「图层混合模式」（二元）的分界。

实现遵循 **CSS Compositing and Blending Level 1 / PDF 混合模型**，而不是自己发明公式：

    B(Cb, Cs)            混合函数（multiply / screen / overlay …）
    Cs' = (1 - αb)·Cs + αb·B(Cb, Cs)      混合后的"源色"
    αo  = αs + αb·(1 - αs)                标准 source-over
    Co  = (Cs'·αs + Cb·αb·(1 - αs)) / αo

照抄标准的收益：**结果与浏览器 `mix-blend-mode` 一致**，而且 SVG 后端能直接用
`mix-blend-mode` 表达同一件事 —— 双后端才可能真正对齐。
"""

from __future__ import annotations

import numpy as np

__all__ = ["MODES", "blend", "blend_names", "is_mode"]

_EPS = 1e-6


def _hard_light(cb, cs):
    return np.where(cs <= 0.5, 2.0 * cb * cs,
                    1.0 - 2.0 * (1.0 - cb) * (1.0 - cs))


def _soft_light(cb, cs):
    d = np.where(cb <= 0.25, ((16.0 * cb - 12.0) * cb + 4.0) * cb, np.sqrt(np.maximum(cb, 0.0)))
    return np.where(cs <= 0.5,
                    cb - (1.0 - 2.0 * cs) * cb * (1.0 - cb),
                    cb + (2.0 * cs - 1.0) * (d - cb))


# 混合函数表：B(Cb, Cs)。键名与 CSS `mix-blend-mode` 对齐。
_FUNCS = {
    "normal": lambda cb, cs: cs,
    "multiply": lambda cb, cs: cb * cs,
    "screen": lambda cb, cs: cb + cs - cb * cs,
    "overlay": lambda cb, cs: _hard_light(cs, cb),      # overlay(Cb,Cs) = hard_light(Cs,Cb)
    "darken": np.minimum,
    "lighten": np.maximum,
    "difference": lambda cb, cs: np.abs(cb - cs),
    "exclusion": lambda cb, cs: cb + cs - 2.0 * cb * cs,
    "hard-light": _hard_light,
    "soft-light": _soft_light,
    "color-dodge": lambda cb, cs: np.where(cs >= 1.0 - _EPS, 1.0,
                                           np.minimum(1.0, cb / np.maximum(1.0 - cs, _EPS))),
    "color-burn": lambda cb, cs: np.where(cs <= _EPS, 0.0,
                                          np.maximum(0.0, 1.0 - (1.0 - cb) / np.maximum(cs, _EPS))),
    "linear-dodge": lambda cb, cs: np.minimum(1.0, cb + cs),        # 又称 add
    "linear-burn": lambda cb, cs: np.maximum(0.0, cb + cs - 1.0),   # 又称 subtract
}

# 别名：让习惯了 Pillow `ImageChops` 的人也能直接写
_ALIASES = {
    "over": "normal", "source-over": "normal", "blend": "normal",
    "add": "linear-dodge", "subtract": "linear-burn",
    "darker": "darken", "lighter": "lighten",
    "soft_light": "soft-light", "hard_light": "hard-light",
    "color_dodge": "color-dodge", "color_burn": "color-burn",
    "linear_dodge": "linear-dodge", "linear_burn": "linear-burn",
}

MODES = ("normal",) + tuple(sorted(k for k in _FUNCS if k != "normal"))


def blend_names() -> list[str]:
    """全部可用的混合模式（规范名 + 别名），供 CLI 与能力清单展示。"""
    return sorted(set(_FUNCS) | set(_ALIASES))


def is_mode(name: str) -> bool:
    return str(name) in _FUNCS or str(name) in _ALIASES


def _resolve(mode: str) -> str:
    m = str(mode)
    m = _ALIASES.get(m, m)
    if m not in _FUNCS:
        raise ValueError(f"未知混合模式 {mode!r}（可用：{blend_names()}）")
    return m


def blend(src: np.ndarray, dst: np.ndarray, mode: str = "normal",
          opacity: float = 1.0) -> np.ndarray:
    """把 ``src`` 按 ``mode`` 与 ``opacity`` 混合到 ``dst`` 上，返回新数组（不改入参）。

    - ``src`` / ``dst`` 都是 ``(h, w, 4)`` 的 0–1 浮点直通道 RGBA，形状必须一致
    - ``opacity`` 只缩放**源**的 alpha（图层不透明度），符合 PS/AE 的直觉
    """
    if src.shape != dst.shape:
        raise ValueError(f"两块内容形状必须一致：{src.shape} vs {dst.shape}")
    if src.ndim != 3 or src.shape[2] != 4:
        raise ValueError(f"需要 (h, w, 4) 的 RGBA，收到 {src.shape}")
    fn = _FUNCS[_resolve(mode)]
    k = float(np.clip(opacity, 0.0, 1.0))
    if k <= 0.0:
        return dst.astype(np.float32, copy=True)

    cs = np.clip(src[..., :3], 0.0, 1.0)
    cb = np.clip(dst[..., :3], 0.0, 1.0)
    sa = np.clip(src[..., 3:4], 0.0, 1.0) * np.float32(k)
    da = np.clip(dst[..., 3:4], 0.0, 1.0)

    # ① 混合函数作用于"底色 × 源色"（用未缩放 alpha 的官方口径计算混合色）
    mixed = fn(cb, cs)
    cs2 = (1.0 - da) * cs + da * mixed
    # ② 标准 source-over 合成
    oa = sa + da * (1.0 - sa)
    out = np.empty_like(dst, dtype=np.float32)
    num = cs2 * sa + cb * da * (1.0 - sa)
    nz = oa > _EPS
    np.divide(num, oa, out=out[..., :3], where=nz)
    out[..., :3] = np.where(nz, out[..., :3], 0.0)
    np.clip(out[..., :3], 0.0, 1.0, out=out[..., :3])
    out[..., 3] = oa[..., 0]
    return out
