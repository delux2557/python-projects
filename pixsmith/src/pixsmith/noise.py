"""噪声族：程序化纹理的地基。

为什么值得单独一个模块
----------------------
一维均匀随机是**假噪点** —— 它只有"颗粒感"，没有"结构感"。云、大理石、地形、水波、
金属拉丝这类真实纹理，全部来自**在多个尺度上平滑变化的噪声**：

    Perlin / Value       平滑的连续场（"有起伏的坡"）
    Cellular (Worley)    细胞状的场（石头、裂纹、鳞片）
    fBm（分形叠加）        多倍频叠加 → 自然界的"粗糙度"
    域扭曲 (domain warp)  用噪声去偏移采样坐标 → 云、烟雾、火焰

设计要点
--------
1. **全部向量化**。参考实现的实测（NoiseTexture 项目）：纯 Python Perlin 2D 要 1.26 s，
   Cython 版 0.017 s（74×）。我们不引 C 扩展，靠 NumPy 拿到同一量级。
2. **确定性**。同一 `seed` 必然同一结果 —— 用整数哈希而不是预先生成随机表，
   因为哈希按需计算，不占内存。
3. **返回 [0, 1] 的浮点场**，不返回图。上色交给 `color.gradient_stops` ——
   同一片噪声可以当亮度、当位移、当透明度。**场是能力，上色是素材。**

⚠️ 一条踩过的坑（fBm 的实现细节）
---------------------------------
第一版把每个倍频**各自归一化**到 [0,1] 再按振幅叠加，再除以振幅和。
后果：`persistence=0.5` 时高频层权重只有 0.5^k/Σamp ≈ 1.6%，**加倍频反而让细节变少**
（实测相邻差 0.0102 → 0.0084，与直觉相反）。
正解是**先叠加原始值、最后只归一化一次**（这也是各家 fBm 的标准做法）。
现在 `fbm(octaves=6, persistence=0.75)` 的细节量是单层的约 2 倍，符合直觉。

坐标系：``(0,0)`` 在左上；`freq` 是"画布上有几个噪声周期"，与分辨率解耦。
"""

from __future__ import annotations

import numpy as np

__all__ = ["value_noise", "perlin_noise", "cellular_noise", "fbm",
           "domain_warp", "field", "KINDS"]

_MASK = 0xFFFFFFFF
# 8 个方向的单位梯度（Perlin 用）
_GRAD = np.array([[1, 0], [-1, 0], [0, 1], [0, -1],
                  [0.7071, 0.7071], [-0.7071, 0.7071],
                  [0.7071, -0.7071], [-0.7071, -0.7071]], dtype=np.float32)
_P1, _P2, _P3 = 374761393, 668265263, 1274126177
_KINDS = ("perlin", "value", "cellular", "f2f1", "cell")


