"""双后端契约测试 —— 整个架构最重要的不变式。

> **每个图案，要么能在矢量后端跑通，要么显式声明它需要什么位图专属能力。**

这条不变式为什么值钱：它把"双后端"从一句口号变成了**可执行的约束**。
以后任何人加图案，只要偷偷用了 `paint()`（逐像素场）而不声明，
这个测试立刻失败 —— 而不是等到某天用户选 SVG 输出时才发现少了一半效果。

另外还覆盖：SVG 产物是合法 XML、场景 JSON 往返、图层混合在两端都生效、
不支持的能力**报错而不是静默降级**。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np
import pytest

from pixsmith.backend import UnsupportedOperation, backend_capabilities
from pixsmith.canvas import Canvas
from pixsmith.patterns import get, names
from pixsmith.scene import Scene
from pixsmith.svg import SvgBackend

SVG_SIZE = (96, 72)
#: SVG 里真正的"绘制元素"（只有 <svg>/<defs> 不算画了东西）
DRAW_TAGS = ("<rect", "<circle", "<ellipse", "<line", "<path", "<polygon",
             "<polyline")


# ---------------------------------------------------------------- 核心契约
@pytest.mark.parametrize("key", names())
def test_pattern_is_dual_backend_or_declares_why_not(key):
    """契约：跑得通 ↔ 没声明需要位图能力；跑不通 ↔ 有声明。两边必须一致。"""
    spec = get(key)
    svg = SvgBackend(*SVG_SIZE)
    try:
        spec.fn(svg, **spec.bind({}))
    except (AttributeError, UnsupportedOperation) as exc:
        assert spec.requires, (
            f"图案 {key!r} 在矢量后端失败（{type(exc).__name__}: {exc}），"
            f"但没有声明 requires —— 请补上，例如 requires=(\"paint\",)")
    else:
        assert not spec.requires, (
            f"图案 {key!r} 其实能在矢量后端跑通，却声明了 requires={spec.requires}"
            f" —— 声明过严会把本可用的图案挡在门外。"
            f"若依赖是参数相关的，请改用 requires_fn。")
        xml = svg.to_svg()
        assert any(t in xml for t in DRAW_TAGS), f"{key} 在矢量后端没画出任何元素"


def test_every_pattern_still_renders_on_raster():
    """位图后端必须**全部**支持 —— 它是基准后端。"""
    for key in names():
        c = Canvas(*SVG_SIZE)
        get(key).fn(c, **get(key).bind({}))
        assert (c.to_rgba8()[..., 3] > 0).any(), f"{key} 在位图后端没画出东西"


def test_raster_only_patterns_are_the_expected_ones():
    """把"哪些只能位图"钉下来。数量变了就该有人来解释一句为什么。"""
    raster_only = {k for k in names() if get(k).requires}
    assert raster_only == {"stripes", "checker", "noise", "vignette",
                           "marble", "clouds", "cracks", "brushed"}, \
        f"位图专属图案集合变了：{sorted(raster_only)}"


def test_parameter_dependent_requirement_is_enforced_at_render():
    """`starfield` 默认参数双后端通用，但开了银河带就需要位图能力 ——

    这类"参数相关依赖"由 `requires_fn` 声明，在**渲染前**被拦下。
    """
    ok = Scene.from_dict({"dsl": 1, "size": [64, 64],
                          "ops": [{"op": "pattern", "pattern": "starfield"}]})
    assert ok.requires() == set()
    ok.render(SvgBackend(64, 64))            # 不该抛

    needs_paint = Scene.from_dict({
        "dsl": 1, "size": [64, 64],
        "ops": [{"op": "pattern", "pattern": "starfield",
                 "params": {"milky": 0.2}}]})
    assert "paint" in needs_paint.requires()
    with pytest.raises(UnsupportedOperation, match="paint"):
        needs_paint.render(SvgBackend(64, 64))


# ---------------------------------------------------------------- SVG 合法性
def test_svg_output_is_well_formed_xml():
    svg = SvgBackend(200, 100)
    svg.fill("#0A1730")
    svg.linear_gradient("#0A1730", "#C8102E", 45)
    svg.rect(10, 10, 80, 40, "#FFFFFF80", radius=8)
    svg.disc(150, 50, 20, "#F2C14E")
    svg.star(60, 80, 18, 5, "#FFE9AF")
    svg.blur(6)
    root = ET.fromstring(svg.to_svg())
    assert root.tag.endswith("svg")
    assert root.get("viewBox") == "0 0 200 100"


def test_svg_has_no_numpy_repr_leakage():
    """数字必须被格式化过 —— 直接把 numpy 值插进字符串会写出 `np.float32(3.0)`。"""
    svg = SvgBackend(50, 50)
    svg.disc(np.float32(25.0), np.float32(25.0), np.float32(10.0), "#FFF")
    svg.rect(np.float64(1.5), 2.25, 10.0, 10.0, "#000")
    text = svg.to_svg()
    assert "np." not in text and "float32" not in text


def test_svg_save_rejects_png_extension(tmp_path):
    svg = SvgBackend(20, 20)
    with pytest.raises(ValueError, match="只能写 .svg"):
        svg.save(tmp_path / "a.png")
    assert svg.save(tmp_path / "a.svg").endswith("a.svg")


def test_svg_erase_disc_emits_a_mask():
    svg = SvgBackend(60, 60)
    svg.disc(30, 30, 25, "#F2C14E")
    svg.erase_disc(30, 30, 12)
    text = svg.to_svg()
    assert "<mask" in text and 'fill="black"' in text and 'mask="url(#' in text


# ---------------------------------------------------------------- 能力校验
def test_capabilities_are_declared_not_inferred():
    assert "paint" in backend_capabilities(Canvas(4, 4))
    assert "paint" not in backend_capabilities(SvgBackend(4, 4))


def test_unsupported_op_raises_with_actionable_message():
    """静默降级是最坏的失败模式（agent 看不见图）—— 必须报错。"""
    scene = Scene.from_dict({"dsl": 1, "size": [40, 40],
                             "ops": [{"op": "grain", "amount": 0.2}]})
    with pytest.raises(UnsupportedOperation) as ei:
        scene.render(SvgBackend(40, 40))
    msg = str(ei.value)
    assert "grain" in msg and "位图后端" in msg


def test_paint_dependent_pattern_is_blocked_on_svg():
    scene = Scene.from_dict({"dsl": 1, "size": [40, 40],
                             "ops": [{"op": "pattern", "pattern": "noise"}]})
    with pytest.raises(UnsupportedOperation, match="paint"):
        scene.render(SvgBackend(40, 40))
    scene.render()          # 位图后端应当照常通过


# ---------------------------------------------------------------- 场景
def test_scene_json_roundtrip_preserves_structure():
    src = {
        "dsl": 1, "size": [320, 180], "background": "#101820",
        "layers": [
            [{"op": "linear_gradient", "begin": "#101820", "end": "#C8102E"}],
            {"blend": "multiply", "opacity": 0.5,
             "ops": [{"op": "pattern", "pattern": "flag_cn"}]},
        ],
    }
    scene = Scene.from_dict(src)
    again = Scene.from_dict(Scene.from_json(scene.to_json()).to_dict())
    assert again.size == scene.size
    assert again.background == scene.background
    assert len(again.layers) == 2
    assert again.layers[1].blend == "multiply"
    assert again.layers[1].opacity == 0.5
    assert again.all_ops() == scene.all_ops()


def test_scene_sugar_forms_are_equivalent():
    a = Scene.from_dict({"dsl": 1, "size": [64, 64],
                         "ops": [{"op": "fill", "color": "#123456"}]})
    b = Scene.from_dict({"dsl": 1, "size": [64, 64],
                         "layers": [[{"op": "fill", "color": "#123456"}]]})
    c = Scene.from_dict({"dsl": 1, "size": [64, 64],
                         "layers": [{"ops": [{"op": "fill", "color": "#123456"}]}]})
    for s in (a, b, c):
        assert len(s.layers) == 1 and s.layers[0].blend == "normal"
    assert a.to_json() == b.to_json() == c.to_json()


def test_scene_accepts_aspect_and_old_recipe_shape():
    s = Scene.from_dict({"dsl": 1, "aspect": "16:9", "ops": []})
    assert s.size == (1920, 1080)
    # 旧配方形态（pattern + params）必须继续可用
    old = Scene.from_dict({"pattern": "gradient", "size": [80, 60],
                           "params": {"end": "#FF0000"}})
    assert old.all_ops()[0]["pattern"] == "gradient"
    assert old.all_ops()[0]["params"] == {"end": "#FF0000"}


def test_scene_rejects_bad_input():
    with pytest.raises(KeyError):
        Scene.from_dict({"dsl": 1, "size": [10, 10], "typo": 1})
    with pytest.raises(KeyError):
        Scene.from_dict({"dsl": 1, "size": [10, 10], "ops": [{"op": "nope"}]})
    with pytest.raises(KeyError):
        Scene.from_dict({"dsl": 1, "size": [10, 10],
                         "layers": [{"ops": [], "typo": 1}]})
    with pytest.raises(ValueError):
        Scene.from_dict({"dsl": 99, "size": [10, 10]})
    with pytest.raises(KeyError):
        Scene.from_dict({"dsl": 1})


def test_scene_rejects_size_mismatch_with_backend():
    scene = Scene.from_dict({"dsl": 1, "size": [40, 40], "ops": []})
    with pytest.raises(ValueError, match="尺寸"):
        scene.render(Canvas(50, 50))


def test_layer_blend_and_opacity_take_effect_on_raster():
    base = Scene.from_dict({"dsl": 1, "size": [32, 32], "background": "#808080",
                            "ops": [{"op": "fill", "color": "#808080"}]})
    plain = base.render().to_rgba8()[0, 0, :3].astype(int)

    multi = Scene.from_dict({
        "dsl": 1, "size": [32, 32], "background": "#808080",
        "layers": [
            {"ops": [{"op": "fill", "color": "#808080"}]},
            {"blend": "multiply", "opacity": 0.5,
             "ops": [{"op": "fill", "color": "#808080"}]},
        ]})
    blended = multi.render().to_rgba8()[0, 0, :3].astype(int)
    assert not np.array_equal(plain, blended), "混合模式应当改变结果"
    assert all(0 <= v <= 255 for v in blended)


def test_layer_blend_reaches_svg():
    scene = Scene.from_dict({
        "dsl": 1, "size": [40, 40],
        "layers": [
            {"ops": [{"op": "fill", "color": "#102030"}]},
            {"blend": "multiply", "opacity": 0.4,
             "ops": [{"op": "fill", "color": "#C8102E"}]},
        ]})
    text = scene.render(SvgBackend(40, 40)).to_svg()
    assert "mix-blend-mode:multiply" in text and "opacity:0.4" in text


# ---------------------------------------------------------------- report
def test_report_describes_what_was_drawn():
    scene = Scene.from_dict({
        "dsl": 1, "size": [80, 60], "background": "#0A1730",
        "ops": [{"op": "disc", "cx": 40, "cy": 30, "r": 15, "color": "#F2C14E"}]})
    rep = scene.report()
    assert rep["size"] == [80, 60]
    assert rep["opaque_ratio"] > 0.9           # 有底色，应当几乎全不透明
    assert rep["fully_transparent"] is False
    assert rep["content_bbox"] == [0, 0, 79, 59]
    assert rep["touches_edge"] is True
    assert rep["dominant_colors"], "应当能报出主色"
    assert any(c.startswith("#") for c in rep["dominant_colors"])
    assert rep["ops"] == 1 and rep["layers"] == 1


def test_report_flags_fully_transparent_scene():
    """agent 的"眼睛"：全透明 = 一定画错了，得能被自动发现。"""
    scene = Scene.from_dict({"dsl": 1, "size": [20, 20],
                             "ops": [{"op": "erase_disc", "cx": 0, "cy": 0, "r": 0.1}]})
    rep = scene.report()
    assert rep["fully_transparent"] is True
    assert rep["opaque_ratio"] == 0.0
    assert rep["hints"], "全透明必须给出提示"


# ---------------------------------------------------------------- report 探针
def _rep(ops, size=(320, 320)):
    return Scene.from_dict({"dsl": 1, "size": list(size), "ops": ops}).report()


def test_report_gives_probes_that_answer_did_my_params_work():
    """``channel_range`` 与 ``corner_colors`` 是直接回答"参数生效没"的探针。

    起因：对角渐变的 ``dominant_colors`` 全是中间调（面积最多），中国红一个都进不去，
    看起来像参数传错了 —— 而渐变其实完全正确。所以必须另给两个探针。
    """
    rep = _rep([{"op": "linear_gradient", "begin": "#0A1730", "end": "#C8102E",
                 "angle": 118}])
    r_lo, r_hi = rep["channel_range"]["r"]
    assert r_lo < 30 and r_hi > 180, f"红通道应有跨度，实际 {r_lo}→{r_hi}"
    corners = rep["corner_colors"]
    assert set(corners) == {"tl", "tr", "bl", "br"}
    # 118° 的起点在左下 → 那一角应当最红
    assert corners["bl"].startswith("#C"), corners
    assert corners["tr"].startswith("#0"), corners


def test_report_hints_fire_on_gradient_but_not_on_flat_colors():
    """主色覆盖率的判别线是**实测标定**的（0.25），不是拍脑袋 —— 这里把它钉住。

    标定数据（320×320 实测）：
      纯色 100% · 纯色+图形 98.7% · 条纹 50.3% · 棋盘 50.5% · 星空 90.5%  → 有主色
      渐变 118° 12.9% · 渐变 90° 8.4% · 三色渐变 18.4% · 大理石 19.2%      → 没有主色
    """
    for ops, coverage_min in (
        ([{"op": "fill", "color": "#C8102E"}], 0.9),
        ([{"op": "pattern", "pattern": "stripes"}], 0.4),
        ([{"op": "pattern", "pattern": "starfield"}], 0.5),
    ):
        rep = _rep(ops)
        assert rep["dominant_coverage"] >= coverage_min, rep["dominant_coverage"]
        assert "hints" not in rep, f"{ops[0]} 有主色，不该给主色提示：{rep.get('hints')}"

    for ops in (
        [{"op": "linear_gradient", "begin": "#0A1730", "end": "#C8102E", "angle": 118}],
        [{"op": "linear_gradient", "begin": "#0A1730", "end": "#C8102E", "angle": 90}],
        [{"op": "pattern", "pattern": "marble"}],
    ):
        rep = _rep(ops)
        assert rep["dominant_coverage"] < 0.25, rep["dominant_coverage"]
        assert rep["hints"], f"{ops[0]} 应给出提示"
        joined = " ".join(rep["hints"])
        assert "channel_range" in joined and "corner_colors" in joined


def test_report_hints_on_almost_empty_canvas():
    """内容几乎全是透明 → 大概率画到画布外了，也要提示。"""
    rep = _rep([{"op": "disc", "cx": -200, "cy": -200, "r": 30, "color": "#FFF"}],
               size=(200, 200))
    assert rep["opaque_ratio"] < 0.05
    assert any("画布外" in h for h in rep.get("hints", [])), rep.get("hints")


def test_report_keeps_machine_readable_shape():
    """提示是附加信息，不能破坏原有字段的稳定性。"""
    rep = _rep([{"op": "fill", "color": "#123456"}])
    for key in ("size", "layers", "ops", "requires", "opaque_ratio",
                "fully_transparent", "transparent_ratio", "content_bbox",
                "touches_edge", "mean_luma", "contrast", "dominant_colors",
                "dominant_coverage", "channel_range", "corner_colors"):
        assert key in rep, f"缺少字段 {key}"
    assert rep["dominant_coverage"] == 1.0
    assert rep["fully_transparent"] is False
