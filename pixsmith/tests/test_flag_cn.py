"""五星红旗的**国标符合性**校验（全部从渲染出的像素反测，不靠"看着像"）。

为什么值得单独一个文件：这是整个库里唯一一个**有官方标准答案**的图案 ——
GB 12982《国旗》规定了 30×20 网格、大星中心 (5, 5) 半径 3、四小星半径 1，
而且**每颗小星都要有一个角尖指向大星中心**。
「指向」这种约束最容易写错（少旋转 90°、方向取反），肉眼还不一定看得出来，
所以这里用「沿指定方向的最远着色半径」把它量化。

两条测量学注记：

* **尖角读数会偏小 1.5–2px** —— 尖端只有一个像素宽，抗锯齿把它混成了
  红黄之间的过渡色，严格判到底是"黄"的采样点因而提前结束。
  这不是几何误差，而是**判据的固有偏差**，所以容差按"尖角 3px / 凹口 2px"给。
* 因此更硬的断言是**比值不变量**：``尖角 / 凹口 ≈ 1 / 0.382 = 2.618``。
  它与抗锯齿无关，能真正卡住"形状对不对"。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pixsmith.recipes import render

W, H = 900, 600           # 3:2，u = 30px，星心恰好落在整数像素上
U = W / 30.0
BIG = (5 * U, 5 * U)
SMALL = [(gx * U, gy * U) for gx, gy in ((10, 2), (12, 4), (12, 7), (10, 9))]
OUTER = 3 * U
SMALL_OUTER = 1 * U
INNER_RATIO = 0.382
TOL_TIP = 4.0             # 尖角读数侵蚀 1.6–3.4px（随尖端的亚像素落点变化）
TOL_NOTCH = 2.0

# 五角星的外尖角方向（一个角朝正上，然后每 72° 一个）
TIP_ANGLES = tuple(-90.0 + 72.0 * k for k in range(5))
NOTCH_ANGLES = tuple(-54.0 + 72.0 * k for k in range(5))


@pytest.fixture(scope="module")
def flag():
    return render({"pattern": "flag_cn", "size": [W, H]}).to_rgba8()


def _is_yellow(px) -> bool:
    return int(px[0]) > 200 and int(px[1]) > 170 and int(px[2]) < 90


def _is_red(px) -> bool:
    return int(px[0]) > 180 and int(px[1]) < 90 and int(px[2]) < 60


def _ray_extent(px, cx, cy, ang_deg, limit, step=0.2):
    """从 (cx, cy) 沿 ang 方向走，返回**最远**的黄色采样点距离。"""
    a = math.radians(ang_deg)
    ca, sa = math.cos(a), math.sin(a)
    last, d = 0.0, 0.0
    while d <= limit:
        x, y = int(round(cx + ca * d)), int(round(cy + sa * d))
        if 0 <= y < px.shape[0] and 0 <= x < px.shape[1] and _is_yellow(px[y, x]):
            last = d
        d += step
    return last


# ------------------------------------------------------------------ 颜色
def test_field_and_star_colors_match_national_standard(flag):
    """国旗标准色：红 #DE2910 / 黄 #FFDE00（不掺一点"接近"）。"""
    assert _is_red(flag[int(15 * U), int(15 * U)]), "旗面应为国旗红"
    assert _is_yellow(flag[int(BIG[1]), int(BIG[0])]), "大星中心应为国旗黄"
    assert tuple(int(v) for v in flag[int(15 * U), int(15 * U), :3]) == (0xDE, 0x29, 0x10)
    assert tuple(int(v) for v in flag[int(BIG[1]), int(BIG[0]), :3]) == (0xFF, 0xDE, 0x00)


# ------------------------------------------------------------------ 大星
def test_big_star_sits_on_grid_point_five_five(flag):
    assert _is_yellow(flag[int(BIG[1]), int(BIG[0])])
    up = _ray_extent(flag, BIG[0], BIG[1], -90.0, OUTER * 1.4)
    down = _ray_extent(flag, BIG[0], BIG[1], 90.0, OUTER * 1.4)
    assert abs(up - OUTER) <= TOL_TIP, f"大星上尖角半径 {up:.1f} 应≈{OUTER:.1f}"
    # 正下方落在两条尖角之间的凹口 → 内接半径
    assert abs(down - OUTER * INNER_RATIO) <= TOL_NOTCH, \
        f"大星正下方应为凹口(≈{OUTER * INNER_RATIO:.1f})，实测 {down:.1f}"


@pytest.mark.parametrize("ang", TIP_ANGLES)
def test_big_star_has_five_outward_points(flag, ang):
    ext = _ray_extent(flag, BIG[0], BIG[1], ang, OUTER * 1.4)
    assert abs(ext - OUTER) <= TOL_TIP, f"{ang:.0f}° 方向尖角延伸 {ext:.1f}，应≈{OUTER:.1f}"


