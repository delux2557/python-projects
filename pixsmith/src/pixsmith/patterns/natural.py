"""自然材质类图案：噪声族的落地。

这一类是 `noise.py` 的**价值证明** —— 在它之前，库里只有"均匀颗粒噪点"，
那是**假噪点**：只有颗粒感、没有结构感。云、大理石、裂纹、拉丝这些真实材质，
全部来自"多尺度平滑噪声 + 域扭曲 + 上色"。

它们**只支持位图后端**（逐像素场在矢量域没有对应物），所以都声明了 `requires=("paint",)`。
这不是妥协，是诚实：与其在矢量后端画出一个似是而非的东西，不如让能力校验提前拦住。

三种把场变成图的手法（后面还会反复用到）
----------------------------------------
1. **直接当灰度**：`paint(gradient_stops([(0,暗),(1,亮)], field))` —— 大理石、地形
2. **当透明度**：`paint(rgb, alpha=field)` —— 云、雾
3. **当位移**：`warp_field(src, *domain_warp(...))` —— 让规整的纹理"被搅动"
"""

from __future__ import annotations

import math

import numpy as np

from ..color import gradient_stops, parse_color
from ..filters import warp_field
from ..noise import cellular_noise, domain_warp, fbm
from . import Param, pattern

__all__ = []


def _warped(w: int, h: int, *, freq: float, octaves: int, strength: float,
            seed: int) -> np.ndarray:
    """fBm + 域扭曲 —— 四种材质共用的前处理。"""
    base = fbm(w, h, octaves=octaves, freq=freq, seed=seed)
    if strength <= 0:
        return base
    dx, dy = domain_warp(w, h, strength=strength, freq=max(1.0, freq * 0.7),
                         octaves=max(2, octaves - 1), seed=seed + 3)
    return warp_field(base, dx, dy)


@pattern("marble", "大理石：域扭曲的 fBm 条纹", [
    Param("stone", "color", "#F2EFE6", "石底色"),
    Param("vein", "color", "#8A7B66", "纹路色"),
    Param("freq", "float", 3.0, "基础频率（越大纹路越密）"),
    Param("octaves", "int", 6, "分形层数"),
    Param("bands", "float", 4.0, "条纹密度"),
    Param("warp", "float", 0.10, "域扭曲强度（0 = 直条纹）"),
    Param("detail", "float", 0.18, "细节噪点占比 0–1"),
    Param("seed", "int", 11, "随机种子"),
], category="natural", requires=("paint",))
def marble(c, *, stone, vein, freq, octaves, bands, warp, detail, seed):
    w, h = c.w, c.h
    base = _warped(w, h, freq=freq, octaves=octaves, strength=warp, seed=seed)
    grain = fbm(w, h, octaves=3, freq=freq * 6.0, seed=seed + 91)
    # 条纹 = 正弦相位 + 噪声扰动 —— 大理石的"脉络"就是这么来的
    phase = base * float(bands) * 2.0 * math.pi
    t = 0.5 + 0.5 * np.sin(phase)
    t = np.clip(t * (1.0 - float(detail)) + grain * float(detail), 0.0, 1.0)
    c.paint(gradient_stops([(0.0, stone), (1.0, vein)], t.astype(np.float32)))
    return c


@pattern("clouds", "云层：fBm 当作透明度（透明底，可直接叠在任意背景上）", [
    Param("color", "color", "#FFFFFF", "云色"),
    Param("freq", "float", 2.5, "云的尺度（越小团越大）"),
    Param("octaves", "int", 6, "分形层数（越大边缘越碎）"),
    Param("coverage", "float", 0.45, "云量 0–1"),
    Param("softness", "float", 0.35, "边缘柔和度 0–1（越大越稀薄）"),
    Param("warp", "float", 0.12, "域扭曲强度"),
    Param("seed", "int", 5, "随机种子"),
], category="natural", requires=("paint",))
def clouds(c, *, color, freq, octaves, coverage, softness, warp, seed):
    w, h = c.w, c.h
    f = _warped(w, h, freq=freq, octaves=octaves, strength=warp, seed=seed)
    thr = 1.0 - float(np.clip(coverage, 0.0, 1.0))
    soft = max(0.02, float(np.clip(softness, 0.01, 1.0)))
    a = np.clip((f - thr) / soft, 0.0, 1.0) ** 1.3
    rgb = np.broadcast_to(np.asarray(parse_color(color)[:3], np.float32),
                          (h, w, 3))
    c.paint(rgb, a.astype(np.float32) * float(parse_color(color)[3]))
    return c


