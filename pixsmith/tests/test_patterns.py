"""配方层测试：每个图案都能渲染、参数可绑定、结果可复现、错误能被拦住。"""

from __future__ import annotations

import numpy as np
import pytest

from pixsmith.patterns import REGISTRY, by_category, describe, get, names
from pixsmith.patterns._util import fit_size
from pixsmith.recipes import (DEFAULT_SIZE, list_patterns, make_recipe, render,
                              render_file, to_json)

SMALL = (120, 80)
ALL_KEYS = names()


def test_registry_is_populated_and_unique():
    assert len(ALL_KEYS) >= 18, "图案数量偏少，可能某个模块没被导入"
    assert len(set(ALL_KEYS)) == len(ALL_KEYS)
    cats = by_category()
    assert set(cats) >= {"background", "texture", "shape", "festive"}
    for key in ALL_KEYS:
        assert get(key).summary, f"{key} 缺 summary（CLI list 会显示空）"


@pytest.mark.parametrize("key", ALL_KEYS)
def test_every_pattern_renders_with_defaults(key):
    """默认参数必须能跑通 —— 这是 `pixsmith render <图案名>` 的底线。"""
    c = render({"pattern": key, "size": list(SMALL)})
    assert c.size == SMALL
    arr = c.to_rgba8()
    assert arr.shape == (SMALL[1], SMALL[0], 4)
    assert arr.dtype == np.uint8


@pytest.mark.parametrize("key", ALL_KEYS)
def test_every_pattern_is_deterministic(key):
    """同参数同输出 —— 「可复现」是这块东西存在的理由，必须逐个图案验证。"""
    a = render({"pattern": key, "size": list(SMALL)}).to_png()
    b = render({"pattern": key, "size": list(SMALL)}).to_png()
    assert a == b, f"{key} 两次渲染字节不一致"


@pytest.mark.parametrize("key", ALL_KEYS)
def test_every_pattern_shows_something(key):
    """不能整幅全透明 —— 那多半是参数没接上或画到画布外了。"""
    arr = render({"pattern": key, "size": list(SMALL)}).to_rgba8()
    assert (arr[..., 3] > 0).mean() > 0.01, f"{key} 渲染结果几乎全透明"


@pytest.mark.parametrize("key", ALL_KEYS)
def test_describe_covers_every_param(key):
    text = describe(key)
    assert key in text
    for spec in get(key).params:
        assert spec.name in text
        if spec.type == "color" and spec.default is not None:
            assert spec.doc, f"{key}.{spec.name} 是颜色参数但没有说明"


def test_seed_changes_output_but_same_seed_reproduces():
    a = render({"pattern": "starfield", "size": list(SMALL),
                "params": {"seed": 1}}).to_png()
    b = render({"pattern": "starfield", "size": list(SMALL),
                "params": {"seed": 2}}).to_png()
    c = render({"pattern": "starfield", "size": list(SMALL),
                "params": {"seed": 1}}).to_png()
    assert a != b, "换 seed 应改变输出"
    assert a == c, "同 seed 应可复现"


def test_unknown_pattern_and_param_are_rejected():
    with pytest.raises(KeyError):
        render({"pattern": "no_such_pattern", "size": [10, 10]})
    with pytest.raises(KeyError):
        render({"pattern": "gradient", "size": [10, 10],
                "params": {"not_a_param": 1}})


def test_recipe_top_level_keys_are_validated():
    with pytest.raises(KeyError):
        render({"pattern": "gradient", "typo_key": 1})


def test_empty_scene_is_legal_and_gives_a_blank_canvas():
    """空场景是**合法**的：`{size + background}` 就是"给我一张纯色底"。

    （旧版把"没有 pattern"当错误 —— 那是把"配方"当成了唯一形态。
    有了场景之后，只铺底色是正当需求，不该报错。）
    """
    c = render({"size": [12, 8], "background": "#336699"})
    arr = c.to_rgba8()
    assert tuple(arr[0, 0]) == (0x33, 0x66, 0x99, 255)
    blank = render({"size": [12, 8]})
    assert (blank.to_rgba8()[..., 3] == 0).all(), "无底色则应为全透明"


@pytest.mark.parametrize("raw,expected", [
    ("1920x1080", (1920, 1080)),
    ("800*600", (800, 600)),
    ([640, 480], (640, 480)),
    ((100, 200), (100, 200)),
])
def test_fit_size_accepts_common_forms(raw, expected):
    assert fit_size(raw) == expected


def test_fit_size_rejects_garbage():
    with pytest.raises(ValueError):
        fit_size("1920")
    with pytest.raises((ValueError, TypeError)):
        fit_size(42)


def test_make_recipe_omits_defaults_for_readability():
    rec = make_recipe("gradient", size=(800, 600))
    assert rec["pattern"] == "gradient"
    assert rec["size"] == [800, 600]
    assert "params" not in rec, "全默认时不该写出 params，配方越短越好"

    rec2 = make_recipe("gradient", size=(800, 600), end="#FF0000")
    assert rec2["params"] == {"end": "#FF0000"}


def test_recipe_json_roundtrip(tmp_path):
    rec = make_recipe("star", size=(64, 64), color="#FF0000", points=6)
    p = tmp_path / "r.json"
    p.write_text(to_json(rec), encoding="utf-8")
    out, c = render_file(p, tmp_path / "out.png")
    assert c.size == (64, 64)
    assert (tmp_path / "out.png").exists()
    assert str(tmp_path / "out.png") in out


def test_list_patterns_shape():
    got = list_patterns()
    assert isinstance(got, dict)
    assert sum(len(v) for v in got.values()) == len(REGISTRY)


def test_background_param_of_recipe_prepaints_canvas():
    """配方级 background 会先铺底，图案再叠上去。"""
    a = render({"pattern": "star", "size": list(SMALL),
                "params": {"radius": 10}}).to_rgba8()
    b = render({"pattern": "star", "size": list(SMALL),
                "background": "#003366",
                "params": {"radius": 10}}).to_rgba8()
    assert a[0, 0, 3] == 0, "不指定 background 时角落应透明"
    assert tuple(b[0, 0]) == (0, 51, 102, 255)


def test_render_rejects_bad_size_type():
    with pytest.raises((ValueError, TypeError)):
        render({"pattern": "gradient", "size": "abc"})
