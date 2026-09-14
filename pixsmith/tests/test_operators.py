"""一元算子（filters）与二元算子（blend）的测试。

重点是三条**容易写错、出错还看不出来**的性质：

1. 模糊必须 alpha 感知（否则透明边缘渗黑边）
2. 模糊必须 O(n)（否则大半径卡死）
3. 混合必须符合 CSS/PDF 公式（否则与浏览器 `mix-blend-mode` 对不上）
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from pixsmith import blend as B
from pixsmith import filters as F

H, W = 64, 64


def _blank(alpha=0.0):
    a = np.zeros((H, W, 4), dtype=np.float32)
    a[..., 3] = alpha
    return a


def _dot(color=(1.0, 1.0, 1.0), r=10):
    """中心一个不透明圆点，四周全透明 —— 检验"边缘渗透"的标准素材。"""
    c = _blank()
    yy, xx = np.mgrid[0:H, 0:W]
    mask = np.hypot(xx - W / 2 + 0.5, yy - H / 2 + 0.5) <= r
    c[mask] = (*color, 1.0)
    return c


# ------------------------------------------------------------------ 模糊
def test_blur_zero_radius_is_identity():
    a = _dot()
    assert np.array_equal(F.blur(a, 0), a)


def test_blur_preserves_total_alpha():
    """模糊是能量守恒的（边缘用 edge 复制，总量应基本不变）。"""
    a = _dot(r=12)
    b = F.blur(a, 6.0)
    assert abs(float(b[..., 3].sum()) - float(a[..., 3].sum())) / a[..., 3].sum() < 0.05


def test_blur_does_not_bleed_dark_halo():
    """⭐ 核心：半透明边缘的 RGB 应保持白，不能变成灰。

    直通道 RGBA 直接卷积时，透明像素的 RGB=(0,0,0) 会被平均进来 → 出现暗边。
    本实现先预乘 alpha 再卷积，所以边缘像素的 RGB 必须是接近 (1,1,1) 的白。
    """
    a = _dot(color=(1.0, 1.0, 1.0), r=12)
    b = F.blur(a, 8.0)
    edge = (b[..., 3] > 0.05) & (b[..., 3] < 0.95)
    assert edge.sum() > 50, "应当存在一批半透明边缘像素"
    rgb = b[..., :3][edge]
    assert float(rgb.min()) > 0.90, (
        f"边缘 RGB 最小值 {rgb.min():.3f} 偏低 → 出现了暗边（预乘没做好）")


def test_blur_reduces_high_frequency_energy_monotonically():
    """模糊半径越大，高频能量越小 —— 单调性比"降了一半"这种硬阈值更可靠。"""
    a = _dot(r=4)
    e = lambda x: float(np.abs(np.diff(x[..., 3], axis=1)).mean())  # noqa: E731
    e0, e4, e8, e16 = e(a), e(F.blur(a, 4.0)), e(F.blur(a, 8.0)), e(F.blur(a, 16.0))
    assert e0 > e4 > e8 > e16, f"高频能量应随半径单调下降：{e0:.5f}/{e4:.5f}/{e8:.5f}/{e16:.5f}"


def test_blur_is_affordable_at_large_radius():
    """大半径不能退化成 O(n·r) —— 4K 画布上半径 200 必须在秒级内完成。"""
    big = np.zeros((1080, 1920, 4), dtype=np.float32)
    big[400:700, 700:1200] = (1.0, 0.4, 0.2, 1.0)
    t0 = time.perf_counter()
    F.blur(big, 200.0)
    dt = time.perf_counter() - t0
    assert dt < 5.0, f"半径 200 的 1920×1080 模糊耗时 {dt:.2f}s，实现可能不是 O(n)"


def test_box_blur_runs():
    a = _dot()
    b = F.box_blur(a, 4.0)
    assert b.shape == a.shape and float(b[..., 3].max()) <= 1.0


# ------------------------------------------------------------------ 调色
def test_adjust_identity_is_noop():
    a = _dot(color=(0.3, 0.6, 0.9))
    assert np.allclose(F.adjust(a), a, atol=1e-6)


def test_adjust_brightness_scales_rgb_only():
    a = _dot(color=(0.8, 0.4, 0.2))
    b = F.adjust(a, brightness=0.5)
    assert np.allclose(b[H // 2, W // 2, :3], [0.4, 0.2, 0.1], atol=1e-5)
    assert b[H // 2, W // 2, 3] == a[H // 2, W // 2, 3]


def test_adjust_saturation_zero_gives_gray():
    a = _dot(color=(0.9, 0.2, 0.1))
    b = F.adjust(a, saturation=0.0)
    px = b[H // 2, W // 2, :3]
    assert abs(px[0] - px[1]) < 1e-4 and abs(px[1] - px[2]) < 1e-4


def test_adjust_hue_rotates_360_back_to_original():
    """色相转 360° 应回到原色（矩阵是正交的 → 这是实现正确性的强判据）。"""
    a = _dot(color=(0.9, 0.35, 0.15))
    b = F.adjust(a, hue=360.0)
    assert np.allclose(b[H // 2, W // 2, :3], a[H // 2, W // 2, :3], atol=2e-3)


def test_adjust_hue_180_is_not_identity():
    a = _dot(color=(0.9, 0.35, 0.15))
    b = F.adjust(a, hue=180.0)
    assert not np.allclose(b[H // 2, W // 2, :3], a[H // 2, W // 2, :3], atol=1e-2)


def test_adjust_contrast_pivots_around_mid_gray():
    a = _dot(color=(0.75, 0.75, 0.75))
    b = F.adjust(a, contrast=2.0)
    assert abs(float(b[H // 2, W // 2, 0]) - 1.0) < 1e-5
    c = _dot(color=(0.25, 0.25, 0.25))
    d = F.adjust(c, contrast=2.0)
    assert abs(float(d[H // 2, W // 2, 0]) - 0.0) < 1e-5


def test_adjust_gamma_moves_midtones():
    a = _dot(color=(0.5, 0.5, 0.5))
    assert float(F.adjust(a, gamma=2.0)[H // 2, W // 2, 0]) > 0.6
    assert float(F.adjust(a, gamma=0.5)[H // 2, W // 2, 0]) < 0.4


# ------------------------------------------------------------------ 其它一元
def test_posterize_quantizes():
    a = _dot(color=(0.63, 0.63, 0.63))
    v2 = float(F.posterize(a, 2)[H // 2, W // 2, 0])
    assert v2 in (0.0, 1.0)
    v4 = float(F.posterize(a, 4)[H // 2, W // 2, 0])
    assert any(abs(v4 - x) < 1e-6 for x in (0.0, 1 / 3, 2 / 3, 1.0))
    # 档数越多越接近原值
    assert abs(float(F.posterize(a, 64)[H // 2, W // 2, 0]) - 0.63) < 0.02


def test_solarize_thresholds():
    a = _dot(color=(0.8, 0.2, 0.5))
    assert np.allclose(F.solarize(a, 1.0), a, atol=1e-6)          # 阈值 1 → 全不变
    inv = F.solarize(a, 0.0)
    assert np.allclose(inv[H // 2, W // 2, :3], [0.2, 0.8, 0.5], atol=1e-5)


def test_invert_twice_is_identity():
    a = _dot(color=(0.3, 0.7, 0.1))
    assert np.allclose(F.invert(F.invert(a)), a, atol=1e-6)


def test_grayscale_amount_is_interpolated():
    a = _dot(color=(0.9, 0.2, 0.1))
    half = F.grayscale(a, 0.5)[H // 2, W // 2, :3]
    full = F.grayscale(a, 1.0)[H // 2, W // 2, :3]
    assert not np.allclose(half, full)
    assert abs(full[0] - full[1]) < 1e-5


def test_grain_is_deterministic_and_alpha_preserving():
    a = _dot(color=(0.5, 0.5, 0.5))
    g1 = F.grain(a, 0.2, seed=5)
    g2 = F.grain(a, 0.2, seed=5)
    g3 = F.grain(a, 0.2, seed=6)
    assert np.array_equal(g1, g2), "grain 必须可复现"
    assert not np.allclose(g1, g3)
    assert np.allclose(g1[..., 3], a[..., 3]), "颗粒不该改 alpha"
    assert np.allclose(F.grain(a, 0.0), a)


# ------------------------------------------------------------------ 重采样
def test_sample_bilinear_identity():
    a = np.arange(H * W, dtype=np.float32).reshape(H, W)
    xs = np.arange(W, dtype=np.float32)[None, :].repeat(H, axis=0)
    ys = np.arange(H, dtype=np.float32)[:, None].repeat(W, axis=1)
    assert np.allclose(F.sample_bilinear(a, xs, ys), a, atol=1e-3)


def test_warp_field_with_zero_displacement_is_identity():
    a = np.arange(H * W, dtype=np.float32).reshape(H, W)
    z = np.zeros((H, W), dtype=np.float32)
    assert np.allclose(F.warp_field(a, z, z), a, atol=1e-3)


def test_warp_field_rejects_shape_mismatch():
    a = np.zeros((H, W), dtype=np.float32)
    with pytest.raises(ValueError):
        F.warp_field(a, np.zeros((H, W - 1), np.float32), np.zeros((H, W), np.float32))


# ------------------------------------------------------------------ 混合
def _opaque(rgb):
    a = np.zeros((8, 8, 4), dtype=np.float32)
    a[..., :3] = rgb
    a[..., 3] = 1.0
    return a


def test_normal_with_full_opacity_replaces():
    dst = _opaque((0.2, 0.2, 0.2))
    src = _opaque((0.8, 0.4, 0.1))
    out = B.blend(src, dst, "normal", 1.0)
    assert np.allclose(out[0, 0, :3], [0.8, 0.4, 0.1], atol=1e-5)


def test_zero_opacity_keeps_destination():
    dst = _opaque((0.2, 0.3, 0.4))
    src = _opaque((0.9, 0.9, 0.9))
    out = B.blend(src, dst, "multiply", 0.0)
    assert np.allclose(out, dst, atol=1e-6)


@pytest.mark.parametrize("mode,expected", [
    ("multiply", 0.2 * 0.5),
    ("screen", 0.2 + 0.5 - 0.2 * 0.5),
    ("darken", 0.2),
    ("lighten", 0.5),
    ("difference", 0.3),
    ("linear-dodge", 0.7),
    ("linear-burn", 0.0),
])
def test_blend_formulas_match_spec(mode, expected):
    """两块**不透明**内容做混合时，结果应等于纯粹的 B(Cb, Cs)。"""
    dst = _opaque((0.2, 0.2, 0.2))
    src = _opaque((0.5, 0.5, 0.5))
    out = B.blend(src, dst, mode, 1.0)
    assert abs(float(out[0, 0, 0]) - expected) < 1e-5


def test_blend_aliases_resolve():
    assert B._resolve("over") == "normal"
    assert B._resolve("add") == "linear-dodge"
    assert B._resolve("soft_light") == "soft-light"
    assert B.is_mode("over") and not B.is_mode("nope")


def test_blend_rejects_unknown_mode_and_shape_mismatch():
    a = _opaque((1, 1, 1))
    with pytest.raises(ValueError):
        B.blend(a, a, "nope")
    with pytest.raises(ValueError):
        B.blend(a, np.zeros((4, 4, 4), np.float32))
    with pytest.raises(ValueError):
        B.blend(a, np.zeros((8, 8, 3), np.float32))


def test_blend_alpha_math_matches_source_over():
    """半透明源叠在不透明底上：αo 应恒为 1，颜色按 αs 线性插值（normal 模式）。"""
    dst = _opaque((0.0, 0.0, 0.0))
    src = _opaque((1.0, 1.0, 1.0))
    src[..., 3] = 0.25
    out = B.blend(src, dst, "normal", 1.0)
    assert abs(float(out[0, 0, 0]) - 0.25) < 1e-5
    assert abs(float(out[0, 0, 3]) - 1.0) < 1e-5


def test_all_documented_modes_execute():
    dst = _opaque((0.3, 0.5, 0.7))
    src = _opaque((0.6, 0.4, 0.2))
    for mode in B.MODES:
        out = B.blend(src, dst, mode, 0.7)
        assert out.shape == dst.shape
        assert np.isfinite(out).all()
        assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0
