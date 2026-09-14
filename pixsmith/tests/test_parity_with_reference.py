"""与纯 Python 参考实现的**逐像素一致性**校验。

这是本项目最重要的一组测试：NumPy 版是对参考实现的重写，
「看起来一样」不算数 —— 只有逐像素对照能证明**公式没被改掉**。

容差取 ±1：参考实现每一步都量化到字节，NumPy 版全程保留浮点、最后才取整，
单次图元操作下两者最多差 1（多图元叠加会累积，所以只在单操作上比对）。

⚠️ 唯一一处**故意不一致**：``ring``（见文件末尾的
``test_ring_divergence_from_original_is_documented``）。原实现在内边缘羽化失效，
pixsmith 用的是修正版，所以这里对照的是 ``ring_normalized``。
"""

from __future__ import annotations

import numpy as np
import pytest

from benchmarks.pure_python_reference import PixelCanvas
from pixsmith.canvas import Canvas

W, H = 140, 100
BG = "#102030"
BG8 = (16, 32, 48, 255)


def _rgba255(hexcolor: str) -> tuple[int, int, int, int]:
    h = hexcolor.lstrip("#")
    if len(h) == 6:
        h += "ff"
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]


def _star_pts(cx, cy, r, points=5, ang=-90.0, inner=0.382):
    step = 360.0 / (points * 2)
    out = []
    for i in range(points * 2):
        rr = r if i % 2 == 0 else r * inner
        a = np.radians(ang + i * step)
        out.append((cx + np.cos(a) * rr, cy + np.sin(a) * rr))
    return out


# (名称, 画布方法, 位置参数, 颜色, 关键字参数, [参考实现方法名])
CASES = [
    ("不透明圆", "disc", (40.5, 30.25, 18.0), "#F2C14EFF", {"feather": 1.0}),
    ("半透明圆", "disc", (70.0, 50.0, 22.0), "#F2C14EB0", {"feather": 1.6}),
    ("半透明小圆", "disc", (25.0, 22.0, 6.0), "#FFFFFF40", {"feather": 1.0}),
    ("圆环(修正版)", "ring", (60.0, 45.0, 30.0, 18.0), "#4FD1C5FF",
     {"feather": 1.0}, "ring_normalized"),
    ("椭圆(带旋转)", "ellipse", (55.0, 40.0, 26.0, 13.0), "#F0C24E90", {"ang": 27.0}),
    ("矩形(非整数边)", "rect", (12.4, 8.7, 60.0, 34.0), "#FFFFFFFF", {}),
    ("半透明矩形", "rect", (20.0, 15.0, 50.0, 30.0), "#9B8CFA66", {}),
    ("水平胶囊", "capsule", (10.0, 50.0, 130.0, 50.0, 6.0), "#FF8A6BFF", {}),
    ("斜向胶囊(半透明)", "capsule", (8.0, 90.0, 132.0, 12.0, 5.0), "#5FD6A0C0", {}),
    ("跨块长胶囊", "capsule", (5.0, 95.0, 260.0, 5.0, 5.0), "#5FD6A0C0", {}),
    ("弧段(上半)", "arc", (70.0, 50.0, 34.0, 22.0, 0.0, 3.14159265), "#FFDE00FF", {}),
    ("三角形", "polygon", ([((20.0, 80.0), (70.0, 12.0), (120.0, 80.0))]), "#C8102EFF",
     {"ss": 3}),
    ("五角星", "polygon", ([tuple(_star_pts(70.0, 50.0, 40.0))]), "#FFE9AFAA", {"ss": 2}),
    ("六边形", "polygon", ([tuple(_star_pts(70.0, 50.0, 36.0, points=3, inner=1.0))]),
     "#4FD1C5FF", {"ss": 3}),
]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_pixel_parity_with_reference(case):
    name, kind, args, color, kwargs = case[:5]
    ref_kind = case[5] if len(case) > 5 else kind

    cn = Canvas(W, H, BG)
    getattr(cn, kind)(*args, color, **kwargs)
    a = cn.to_rgba8()

    rf = PixelCanvas(W, H, BG8)
    getattr(rf, ref_kind)(*args, _rgba255(color), **kwargs)
    b = np.array(rf.to_rgba(), dtype=np.uint8)

    assert a.shape == b.shape
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    bad = int((diff.max(axis=2) > 1).sum())
    assert diff.max() <= 1 and bad == 0, (
        f"{name}: 与参考实现最大偏差 {diff.max()}，超出容差的像素 {bad} 个")
    assert diff.mean() < 0.02, f"{name}: 平均偏差 {diff.mean():.4f} 偏大"


def test_parity_on_transparent_canvas():
    """透明底也要一致 —— 直通道 alpha 的除法分支最容易在这里写错。"""
    w = h = 80
    cn = Canvas(w, h)
    rf = PixelCanvas(w, h, (0, 0, 0, 0))
    cn.disc(40.0, 40.0, 26.0, "#F2C14E80", feather=1.4)
    rf.disc(40.0, 40.0, 26.0, _rgba255("#F2C14E80"), feather=1.4)
    cn.rect(0.0, 0.0, 30.0, 30.0, "#4FD1C580")
    rf.rect(0.0, 0.0, 30.0, 30.0, _rgba255("#4FD1C580"))
    a, b = cn.to_rgba8(), np.array(rf.to_rgba(), dtype=np.uint8)
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    assert diff.max() <= 1
    assert (a[..., 3] > 0).any() and (a[..., 3] < 255).any(), "应存在半透明像素"


def test_ring_divergence_from_original_is_documented():
    """把「圆环内边缘羽化」这处**故意不一致**钉成回归测试。

    原始 ``ring()`` 把未归一化的外圈覆盖率乘进 ``(1 - ci)``，``over()`` 截断后
    内边缘变成硬边。若哪天有人"顺手对齐"了实现，这条会失败并提醒他看 docstring。
    """
    cn = Canvas(W, H, BG)
    cn.ring(60.0, 45.0, 30.0, 18.0, "#4FD1C5FF", feather=1.0)
    a = cn.to_rgba8()

    rf_new = PixelCanvas(W, H, BG8)
    rf_new.ring_normalized(60.0, 45.0, 30.0, 18.0, _rgba255("#4FD1C5FF"), feather=1.0)
    b_new = np.array(rf_new.to_rgba(), dtype=np.uint8)
    assert np.abs(a.astype(np.int16) - b_new.astype(np.int16)).max() <= 1

    rf_old = PixelCanvas(W, H, BG8)
    rf_old.ring(60.0, 45.0, 30.0, 18.0, _rgba255("#4FD1C5FF"), feather=1.0)
    b_old = np.array(rf_old.to_rgba(), dtype=np.uint8)
    d = np.abs(a.astype(np.int16) - b_old.astype(np.int16))
    assert d.max() > 100, "与原实现的差异应当显著（否则这处修正就没意义了）"
    assert 50 < int((d.max(axis=2) > 1).sum()) < 400, "差异应集中在内边缘一带"
