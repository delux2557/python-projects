"""噪声族的正确性、确定性与"结构感"测试。"""

from __future__ import annotations

import numpy as np
import pytest

from pixsmith import noise
from pixsmith.noise import (KINDS, cellular_noise, domain_warp, fbm, field,
                            perlin_noise, value_noise)

W, H = 128, 96


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_returns_normalized_field(kind):
    a = field(kind, W, H, freq=4.0, seed=1)
    assert a.shape == (H, W)
    assert a.dtype == np.float32
    assert 0.0 <= float(a.min()) and float(a.max()) <= 1.0


@pytest.mark.parametrize("fn", [value_noise, perlin_noise])
def test_scalar_noise_is_deterministic_and_seed_sensitive(fn):
    a = fn(W, H, freq=4.0, seed=7)
    b = fn(W, H, freq=4.0, seed=7)
    c = fn(W, H, freq=4.0, seed=8)
    assert np.array_equal(a, b), "同 seed 必须逐元素一致"
    assert not np.allclose(a, c), "换 seed 应改变结果"


def test_noise_is_smooth_not_random():
    """噪声的本质是**空间相关**：相邻像素差应远小于均匀随机的相邻差。"""
    n = perlin_noise(W, H, freq=4.0, seed=3)
    smooth_step = float(np.abs(np.diff(n, axis=1)).mean())
    rng = np.random.default_rng(0).random((H, W), dtype=np.float32)
    random_step = float(np.abs(np.diff(rng, axis=1)).mean())
    assert smooth_step < random_step * 0.25, (
        f"Perlin 相邻差 {smooth_step:.4f} 应远小于均匀随机 {random_step:.4f}")


def test_higher_freq_gives_finer_structure():
    """freq 是"画布上有几个周期"——调大必然更细。用相邻差衡量。"""
    low = perlin_noise(W, H, freq=2.0, seed=5)
    high = perlin_noise(W, H, freq=12.0, seed=5)
    assert float(np.abs(np.diff(high, axis=1)).mean()) > \
        float(np.abs(np.diff(low, axis=1)).mean())


def test_value_noise_has_flat_lattice_points_or_at_least_extremes():
    """值噪声在格点上取到极值（构造性质），可作为实现正确性的一条判据。"""
    n = value_noise(W, H, freq=4.0, seed=2)
    assert float(n.max()) > 0.8 and float(n.min()) < 0.2


def test_fbm_adds_detail_compared_to_single_octave():
    """fBm 的意义就是"多尺度叠加"——细节必然比单层多。"""
    one = perlin_noise(W, H, freq=2.0, seed=11)
    many = fbm(W, H, octaves=6, freq=2.0, persistence=0.5, seed=11)
    g1 = float(np.abs(np.diff(one, axis=1)).mean())
    g2 = float(np.abs(np.diff(many, axis=1)).mean())
    assert g2 > g1, f"fBm 相邻差 {g2:.4f} 应大于单层 {g1:.4f}"


def test_fbm_persistence_controls_roughness():
    """persistence 越大越粗糙（高频层的振幅衰减越慢）。"""
    fine = fbm(W, H, octaves=6, freq=2.0, persistence=0.2, seed=4)
    rough = fbm(W, H, octaves=6, freq=2.0, persistence=0.8, seed=4)
    assert float(np.abs(np.diff(rough, axis=1)).mean()) > \
        float(np.abs(np.diff(fine, axis=1)).mean())


def test_fbm_is_deterministic():
    a = fbm(W, H, octaves=5, seed=13)
    b = fbm(W, H, octaves=5, seed=13)
    assert np.array_equal(a, b)


def test_fbm_rejects_unknown_kind():
    with pytest.raises(ValueError):
        fbm(W, H, kind="nope")


@pytest.mark.parametrize("mode", ["f1", "f2f1", "cell"])
def test_cellular_modes(mode):
    a = cellular_noise(W, H, freq=6.0, seed=1, mode=mode)
    assert a.shape == (H, W)
    assert 0.0 <= float(a.min()) and float(a.max()) <= 1.0
    assert float(a.std()) > 0.01, "细胞噪声不该是常数场"


def test_cellular_edge_mode_is_distinct_continuous_and_skewed_low():
    """``f2f1``（次近 − 最近）= 细胞边界场。

    ⚠️ 别想当然以为它给出"细线"：实测低于 0.25 的像素占 ~54% ——
    因为 d2−d1 在边界处为 0、向细胞中心近似线性增长，所以**边界是一圈"低值带"而非细线**。
    要细线得再取阈值（如 `e < 0.05`）。这里断言的是它真正的性质：
    存在真零边界、分布向低值偏斜、且是连续场（阈值提高 → 占比单调上升）。
    """
    e = cellular_noise(W, H, freq=5.0, seed=9, mode="f2f1")
    f1 = cellular_noise(W, H, freq=5.0, seed=9, mode="f1")
    assert float(e.min()) < 0.02, "应存在 d2 == d1 的真实边界"
    assert float(e.mean()) < 0.4, "边界场应显著偏向低值"
    assert not np.allclose(e, f1), "边界模式与距离模式必须是不同的场"
    assert float((e < 0.05).mean()) < float((e < 0.15).mean()) < float((e < 0.30).mean())


def test_cellular_rejects_unknown_mode():
    with pytest.raises(ValueError):
        cellular_noise(W, H, mode="nope")


def test_cellular_is_deterministic():
    a = cellular_noise(W, H, freq=6.0, seed=21, mode="f1")
    b = cellular_noise(W, H, freq=6.0, seed=21, mode="f1")
    assert np.array_equal(a, b)


def test_jitter_changes_layout_but_reproducible():
    a = cellular_noise(W, H, freq=5.0, seed=3, jitter=0.0)
    b = cellular_noise(W, H, freq=5.0, seed=3, jitter=1.0)
    assert not np.allclose(a, b)
    assert np.array_equal(a, cellular_noise(W, H, freq=5.0, seed=3, jitter=0.0))


def test_domain_warp_returns_pixel_scale_displacement():
    dx, dy = domain_warp(W, H, strength=0.3, freq=3.0, seed=1)
    assert dx.shape == (H, W) and dy.shape == (H, W)
    assert dx.dtype == np.float32
    # strength=0.3 × min(128,96)=96 → 约 ±29px
    assert 5.0 < float(np.abs(dx).max()) < 40.0
    assert not np.allclose(dx, dy), "两个通道用不同子种子，不该相同"


def test_domain_warp_is_deterministic():
    a = domain_warp(W, H, seed=5)
    b = domain_warp(W, H, seed=5)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_noise_module_exports_expected_api():
    for name in ("value_noise", "perlin_noise", "cellular_noise", "fbm",
                 "domain_warp", "field", "KINDS"):
        assert hasattr(noise, name), f"缺少 {name}"