@pattern("cracks", "裂纹 / 龟裂：细胞噪声的边界场", [
    Param("base", "color", "#2A2622", "基底色"),
    Param("crack", "color", "#E8D9B8", "裂纹色"),
    Param("freq", "float", 6.0, "细胞密度"),
    Param("width", "float", 0.22, "裂纹粗细 0–1（越大越粗）"),
    Param("glow", "float", 0.0, "裂纹外发光强度 0–1"),
    Param("jitter", "float", 1.0, "细胞不规则度 0–1（0 = 规整网格）"),
    Param("seed", "int", 9, "随机种子"),
], category="natural", requires=("paint",))
def cracks(c, *, base, crack, freq, width, glow, jitter, seed):
    w, h = c.w, c.h
    edge = cellular_noise(w, h, freq=freq, seed=seed, jitter=jitter, mode="f2f1")
    wd = max(0.02, float(np.clip(width, 0.01, 1.0)))
    # f2f1 在边界处为 0 → 取反并按宽度归一，得到"边界处的细线"
    line = np.clip(1.0 - edge / wd, 0.0, 1.0)
    c.fill(base)
    if float(glow) > 0:
        halo = np.clip(1.0 - edge / min(1.0, wd * 4.0), 0.0, 1.0)
        cc = parse_color(crack)
        c.paint(np.broadcast_to(np.asarray(cc[:3], np.float32), (h, w, 3)),
                (halo * float(glow) * 0.5).astype(np.float32))
    c.paint(np.broadcast_to(np.asarray(parse_color(crack)[:3], np.float32),
                            (h, w, 3)), line.astype(np.float32))
    return c


@pattern("brushed", "拉丝金属：沿一个方向拉伸的噪声", [
    Param("base", "color", "#9AA3AC", "金属底色"),
    Param("highlight", "color", "#E6EDF3", "高光色"),
    Param("angle", "float", 0.0, "拉丝方向（0 = 水平）"),
    Param("freq", "float", 220.0, "丝纹密度"),
    Param("jitter", "float", 0.35, "纵向扰动 0–1（0 = 完全平行的丝）"),
    Param("contrast", "float", 0.55, "丝纹对比度 0–1"),
    Param("seed", "int", 3, "随机种子"),
], category="natural", requires=("paint",))
def brushed(c, *, base, highlight, angle, freq, jitter, contrast, seed):
    w, h = c.w, c.h
    # 关键手法：先生成一条**一维**噪声剖面，再按"投影到垂直方向"的坐标去查表。
    # 这样无论角度是多少，丝纹都是严格平行的 —— 而且只算一维噪声，比二维快得多。
    span = int(math.hypot(w, h)) + 4
    prof = fbm(span, 1, octaves=1, freq=max(2.0, float(freq)), seed=seed)[0]
    a = math.radians(float(angle))
    ca, sa = math.cos(a), math.sin(a)
    xs = (np.arange(w, dtype=np.float32) + 0.5)[None, :]
    ys = (np.arange(h, dtype=np.float32) + 0.5)[:, None]
    perp = -xs * np.float32(sa) + ys * np.float32(ca)
    if float(jitter) > 0:
        wob = fbm(w, h, octaves=2, freq=3.0, seed=seed + 17) - 0.5
        perp = perp + wob * np.float32(float(jitter) * 6.0)
    idx = np.mod(np.round(perp).astype(np.int64), span)
    field = prof[idx]                      # 一维剖面 → 二维场，这就是"拉丝"
    k = float(np.clip(contrast, 0.0, 1.0))
    t = np.clip(0.5 + (field - 0.5) * (0.4 + 2.2 * k), 0.0, 1.0)
    c.paint(gradient_stops([(0.0, base), (1.0, highlight)], t.astype(np.float32)))
    return c
