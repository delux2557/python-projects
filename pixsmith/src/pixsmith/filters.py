"""一元算子：对**整幅已绘制内容**做逐像素变换。

术语对齐 Pillow（那是 30 年验证过的分类法，用户与 AI 的既有知识可以直接迁移）：

    Pillow.ImageFilter    →  本模块的 blur / kernel 一族（卷积核类）
    Pillow.ImageEnhance   →  本模块的 adjust（Brightness/Contrast/Color/Sharpness 的等价物）
    Pillow.ImageOps       →  本模块的 posterize / solarize / grayscale / invert
    Pillow.ImageChops     →  二元算子，在 `blend.py`

两条关键工程约束
----------------
1. **模糊必须预乘 alpha**（premultiplied alpha）。
   直接对直通道 RGBA 做卷积，透明像素的 RGB（通常是 0）会被平均进来，
   边缘出现一圈**暗边**。正确做法：`RGB *= A` → 卷积 → 除以 A 还原。
   我们用 `_premultiply/_unpremultiply` 显式处理，并留了回归测试。
2. **模糊用盒式×3 近似高斯**，靠**前缀和**（`cumsum`）实现，与半径无关的 O(n)。
   不要写成卷积——那会退化成 O(n·r)，大半径直接卡死。
"""

from __future__ import annotations

import numpy as np

__all__ = ["blur", "box_blur", "adjust", "posterize", "solarize", "invert",
           "grayscale", "grain", "warp_field", "sample_bilinear", "resize",
           "affine_resample", "hue_saturation_matrix"]

# Rec.709 亮度权重（与 CSS/SVG 的 saturate 一致）
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


# ------------------------------------------------------------------ 基础工具
def _premultiply(rgba: np.ndarray) -> np.ndarray:
    out = rgba.astype(np.float32, copy=True)
    out[..., :3] *= out[..., 3:4]
    return out


