"""仿射变换（`transform`）测试。

分三层钉，因为这三层各自的失败方式完全不同：

1. **几何**（`geometry.affine_matrix`）—— 参数 → 矩阵。矩阵是最容易"看着对"的东西，
   所以这里全部**手算核对**，不拿实现跟自己比。
2. **位图重采样** —— 三条硬要求：恒等时**一个像素都不动**、越界**置透明而非夹取边缘**
   （夹取会把旋转后四角拉成长条）、**预乘 alpha**（不预乘旋转后的边缘会泛黑边）。
   这三条任缺一条，图都"能出来"但不对 —— 正是本项目最不想容忍的那种失败。
3. **双后端一致** —— 同一条 `transform`，矢量端写 `matrix(…)`、位图端做重采样，
   **必须共用 `geometry.affine_matrix` 那一份数字**。所以断言方式是把 SVG 里那个矩阵
   抠出来，与位图端实测的像素位移对到同一个解析解上。
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from pixsmith.canvas import Canvas
from pixsmith.geometry import (affine_apply, affine_invert, affine_is_identity,
                               affine_matrix, affine_mul)
from pixsmith.scene import Scene
from pixsmith.svg import SvgBackend


def _centroid(rgba: np.ndarray, *, thr: int = 128) -> tuple[float, float]:
    """不透明区域的重心，换算到**连续坐标**（像素 i 的中心在 i + 0.5）。"""
    ys, xs = np.nonzero(rgba[..., 3] > thr)
    assert xs.size, "图里没有任何不透明像素"
    return float(xs.mean()) + 0.5, float(ys.mean()) + 0.5


def _svg_matrix(svg: str) -> tuple[float, ...]:
    m = re.search(r'transform="matrix\(([^)]*)\)"', svg)
    assert m, f"SVG 里没有 matrix(...)：\n{svg[:400]}"
    return tuple(float(v) for v in m.group(1).split())


# ============================================================ 1. 几何
def test_identity_by_default():
    assert affine_is_identity(affine_matrix(size=(100, 100)))
    assert affine_is_identity(affine_matrix(size=(37, 11), rotate=0, scale=1,
                                            flip="none"))


def test_rotate_90_about_center_is_clockwise_on_screen():
    """正角 = 屏幕上顺时针（与 `polar` 的 0°向右 / 90°向下 同一套直觉）。"""
    m = affine_matrix(size=(100, 100), rotate=90)
    # 中心右侧 → 中心下方
    assert np.allclose(affine_apply(m, 75.0, 50.0), (50.0, 75.0), atol=1e-9)
    # 中心上方 → 中心右侧
    assert np.allclose(affine_apply(m, 50.0, 25.0), (75.0, 50.0), atol=1e-9)
    # 画布中心是不动点
    assert np.allclose(affine_apply(m, 50.0, 50.0), (50.0, 50.0), atol=1e-9)


def test_pivot_defaults_to_center_and_can_be_overridden():
    center = affine_matrix(size=(100, 100), rotate=180)
    assert np.allclose(affine_apply(center, 75.0, 50.0), (25.0, 50.0), atol=1e-9)
    # 换支点到 (25, 50) 后，(25,50) 自己变成不动点
    off = affine_matrix(size=(100, 100), rotate=180, pivot=[25, 50])
    assert np.allclose(affine_apply(off, 25.0, 50.0), (25.0, 50.0), atol=1e-9)
    assert np.allclose(affine_apply(off, 75.0, 50.0), (-25.0, 50.0), atol=1e-9)


def test_scale_and_flip_are_about_the_center():
    big = affine_matrix(size=(100, 100), scale=2.0)
    assert np.allclose(affine_apply(big, 75.0, 50.0), (100.0, 50.0), atol=1e-9)

    h = affine_matrix(size=(100, 100), flip="h")
    assert np.allclose(affine_apply(h, 75.0, 50.0), (25.0, 50.0), atol=1e-9)
    assert np.allclose(affine_apply(h, 25.0, 20.0), (75.0, 20.0), atol=1e-9)

    v = affine_matrix(size=(100, 100), flip="v")
    assert np.allclose(affine_apply(v, 75.0, 20.0), (75.0, 80.0), atol=1e-9)

    both = affine_matrix(size=(100, 100), flip="both")
    assert np.allclose(affine_apply(both, 75.0, 20.0), (25.0, 80.0), atol=1e-9)


def test_crop_maps_the_region_onto_the_whole_canvas():
    """取景区 [50,10,100,80] → 200×100 画布：该区四角正好落到画布四角。"""
    m = affine_matrix(size=(200, 100), crop=[50, 10, 100, 80])
    assert np.allclose(affine_apply(m, 50.0, 10.0), (0.0, 0.0), atol=1e-9)
    assert np.allclose(affine_apply(m, 150.0, 90.0), (200.0, 100.0), atol=1e-9)
    # 取景比例 ≠ 画布比例 → 天然非等比拉伸（这就是"非等比请走 crop"的含义）
    assert np.allclose(affine_apply(m, 100.0, 50.0), (100.0, 50.0), atol=1e-9)


def test_translate_is_a_plain_canvas_space_offset():
    m = affine_matrix(size=(100, 100), translate=[10, -5])
    assert np.allclose(affine_apply(m, 50.0, 50.0), (60.0, 45.0), atol=1e-9)


def test_invert_round_trips_and_composition_order_is_right():
    m = affine_matrix(size=(200, 100), rotate=37, scale=1.7, translate=[13, -4],
                      pivot=[80, 30], flip="h", crop=[20, 5, 90, 60])
    inv = affine_invert(m)
    p = (123.0, 41.0)
    assert np.allclose(affine_apply(inv, *affine_apply(m, *p)), p, atol=1e-6)
    # m ∘ n = 先 n 后 m。注意 `scale` 绕**中心**，所以拿中心点当测试点等于没测 ——
    # 中心是缩放的不动点，两种顺序都会得到同一个值。
    t = affine_matrix(size=(100, 100), translate=[10, 0])
    s = affine_matrix(size=(100, 100), scale=2.0)
    assert np.allclose(affine_apply(affine_mul(t, s), 60.0, 50.0),
                       (80.0, 50.0), atol=1e-9)      # 先放大 60→70，再 +10
    assert np.allclose(affine_apply(affine_mul(s, t), 60.0, 50.0),
                       (90.0, 50.0), atol=1e-9)      # 先 +10 到 70，再放大到 90


@pytest.mark.parametrize("kwargs, needle", [
    ({"scale": 0}, "scale"),
    ({"scale": -1}, "flip"),
    ({"flip": "diag"}, "flip"),
    ({"crop": [0, 0, 0, 10]}, "宽高"),
    ({"crop": [0, 0, 10, -1]}, "宽高"),
])
def test_bad_params_are_rejected_with_actionable_messages(kwargs, needle):
    """不静默兜底：scale=0 会把整幅图算成空白，flip 写错会静默不翻 —— 都得报。"""
    with pytest.raises(ValueError, match=needle):
        affine_matrix(size=(10, 10), **kwargs)


def test_singular_matrix_is_reported_not_returned():
    with pytest.raises(ValueError, match="不可逆"):
        affine_invert((0.0, 0.0, 0.0, 0.0, 0.0, 0.0))


# ============================================================ 2. 位图重采样
def test_identity_transform_does_not_touch_a_single_pixel():
    """全默认参数时**直接返回**，不白跑一轮重采样 —— 预乘再反预乘是有浮点损耗的。"""
    c = Canvas(40, 30, "#0A1730")
    c.disc(10.5, 12.5, 6, "#F2C14E")
    before = c.to_rgba8().copy()
    c.transform()
    assert np.array_equal(c.to_rgba8(), before)


def test_flip_h_mirrors_the_buffer():
    c = Canvas(40, 30, "#0A1730")
    c.rect(2, 3, 9, 7, "#C8102E")
    c.disc(30.5, 20.5, 5, "#F2C14E")
    before = c.to_rgba8().copy()
    after = c.transform(flip="h").to_rgba8()
    assert np.abs(before[:, ::-1].astype(int) - after.astype(int)).max() <= 1


def test_rotation_moves_content_clockwise_by_90():
    c = Canvas(100, 100)
    c.disc(25, 50, 8, "#FFFFFF")
    assert _centroid(c.to_rgba8())[0] == pytest.approx(25.0, abs=1.0)
    cx, cy = _centroid(c.transform(rotate=90).to_rgba8())
    assert (cx, cy) == pytest.approx((50.0, 25.0), abs=1.5)


def test_out_of_canvas_becomes_transparent_instead_of_smearing_edges():
    """**不夹取边缘** —— 夹取会把旋转后露出的四角拉成长条拖影。

    整幅不透明的画布转 45° 后，四角必然取样到画布外：正确行为是**透明**。
    夹取的话四角会是不透明的边缘色，看上去像拖影。
    """
    c = Canvas(80, 80, "#C8102E").transform(rotate=45)
    arr = c.to_rgba8()
    for y, x in ((0, 0), (0, 79), (79, 0), (79, 79)):
        assert arr[y, x, 3] == 0, f"({x},{y}) 应当是透明的（越界），却被填了色"
    assert arr[40, 40, 3] == 255, "画布中心必须还是实心的"
    # 转 45° 后内容是个菱形，它与轴对齐正方形视口的交集 = 6400 − 4×(23.43²/2) ≈ 5302，
    # 即露出约 17.3% 的透明角。给个宽松下界即可（真正的判据是上面四个角）
    assert (arr[..., 3] == 0).mean() > 0.15


def test_rotation_does_not_bleed_a_dark_halo():
    """**预乘 alpha** —— 不预乘的话，透明像素的 RGB(0,0,0) 会被插值混进来，边缘泛黑边。

    这和 `blur` 踩过的是同一个坑，所以留着同一类回归测试。
    """
    c = Canvas(120, 120)
    c.disc(60, 60, 30, "#FFFFFF", feather=3.0)
    c.transform(rotate=23)
    arr = c.to_rgba8()
    soft = arr[..., 3] > 80                       # 只看"有内容"的像素（含半透明边）
    assert soft.any()
    assert arr[..., :3][soft].min() >= 240, \
        "半透明边缘的 RGB 被拉暗了 —— 多半是重采样前忘了预乘 alpha"


def test_scale_up_keeps_the_canvas_size_and_clips():
    """缩放不改画布尺寸：放大 2 倍后内容溢出被裁掉，溢出的部分**不产生新画布**。"""
    c = Canvas(60, 60, "#0A1730")
    c.transform(scale=2.0)
    assert c.size == (60, 60)
    assert c.to_rgba8()[..., 3].min() == 255      # 满幅底色放大后仍然满幅


# ============================================================ 3. 双后端一致
def test_both_backends_share_one_matrix():
    """矢量端的 `matrix(…)` 与位图端实测的像素位移，必须落在同一个解析解上。

    这是"两个后端共用 `geometry.affine_matrix`"的直接检验：
    谁要是自己又写了一遍三角函数、或者把旋转方向搞反了，这里就会炸。
    """
    scene = {"dsl": 1, "size": [100, 100],
             "ops": [{"op": "disc", "cx": 50, "cy": 20, "r": 5, "color": "#FFFFFF"}],
             "transform": {"rotate": 37}}
    m = affine_matrix(size=(100, 100), rotate=37)
    expect = affine_apply(m, 50.0, 20.0)

    # 矢量端：SVG 里那个矩阵本身
    svg = Scene.from_dict(scene).render(SvgBackend(100, 100)).to_svg()
    assert np.allclose(_svg_matrix(svg), m, atol=1e-3)      # SVG 里只保留 3 位小数

    # 位图端：内容重心确实搬到了同一个地方
    got = _centroid(Scene.from_dict(scene).render().to_rgba8())
    assert got == pytest.approx(expect, abs=1.5)


def test_svg_identity_transform_emits_no_group():
    """恒等变换不该在 SVG 里多包一层 `<g>` —— 白占体积。"""
    c = SvgBackend(50, 50)
    c.rect(0, 0, 10, 10, "#FFFFFF")
    before = c.to_svg()
    c.transform()
    assert c.to_svg() == before


def test_scene_transform_applies_to_the_composited_result_not_per_layer():
    """场景级 transform 是**整幅成品**的姿态 —— 必须在全部图层合成之后套用。

    用 `screen` 混合让"逐层变换"和"合成后变换"能区分开：
    若实现是逐层套用，混合结果会不一样（旋转把图层挪到别处，混合的区域就变了）。
    """
    d = {"dsl": 1, "size": [64, 64], "layers": [
        [{"op": "disc", "cx": 20, "cy": 32, "r": 12, "color": "#FF0000"}],
        {"blend": "screen",
         "ops": [{"op": "rect", "x": 40, "y": 20, "w": 18, "h": 24,
                  "color": "#00FF00"}]}]}
    via_field = Scene.from_dict({**d, "transform": {"rotate": 90}}).render().to_rgba8()
    via_manual = Scene.from_dict(d).render().transform(rotate=90).to_rgba8()
    assert np.abs(via_field.astype(int) - via_manual.astype(int)).max() <= 1


def test_transform_op_inside_a_layer_only_affects_that_layer():
    """图层里的 `transform` 只作用于**那一层已绘内容** —— 另一层不受影响。

    这正是"场景级字段 + 图层 op"两个位置都要存在的理由：一个管整幅，一个管一段。
    """
    d = {"dsl": 1, "size": [100, 100], "layers": [
        [{"op": "disc", "cx": 25, "cy": 50, "r": 9, "color": "#FF0000"}],
        [{"op": "disc", "cx": 75, "cy": 50, "r": 9, "color": "#00FF00"},
         {"op": "transform", "rotate": 90}]],
    }
    arr = Scene.from_dict(d).render().to_rgba8()

    def opaque(x, y):
        return arr[y, x, 3] > 200

    assert opaque(25, 50), "第一层没被第二层的 transform 波及"
    # 第二层的圆心 (75,50) 绕中心**顺时针**转 90° → 落到中心正下方 (50,75)
    assert not opaque(75, 50), "第二层的变换没生效（还是原来那个位置）"
    assert opaque(50, 75) or opaque(50, 74), "第二层应当搬到 (50,75) 附近"


# ============================================================ 4. 场景字段的校验与往返
def test_scene_transform_is_validated_at_construction_time():
    """构造时就炸，不等渲染 —— 与 `Layer.__post_init__` 里的 `check_verbs` 同一理由。"""
    with pytest.raises(KeyError, match="不认识参数"):
        Scene.from_dict({"dsl": 1, "size": [10, 10], "transform": {"rotate": 1,
                                                                  "zzz": 2}})
    with pytest.raises(TypeError, match="必须是对象"):
        Scene.from_dict({"dsl": 1, "size": [10, 10], "transform": 5})


def test_scene_transform_round_trips_without_filling_defaults():
    """`to_dict()` 要忠实往返 —— 不能被 `bind()` 归一化成一堆默认值。"""
    d = {"dsl": 1, "size": [10, 10], "background": "#000000",
         "ops": [{"op": "fill", "color": "#123456"}],
         "transform": {"rotate": 30}}
    back = Scene.from_dict(d).to_dict()
    assert back["transform"] == {"rotate": 30}
    # compact 形态（单层无混合 → 摊平成 ops）也不能把 transform 漏掉
    assert Scene.from_dict(d).to_dict(compact=True)["transform"] == {"rotate": 30}
    assert Scene.from_dict(back).to_dict() == back


def test_scene_transform_applies_to_the_simple_single_layer_path_too():
    """单层快路径（直接画在主后端上）也必须套 transform —— 两条路径行为要一致。"""
    single = {"dsl": 1, "size": [60, 60],
              "ops": [{"op": "disc", "cx": 15, "cy": 30, "r": 8, "color": "#FFFFFF"}]}
    laid = {"dsl": 1, "size": [60, 60],
            "layers": [{"ops": single["ops"]}]}          # 强制走多层路径
    a = Scene.from_dict({**single, "transform": {"rotate": 90,
                                                "pivot": [30, 30]}}).render().to_rgba8()
    b = Scene.from_dict({**laid, "transform": {"rotate": 90,
                                               "pivot": [30, 30]}}).render().to_rgba8()
    assert np.array_equal(a, b)
    assert _centroid(a) == pytest.approx((30.0, 15.0), abs=1.5)