# ------------------------------------------------------------------ 底层工具
def _hash(x: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    """整数格点 → 稳定伪随机 32 位整数。按需计算，不预分配随机表。

    ⚠️ 全程 int64 且每步掩码，否则 NumPy 会在 int32 乘法上溢出告警。
    """
    h = (x.astype(np.int64) * _P1 + y.astype(np.int64) * _P2
         + np.int64(seed & _MASK) * _P3) & _MASK
    h ^= h >> np.int64(13)
    h = (h * _P3) & _MASK
    h ^= h >> np.int64(16)
    return h


def _unit01(h: np.ndarray) -> np.ndarray:
    """哈希 → [0, 1) 浮点。"""
    return ((h & 0xFFFF).astype(np.float32) / 65535.0)


def _grid(w: int, h: int, freq: float):
    """把像素中心映射到以 ``freq`` 为周期的连续坐标，并切开整数/小数部分。"""
    f = float(freq)
    xs = (np.arange(w, dtype=np.float32) + 0.5) / max(1, w) * f
    ys = (np.arange(h, dtype=np.float32) + 0.5) / max(1, h) * f
    xf_full = xs[None, :]
    yf_full = ys[:, None]
    xi = np.broadcast_to(np.floor(xf_full).astype(np.int64), (h, w))
    yi = np.broadcast_to(np.floor(yf_full).astype(np.int64), (h, w))
    return xi, yi, xf_full - xi, yf_full - yi


def _fade(t: np.ndarray) -> np.ndarray:
    """Perlin 的五次缓和曲线 6t⁵-15t⁴+10t³ —— 一阶、二阶导都连续。"""
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _normalize(a: np.ndarray) -> np.ndarray:
    """线性拉到 [0, 1]。常数场返回全 0。"""
    lo = float(a.min())
    span = float(a.max()) - lo
    if span < 1e-9:
        return np.zeros_like(a, dtype=np.float32)
    return ((a - lo) / span).astype(np.float32)


# ------------------------------------------------------------------ 原始场
def _raw_value(w: int, h: int, freq: float, seed: int) -> np.ndarray:
    """值噪声的**原始**输出（未经归一化）—— fBm 要在原始域上叠加。"""
    xi, yi, xf, yf = _grid(w, h, freq)
    u, v = _fade(xf), _fade(yf)
    n00 = _unit01(_hash(xi, yi, seed))
    n10 = _unit01(_hash(xi + 1, yi, seed))
    n01 = _unit01(_hash(xi, yi + 1, seed))
    n11 = _unit01(_hash(xi + 1, yi + 1, seed))
    top = n00 + (n10 - n00) * u
    bot = n01 + (n11 - n01) * u
    return (top + (bot - top) * v).astype(np.float32)


def _raw_perlin(w: int, h: int, freq: float, seed: int) -> np.ndarray:
    """梯度噪声的**原始**输出，量级约 ±0.7（未经归一化）。"""
    xi, yi, xf, yf = _grid(w, h, freq)
    u, v = _fade(xf), _fade(yf)
    total = np.zeros((h, w), dtype=np.float32)
    for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        g = _GRAD[(_hash(xi + dx, yi + dy, seed) & 7)]
        rx, ry = xf - dx, yf - dy
        dot = g[..., 0] * rx + g[..., 1] * ry
        wx = u if dx else (1.0 - u)
        wy = v if dy else (1.0 - v)
        total += wx * wy * dot
    return total


_RAW = {"perlin": _raw_perlin, "value": _raw_value}


# ------------------------------------------------------------------ 公开 API
def value_noise(w: int, h: int, *, freq: float = 4.0, seed: int = 0,
                octaves: int = 1) -> np.ndarray:
    """值噪声：格点上是随机值，格内平滑插值。比 Perlin 软、比均匀随机有结构。"""
    if int(octaves) > 1:
        return fbm(w, h, octaves=octaves, freq=freq, seed=seed, kind="value")
    return _normalize(_raw_value(w, h, freq, seed))


def perlin_noise(w: int, h: int, *, freq: float = 4.0, seed: int = 0,
                 octaves: int = 1) -> np.ndarray:
    """梯度噪声（Perlin 1983）：格点上放梯度向量，四点做点积后插值。"""
    if int(octaves) > 1:
        return fbm(w, h, octaves=octaves, freq=freq, seed=seed, kind="perlin")
    return _normalize(_raw_perlin(w, h, freq, seed))


def fbm(w: int, h: int, *, octaves: int = 6, freq: float = 2.0,
        lacunarity: float = 2.0, persistence: float = 0.5, seed: int = 0,
        kind: str = "perlin") -> np.ndarray:
    """分形叠加（fractal Brownian motion）：多倍频的噪声按振幅递减叠加。

    | 参数 | 作用 | 典型值 |
    |---|---|---|
    | `octaves` | 叠几层 | 4–8 |
    | `lacunarity` | 每层频率倍数 | 2.0 |
    | `persistence` | 每层振幅倍数（越**大**越粗糙） | 0.5 |

    **这是"自然感"的来源** —— 单层噪声只能得到"平缓的坡"，
    真实纹理的关键在于**同时存在大结构与小细节**。

    ⚠️ 实现在**原始域**叠加、最后只归一化一次（见模块 docstring 的踩坑记录）。
    """
    if kind not in ("perlin", "value"):
        raise ValueError(f"fbm 的 kind 只支持 perlin / value，收到 {kind!r}")
    raw = _RAW[kind]
    total = np.zeros((h, w), dtype=np.float32)
    amp, f = 1.0, float(freq)
    for i in range(max(1, int(octaves))):
        total += raw(w, h, f, seed + i * 101) * np.float32(amp)
        amp *= float(persistence)
        f *= float(lacunarity)
    return _normalize(total)


def cellular_noise(w: int, h: int, *, freq: float = 8.0, seed: int = 0,
                   jitter: float = 1.0, mode: str = "f1") -> np.ndarray:
    """细胞噪声（Worley / Voronoi）：每个格子里放一个特征点，取到最近点的距离。

    ``mode``：
      ``f1``      最近距离 —— 细胞的"内部"，适合石材质感
      ``f2f1``    次近 − 最近 —— **细胞边界**（干净的 Voronoi 边），适合裂纹
      ``cell``    最近格子的随机值 —— 马赛克 / 彩绘玻璃
    """
    xi, yi, xf, yf = _grid(w, h, freq)
    d1 = np.full((h, w), 1e9, dtype=np.float32)
    d2 = np.full((h, w), 1e9, dtype=np.float32)
    best = np.zeros((h, w), dtype=np.int64)
    jit = max(0.0, float(jitter))
    for oy in (-1, 0, 1):
        for ox in (-1, 0, 1):
            hx = _unit01(_hash(xi + ox, yi + oy, seed))
            hy = _unit01(_hash(xi + ox, yi + oy, seed + 7919))
            px = ox + (0.5 + (hx - 0.5) * jit)
            py = oy + (0.5 + (hy - 0.5) * jit)
            dd = np.hypot(px - xf, py - yf)
            closer = dd < d1
            d2 = np.where(closer, d1, np.minimum(d2, dd))
            best = np.where(closer, _hash(xi + ox, yi + oy, seed + 104729), best)
            d1 = np.where(closer, dd, d1)
    if mode == "f2f1":
        return _normalize(d2 - d1)
    if mode == "cell":
        return _unit01(best)
    if mode != "f1":
        raise ValueError(f"未知 cellular mode {mode!r}（可用：f1 / f2f1 / cell）")
    return _normalize(d1)


def domain_warp(w: int, h: int, *, strength: float = 0.35, freq: float = 3.0,
                octaves: int = 4, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """域扭曲的**位移场**：返回 ``(dx, dy)``，单位是像素。

    用法：`(dx, dy) = domain_warp(...)` → `filters.warp_field(src, dx, dy)`。
    把一个规整的噪声场沿位移场重采样，就能得到云、烟、火焰那种被搅动的形态。
    少了它，大理石只是条纹；有了它，才是大理石。

    两个通道用不同的子种子，否则位移场会退化成"沿对角线拉扯"。
    """
    s = max(0.0, float(strength)) * min(w, h)
    dx = (fbm(w, h, octaves=octaves, freq=freq, seed=seed) - 0.5) * (2.0 * s)
    dy = (fbm(w, h, octaves=octaves, freq=freq, seed=seed + 5171) - 0.5) * (2.0 * s)
    return dx.astype(np.float32), dy.astype(np.float32)


def field(kind: str, w: int, h: int, **params) -> np.ndarray:
    """统一入口：``field("perlin", 512, 512, freq=4, octaves=6)``。

    让上层（图案层 / DSL）拿一个字符串就能选噪声类型，不用 import 五个函数。
    """
    k = str(kind)
    if k in ("perlin", "value"):
        if int(params.get("octaves", 1)) > 1:
            return fbm(w, h, kind=k, **params)
        return _normalize(_RAW[k](w, h, float(params.get("freq", 4.0)),
                                  int(params.get("seed", 0))))
    if k == "fbm":
        return fbm(w, h, **params)
    if k in ("cellular", "f2f1", "cell"):
        return cellular_noise(w, h, freq=params.get("freq", 8.0),
                             seed=params.get("seed", 0),
                             jitter=params.get("jitter", 1.0),
                             mode={"cellular": "f1"}.get(k, k))
    raise ValueError(f"未知 noise kind {kind!r}（可用：{_KINDS} + fbm）")


KINDS = _KINDS