def _unpremultiply(pm: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    out = pm.astype(np.float32, copy=True)
    np.divide(out[..., :3], alpha, out=out[..., :3],
              where=alpha > 1e-4)
    # 夹紧：前缀和求平均会带出 1e-7 量级的浮点溢出，不夹会让下游断言莫名其妙地失败
    np.clip(out[..., :3], 0.0, 1.0, out=out[..., :3])
    np.clip(alpha, 0.0, 1.0, out=out[..., 3:4])
    return out


def _box_width_for_sigma(sigma: float, passes: int) -> int:
    """n 次盒式模糊的等效 sigma：``sigma² = n(w²-1)/12`` → 反解 w（并强制为奇数）。"""
    w = int(round(np.sqrt(12.0 * sigma * sigma / max(1, passes) + 1.0)))
    w = max(1, w)
    return w if w % 2 == 1 else w + 1


def _box_blur_axis(a: np.ndarray, width: int, axis: int) -> np.ndarray:
    """沿单个轴做宽 ``width`` 的盒式模糊。用**前缀和**，复杂度与宽度无关。"""
    if width <= 1:
        return a
    r = width // 2
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    ap = np.pad(a, pad, mode="edge")            # 边界按 edge 复制，避免暗边
    c = np.cumsum(ap, axis=axis, dtype=np.float32)
    zero_shape = list(c.shape)
    zero_shape[axis] = 1
    c = np.concatenate([np.zeros(zero_shape, dtype=np.float32), c], axis=axis)
    n = a.shape[axis]
    idx = np.arange(n)
    hi = np.take(c, idx + width, axis=axis)
    lo = np.take(c, idx, axis=axis)
    return (hi - lo) / np.float32(width)


def _box_blur(rgba_pm: np.ndarray, radius: float, passes: int = 3) -> np.ndarray:
    sigma = max(0.0, float(radius)) / 2.0        # radius 按约 2σ 解释
    if sigma <= 0.0:
        return rgba_pm
    w = _box_width_for_sigma(sigma, passes)
    out = rgba_pm
    for _ in range(max(1, int(passes))):
        out = _box_blur_axis(out, w, 1)          # 横向
        out = _box_blur_axis(out, w, 0)          # 纵向
    return out


# ------------------------------------------------------------------ 算子
def blur(rgba: np.ndarray, radius: float, *, passes: int = 3) -> np.ndarray:
    """高斯模糊（盒式×3 近似）。``radius`` 按约 2σ 解释，0 表示不处理。

    **alpha 感知**：先预乘再卷积再还原，所以透明区域的 RGB 不会污染边缘。
    """
    r = float(radius)
    if r <= 0:
        return rgba.astype(np.float32, copy=True)
    alpha = rgba[..., 3:4].astype(np.float32)
    pm = _premultiply(rgba)
    pm = _box_blur(pm, r, passes)
    # 注意：预乘后模糊，alpha 通道也在被卷积，这正是我们要的（羽化边缘）
    return _unpremultiply(pm, pm[..., 3:4])


def box_blur(rgba: np.ndarray, radius: float) -> np.ndarray:
    """单次盒式模糊（比高斯更"方"，做特殊风格时有用）。"""
    r = float(radius)
    if r <= 0:
        return rgba.astype(np.float32, copy=True)
    pm = _premultiply(rgba)
    pm = _box_blur_axis(_box_blur_axis(pm, max(1, int(r) * 2 + 1), 1),
                        max(1, int(r) * 2 + 1), 0)
    return _unpremultiply(pm, pm[..., 3:4])


def hue_saturation_matrix(hue_deg: float, saturation: float) -> np.ndarray:
    """CSS/SVG 规范的 hue-rotate × saturate 颜色矩阵（3×3）。

    照抄标准而不是自己推：这样结果和浏览器 CSS `filter: hue-rotate() saturate()`
    一致，用户（和 AI）已有的直觉可以直接迁移。
    """
    a = np.radians(float(hue_deg))
    c, s = float(np.cos(a)), float(np.sin(a))
    # SVG feColorMatrix type="hueRotate"
    h = np.array([
        [0.213 + c * 0.787 - s * 0.213, 0.715 - c * 0.715 - s * 0.715,
         0.072 - c * 0.072 + s * 0.928],
        [0.213 - c * 0.213 + s * 0.143, 0.715 + c * 0.285 + s * 0.140,
         0.072 - c * 0.072 - s * 0.283],
        [0.213 - c * 0.213 - s * 0.787, 0.715 - c * 0.715 + s * 0.715,
         0.072 + c * 0.928 + s * 0.072],
    ], dtype=np.float32)
    # SVG feColorMatrix type="saturate"
    t = 1.0 - float(saturation)
    sat = np.array([
        [_LUMA[0] * t + saturation, _LUMA[1] * t, _LUMA[2] * t],
        [_LUMA[0] * t, _LUMA[1] * t + saturation, _LUMA[2] * t],
        [_LUMA[0] * t, _LUMA[1] * t, _LUMA[2] * t + saturation],
    ], dtype=np.float32)
    return (sat @ h).astype(np.float32)


def adjust(rgba: np.ndarray, *, brightness: float = 1.0, contrast: float = 1.0,
           saturation: float = 1.0, hue: float = 0.0, gamma: float = 1.0,
           ) -> np.ndarray:
    """调色。所有参数以 **1.0 = 原样** 为基准（与 Pillow `ImageEnhance` 一致）。

    - `brightness` 乘亮度、`contrast` 以 0.5 为轴缩放、`saturation` 绕 Rec.709 灰度轴
    - `hue` 色相旋转（度）、`gamma` 伽马校正（RGB 取 ``1/gamma`` 次幂）
    - **alpha 通道不变**（调色不该改变不透明度）
    """
    out = rgba.astype(np.float32, copy=True)
    rgb = out[..., :3]
    if saturation != 1.0 or hue != 0.0:
        m = hue_saturation_matrix(hue, saturation)
        flat = rgb.reshape(-1, 3)
        rgb[:] = (flat @ m.T).reshape(rgb.shape)
    if brightness != 1.0:
        rgb *= np.float32(brightness)
    if contrast != 1.0:
        rgb[:] = (rgb - 0.5) * np.float32(contrast) + 0.5
    if gamma != 1.0:
        g = max(1e-4, float(gamma))
        rgb[:] = np.power(np.clip(rgb, 0.0, 1.0), 1.0 / g)
    np.clip(rgb, 0.0, 1.0, out=rgb)
    return out


def posterize(rgba: np.ndarray, levels: int) -> np.ndarray:
    """色阶量化（海报效果）。``levels`` = 每个通道保留几档，≥2。"""
    n = max(2, int(levels))
    out = rgba.astype(np.float32, copy=True)
    out[..., :3] = np.round(np.clip(out[..., :3], 0.0, 1.0) * (n - 1)) / (n - 1)
    return out


def solarize(rgba: np.ndarray, threshold: float = 0.5) -> np.ndarray:
    """曝光过度效果：亮于 ``threshold`` 的通道取反。"""
    t = float(np.clip(threshold, 0.0, 1.0))
    out = rgba.astype(np.float32, copy=True)
    rgb = np.clip(out[..., :3], 0.0, 1.0)
    out[..., :3] = np.where(rgb > t, 1.0 - rgb, rgb)
    return out


def invert(rgba: np.ndarray) -> np.ndarray:
    """反相（alpha 不动 —— 反相不该改变不透明度）。"""
    out = rgba.astype(np.float32, copy=True)
    out[..., :3] = 1.0 - np.clip(out[..., :3], 0.0, 1.0)
    return out


def grayscale(rgba: np.ndarray, amount: float = 1.0) -> np.ndarray:
    """去色。``amount`` = 1 全灰、0.5 半灰、0 不变（比 Pillow 的纯黑更好用）。"""
    k = float(np.clip(amount, 0.0, 1.0))
    out = rgba.astype(np.float32, copy=True)
    luma = (np.clip(out[..., :3], 0.0, 1.0) * _LUMA).sum(axis=-1, keepdims=True)
    out[..., :3] = out[..., :3] * (1.0 - k) + luma * k
    np.clip(out[..., :3], 0.0, 1.0, out=out[..., :3])
    return out


def grain(rgba: np.ndarray, amount: float = 0.05, *, seed: int = 0,
          mono: bool = True) -> np.ndarray:
    """胶片颗粒。``seed`` 保证可复现（这是本项目的核心承诺之一）。

    ⚠️ 与 `patterns.noise` 的区别：那个是**生成**一张噪点底图；
    这个是往**已有内容**上叠颗粒 —— 素材与算子的分界就在这里。
    """
    a = float(amount)
    if a <= 0:
        return rgba.astype(np.float32, copy=True)
    g = np.random.default_rng(int(seed))
    h, w = rgba.shape[:2]
    if mono:
        delta = (g.random((h, w, 1), dtype=np.float32) - 0.5) * a
    else:
        delta = (g.random((h, w, 3), dtype=np.float32) - 0.5) * a
    out = rgba.astype(np.float32, copy=True)
    out[..., :3] = np.clip(out[..., :3] + delta, 0.0, 1.0)
    return out


def sample_bilinear(src: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """双线性重采样。``xs``/``ys`` 是与输出同形状的坐标数组（越界按边缘夹取）。

    支持 2D 场（``(h, w)``）与 3D 图像（``(h, w, C)``）—— 后者会自动扩展权重轴。
    """
    h, w = src.shape[:2]
    x0 = np.floor(xs).astype(np.int32)
    y0 = np.floor(ys).astype(np.int32)
    fx = (xs - x0).astype(np.float32)
    fy = (ys - y0).astype(np.float32)
    zx0 = np.clip(x0, 0, w - 1)
    zx1 = np.clip(x0 + 1, 0, w - 1)
    zy0 = np.clip(y0, 0, h - 1)
    zy1 = np.clip(y0 + 1, 0, h - 1)
    a = src[zy0, zx0]
    b = src[zy0, zx1]
    c = src[zy1, zx0]
    d = src[zy1, zx1]
    if src.ndim == 3:
        fx = fx[..., None]
        fy = fy[..., None]
    top = a + (b - a) * fx
    bot = c + (d - c) * fx
    return (top + (bot - top) * fy).astype(np.float32)


def warp_field(src: np.ndarray, dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
    """域扭曲：把 ``src`` 沿位移场 ``(dx, dy)``（像素）重采样。

    与 `noise.domain_warp` 配合使用 —— 这是把"规整噪声"变成云/大理石/火焰的那一步。
    """
    h, w = src.shape[:2]
    if dx.shape != (h, w) or dy.shape != (h, w):
        raise ValueError(f"位移场形状应为 {(h, w)}，收到 {dx.shape} / {dy.shape}")
    xs = np.arange(w, dtype=np.float32)[None, :] + dx
    ys = np.arange(h, dtype=np.float32)[:, None] + dy
    return sample_bilinear(src, xs, ys)


def resize(rgba: np.ndarray, width: int, height: int) -> np.ndarray:
    """整幅缩放（双线性，**alpha 感知**）。

    和模糊一样必须预乘再重采样：直通道直接插值时，透明像素的 RGB 会被混进来，
    缩小后的边缘会发暗。

    ⚠️ 这是**库函数**，不是 DSL 动词 —— 矢量域里的"缩放"是改 ``viewBox``（一次性设定），
    和位图域"对已绘内容做变换"不是同一件事。把它塞进场景 op 列表会破坏双后端的语义一致性，
    所以不进（见 docs/能力边界.md）。

    **要"变换已绘内容"的缩放请用 `affine_resample`** —— 那个才是双后端同语义的
    （矢量端对应 ``<g transform="matrix(…)">``），也是 DSL 里 ``transform`` 动词的实现。
    一句话分工：**改画布尺寸 = `resize`（不进 DSL）；改内容姿态 = `affine_resample`（进 DSL）。**
    """
    h, w = rgba.shape[:2]
    tw, th = max(1, int(width)), max(1, int(height))
    if (tw, th) == (w, h):
        return rgba.astype(np.float32, copy=True)
    # 目标像素中心 → 源坐标（中心对齐，避免整体偏移半个像素）
    xs = ((np.arange(tw, dtype=np.float32) + 0.5) * (w / tw) - 0.5)[None, :]
    ys = ((np.arange(th, dtype=np.float32) + 0.5) * (h / th) - 0.5)[:, None]
    src = rgba if rgba.dtype == np.float32 else rgba.astype(np.float32) / np.float32(255.0)
    pm = _premultiply(src)
    out = sample_bilinear(pm, np.broadcast_to(xs, (th, tw)),
                          np.broadcast_to(ys, (th, tw)))
    return _unpremultiply(out, out[..., 3:4])


def affine_resample(rgba: np.ndarray, m) -> np.ndarray:
    """按仿射矩阵 ``m``（``geometry.Affine`` 的 6 元组）重采样整幅图，**尺寸不变**。

    三条都与"旋转后边缘会不会脏"直接相关，缺一条都会出可见的瑕疵：

    1. **预乘 alpha**：直通道直接插值时，透明像素的 RGB（通常是 0,0,0）会被混进来，
       旋转/缩放后的边缘会泛一圈黑边。和 `blur` 踩过的是同一个坑。
    2. **越界置透明，而不是夹取边缘**：`sample_bilinear` 自己的策略是夹取
       （对域扭曲是对的 —— 位移场几乎跑不出画布），但仿射**旋转**后四角必然取样到画布外，
       夹取会把最外圈像素拉成长条糊出去，看着像拖影。
    3. **反向映射（目标找源）**：正向映射（源找目标）在放大时会在目标上留下空洞。
    """
    from .geometry import affine_invert

    h, w = rgba.shape[:2]
    if h < 1 or w < 1:
        return rgba.astype(np.float32, copy=True)
    src = (rgba if rgba.dtype == np.float32
           else rgba.astype(np.float32) / np.float32(255.0))

    # 目标像素中心（连续坐标：像素 i 的中心在 i + 0.5）→ 逆变换 → 源连续坐标
    ia, ib, ic, idd, ie, iff = affine_invert(m)
    gx = (np.arange(w, dtype=np.float32) + 0.5)[None, :]
    gy = (np.arange(h, dtype=np.float32) + 0.5)[:, None]
    xs = ia * gx + ic * gy + ie
    ys = ib * gx + idd * gy + iff

    pm = _premultiply(src)
    # `sample_bilinear` 工作在**索引空间**（像素中心 = 整数），所以这里减 0.5
    out = sample_bilinear(pm, xs - np.float32(0.5), ys - np.float32(0.5))
    # 图像在连续坐标里覆盖 [0, w] × [0, h]；外面直接透明（见 docstring 第 2 条）
    outside = (xs < 0.0) | (xs > np.float32(w)) | (ys < 0.0) | (ys > np.float32(h))
    if outside.any():
        out[outside] = 0.0
    return _unpremultiply(out, out[..., 3:4])