@pytest.mark.parametrize("ang", NOTCH_ANGLES)
def test_big_star_has_five_notches_between_points(flag, ang):
    ext = _ray_extent(flag, BIG[0], BIG[1], ang, OUTER * 1.4)
    assert abs(ext - OUTER * INNER_RATIO) <= TOL_NOTCH, \
        f"{ang:.0f}° 方向应为凹口(≈{OUTER * INNER_RATIO:.1f})，实测 {ext:.1f}"


def test_big_star_shape_ratio_is_scale_free(flag):
    """尖角 / 凹口 ≈ 2.618 —— 与抗锯齿无关的形状不变量。"""
    tip = np.mean([_ray_extent(flag, *BIG, a, OUTER * 1.4) for a in TIP_ANGLES])
    notch = np.mean([_ray_extent(flag, *BIG, a, OUTER * 1.4) for a in NOTCH_ANGLES])
    assert abs(tip / notch - 1.0 / INNER_RATIO) < 0.12, \
        f"尖角/凹口 = {tip / notch:.3f}，应≈{1 / INNER_RATIO:.3f}"


# ------------------------------------------------------------------ 小星
def test_four_small_stars_sit_on_spec_centers(flag):
    for i, (cx, cy) in enumerate(SMALL):
        x, y = int(round(cx)), int(round(cy))
        assert _is_yellow(flag[y, x]), f"第 {i + 1} 颗小星中心 ({x},{y}) 未落到星上"


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_each_small_star_aims_a_point_at_the_big_star(flag, index):
    """GB 12982 的硬约束：小星**一个角尖**对准大星中心。

    量化：沿「小星 → 大星中心」方向应量到外接圆半径 1u；
    反方向应是凹口（内接半径 0.382u）。
    """
    cx, cy = SMALL[index]
    aim = math.degrees(math.atan2(BIG[1] - cy, BIG[0] - cx))
    toward = _ray_extent(flag, cx, cy, aim, SMALL_OUTER * 1.6)
    away = _ray_extent(flag, cx, cy, aim + 180.0, SMALL_OUTER * 1.6)
    assert abs(toward - SMALL_OUTER) <= TOL_TIP, \
        f"第 {index + 1} 颗小星朝向大星应有 {SMALL_OUTER:.0f}px 尖角，实测 {toward:.1f}"
    assert abs(away - SMALL_OUTER * INNER_RATIO) <= TOL_NOTCH, \
        f"第 {index + 1} 颗小星背向应为凹口(≈{SMALL_OUTER * INNER_RATIO:.1f})，实测 {away:.1f}"
    assert toward / max(away, 1e-6) > 2.2, "朝向/背向比值偏小，说明角尖没对准"


# ------------------------------------------------------------------ 整体
def test_total_yellow_area_matches_theoretical_star_area(flag):
    """黄星面积总量校验 —— 抓「多画/少画了一颗星」这类整体性错误。

    正 N 角星（外半径 R、内半径比例 k）的面积，用鞋带公式对 2N 个顶点求和可得
    ``A = N·k·R²·sin(180°/N)``；五角星即 ``5·k·R²·sin36°`` ≈ ``1.1226·R²``。
    （注意别顺手写成 ``2.5·R²·sin72°`` —— 那是把星当成五个三角形算的，会偏大一倍多。）
    抗锯齿会让边界像素变成半黄，总量略少于理论值。
    """
    def star_area(r, k=INNER_RATIO, points=5):
        return points * k * r * r * math.sin(math.radians(180.0 / points))

    theory = star_area(OUTER) + 4 * star_area(SMALL_OUTER)
    r, g, b = flag[..., 0], flag[..., 1], flag[..., 2]
    got = int(((r > 200) & (g > 170) & (b < 90)).sum())
    assert abs(got - theory) / theory < 0.05, \
        f"黄星面积 {got} 与理论 {theory:.0f} 相差 {abs(got - theory) / theory:.1%}"


def test_non_three_two_canvas_centers_flag_without_deforming_stars():
    """画布比例不是 3:2 时，旗面应居中保持 3:2，星不得被拉伸。"""
    size = 800
    sq = render({"pattern": "flag_cn", "size": [size, size]}).to_rgba8()
    fw = float(size)
    fh = fw / 1.5
    ox, oy = (size - fw) / 2.0, (size - fh) / 2.0
    u = fw / 30.0

    assert not _is_red(sq[5, 5]), "正方形画布上下应留白，不应整幅铺红"
    assert _is_red(sq[int(oy + fh / 2), int(ox + fw / 2)]), "旗面中心区域应为红"

    bx, by = ox + 5 * u, oy + 5 * u
    up = _ray_extent(sq, bx, by, -90.0, 3 * u * 1.4)
    right = _ray_extent(sq, bx, by, -18.0, 3 * u * 1.4)
    assert abs(up - 3 * u) <= TOL_TIP
    assert abs(right - 3 * u) <= TOL_TIP
    assert abs(up - right) <= 2.5, "横竖两个方向半径应一致（证明星没被拉伸）"
