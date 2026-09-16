"""CLI 测试：子命令能跑通、参数能生效、错误有清晰提示。"""

from __future__ import annotations

import json

import pytest

from pixsmith.cli import main


def test_list_plain(capsys):
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "gradient" in out and "starfield" in out
    assert "background" in out and "festive" in out


def test_list_json_is_machine_readable(capsys):
    assert main(["list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "background" in data
    assert "gradient" in data["background"]


def test_show_single_pattern(capsys):
    assert main(["show", "gradient"]) == 0
    out = capsys.readouterr().out
    assert "gradient" in out and "--begin" in out and "角度" in out


def test_show_all_and_json(capsys):
    assert main(["show", "all"]) == 0
    assert "starfield" in capsys.readouterr().out

    assert main(["show", "star", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["key"] == "star"
    assert data["params"]["points"]["default"] == 5


def test_show_unknown_pattern_exits_2(capsys):
    assert main(["show", "nope"]) == 2
    assert "nope" in capsys.readouterr().err


def test_render_by_pattern_name_with_set(tmp_path, capsys):
    out = tmp_path / "a.png"
    rc = main(["render", "gradient", "--size", "64x48",
               "--set", "end=#00FF00", "-o", str(out)])
    assert rc == 0
    assert out.exists() and out.stat().st_size > 0
    assert "64x48" in capsys.readouterr().out


def test_render_prints_equivalent_scene(tmp_path, capsys):
    """``--print-recipe`` 打的是**等价场景 JSON** —— CLI 调参结果能直接沉淀成可分享的文件。"""
    rc = main(["render", "star", "--size", "32x32", "--set", "points=7",
               "--print-recipe", "-o", str(tmp_path / "b.png")])
    assert rc == 0
    out = capsys.readouterr().out
    rec = json.loads(out[out.index("{"):out.rindex("}") + 1])
    assert rec["dsl"] == 1
    assert rec["size"] == [32, 32]
    op = rec["ops"][0]
    assert op["op"] == "pattern" and op["pattern"] == "star"
    assert op["params"] == {"points": 7}, "只该写出与默认值不同的参数"


def test_render_from_recipe_file(tmp_path, capsys):
    recipe = tmp_path / "r.json"
    recipe.write_text(json.dumps({"pattern": "checker", "size": [40, 40],
                                  "params": {"cell": 8}}), encoding="utf-8")
    out = tmp_path / "c.png"
    assert main(["render", str(recipe), "-o", str(out)]) == 0
    assert out.exists()


def test_render_rejects_bad_set_syntax(tmp_path, capsys):
    rc = main(["render", "gradient", "--set", "oops", "-o", str(tmp_path / "x.png")])
    assert rc == 2
    assert "k=v" in capsys.readouterr().err


def test_render_rejects_unknown_pattern(tmp_path, capsys):
    rc = main(["render", "nope", "-o", str(tmp_path / "x.png")])
    assert rc == 2
    assert "nope" in capsys.readouterr().err


def test_gallery_writes_images_and_index(tmp_path):
    assert main(["gallery", "--out", str(tmp_path), "--size", "48x32"]) == 0
    pngs = sorted(tmp_path.glob("*.png"))
    assert len(pngs) >= 18
    index = tmp_path / "index.html"
    assert index.exists()
    html = index.read_text(encoding="utf-8")
    assert "pixsmith" in html and "gradient" in html


def test_gallery_can_skip_html(tmp_path):
    assert main(["gallery", "--out", str(tmp_path), "--size", "32x32",
                 "--no-html"]) == 0
    assert not (tmp_path / "index.html").exists()


def test_gallery_prunes_stale_files_but_keeps_foreign_ones(tmp_path):
    """图案换分类会留下孤儿文件 —— 画廊必须清掉它们，但**不能碰**用户自己的文件。

    （真实踩过：把 natural 类的 4 个图案从 texture 改过来后，旧文件一直留着，
    提交时就成了重复的两套图。）
    """
    stale = tmp_path / "texture__marble.png"      # 符合本命令命名规范 → 该清
    foreign = tmp_path / "my_notes.png"           # 用户自己的文件 → 别碰
    weird = tmp_path / "notes__extra.svg"         # 分类段不是已知分类 → 别碰
    for f in (stale, foreign, weird):
        f.write_bytes(b"x")
    assert main(["gallery", "--out", str(tmp_path), "--size", "24x24",
                 "--no-html"]) == 0
    assert not stale.exists(), "陈旧孤儿文件应当被清理"
    assert foreign.exists(), "用户自己的文件不该被清理"
    assert weird.exists(), "不符合命名规范的文件不该被清理"


# ---------------------------------------------------------------- new
def test_new_prints_usable_skeleton(capsys):
    """脚手架的产物必须真的能用：有 @pattern 声明、有参数、有收录三问。"""
    assert main(["new", "my_thing", "--category", "texture"]) == 0
    out = capsys.readouterr().out
    assert '@pattern("my_thing"' in out
    assert 'category="texture"' in out
    assert "Param(" in out
    assert "收录三问" in out
    assert "requires" in out, "骨架里应当提示双后端的声明方式"


def test_new_writes_file(tmp_path, capsys):
    target = tmp_path / "sub" / "p.py"
    assert main(["new", "demo_key", "-o", str(target)]) == 0
    assert target.exists()
    assert '@pattern("demo_key"' in target.read_text(encoding="utf-8")


def test_new_rejects_bad_name(capsys):
    for bad in ("Bad-Name", "1abc", "空格 名", "has.dot"):
        assert main(["new", bad]) == 2, f"{bad!r} 应被拒绝"
    assert "只能用小写字母" in capsys.readouterr().err


def test_new_warns_on_duplicate_key(capsys):
    assert main(["new", "gradient"]) == 0
    assert "已存在" in capsys.readouterr().err


# ---------------------------------------------------------------- 路径 vs 图案名
def test_missing_path_reports_file_not_found_not_unknown_pattern(tmp_path, capsys):
    """路径拼错时必须报「文件不存在」，而不是「没有名为 'x.json' 的图案」。

    后者是**文不对题**的报错：agent 会照着去改图案名，越改越远。
    """
    missing = tmp_path / "verify" / "typo.json"
    for cmd in (["validate", str(missing)], ["render", str(missing)]):
        assert main(cmd) == 2
        err = capsys.readouterr().err
        assert "文件不存在" in err, f"{cmd} 的报错应说明文件不存在：{err}"
        assert "没有名为" not in err, f"{cmd} 不该把它当作图案名"
        assert str(missing) in err


def test_path_like_input_never_falls_back_to_pattern_name(tmp_path, capsys):
    """含分隔符或扩展名的输入**永远**按路径处理，即使图案同名也不会被误认。"""
    for bad in ("a/b", "a\\b", "scene.json", "x.yaml"):
        assert main(["validate", bad]) == 2
        assert "文件不存在" in capsys.readouterr().err, bad


def test_bare_name_still_works_as_pattern(tmp_path):
    """不带路径特征的名字仍然当图案名 —— 这条便利不能丢。"""
    out = tmp_path / "a.png"
    assert main(["render", "gradient", "--size", "16x16", "-o", str(out)]) == 0
    assert out.exists()


def test_output_name_derived_from_input_path(tmp_path):
    """输入是路径时输出名从它派生（scene.json → scene.png），不是 scene.json.png。"""
    src = tmp_path / "cover.json"
    src.write_text('{"dsl":1,"size":[16,16],"ops":[{"op":"fill","color":"#123456"}]}',
                   encoding="utf-8")
    assert main(["render", str(src)]) == 0
    assert (tmp_path / "cover.png").exists()
    assert not (tmp_path / "cover.json.png").exists()


def test_dir_is_rejected_as_scene_file(tmp_path, capsys):
    assert main(["validate", str(tmp_path)]) == 2
    assert "目录" in capsys.readouterr().err


# ------------------------------------------------------------------ export
def test_export_writes_size_ladder_svg_and_both_mono_inks(tmp_path):
    """一次导出"尺寸阶梯 × 两种单色墨"，外加一份矢量。

    这条盯的是一个真实踩过的坑：手工循环时只做了深墨单色版，
    漏了"深墨压在深底上等于没画"的白墨版。矩阵类输出正该由工具兜住。
    """
    out = tmp_path / "exp"
    code = main(["export", "star", "-o", str(out), "--sizes", "64,32", "--svg",
                 "--mono", "#0A1730", "--mono-light", "#FFFFFF"])
    assert code == 0
    for name in ("star_64.png", "star_32.png", "star.svg",
                 "star_mono_64.png", "star_mono_32.png",
                 "star_mono_light_64.png", "star_mono_light_32.png"):
        p = out / name
        assert p.exists(), f"缺少 {name}"
        assert p.stat().st_size > 0, f"{name} 是空文件"


def test_export_sizes_accept_explicit_width_height(tmp_path):
    """`--sizes` 里除了方图 N，还要能写 WxH。"""
    out = tmp_path / "exp"
    assert main(["export", "star", "-o", str(out), "--sizes", "80x60,40x30"]) == 0
    assert (out / "star_80x60.png").exists()
    assert (out / "star_40x30.png").exists()


def test_export_without_sizes_uses_scene_own_size(tmp_path):
    """不写 `--sizes` 就只用场景自己的尺寸 —— 不擅自决定用户要哪几档。"""
    src = tmp_path / "s.json"
    src.write_text('{"dsl":1,"size":[50,40],"ops":[{"op":"fill","color":"#123456"}]}',
                   encoding="utf-8")
    out = tmp_path / "exp"
    assert main(["export", str(src), "-o", str(out)]) == 0
    assert (out / "s_50x40.png").exists()


def test_export_rejects_bad_size_syntax(tmp_path, capsys):
    assert main(["export", "star", "-o", str(tmp_path), "--sizes", "abc"]) == 2
    assert "尺寸" in capsys.readouterr().err


def test_mono_rewrite_replaces_colors_and_keeps_alpha():
    """单色改写要按 `Param` 声明类型动手，并**保留各自透明度**。

    丢透明度的后果不是"少个属性"——抗锯齿边缘会变成硬边，小尺寸下很明显。
    """
    from pixsmith.cli import _mono_dict
    from pixsmith.color import to_rgba8

    src = {"dsl": 1, "size": [10, 10], "background": "#FF000080",
           "ops": [{"op": "disc", "cx": 3, "cy": 4, "r": 2, "color": "#00FF00AA"},
                   {"op": "pattern", "pattern": "gradient",
                    "params": {"begin": "#111111", "end": "#222222"}}]}
    mono = _mono_dict(src, "#0A1730")

    assert to_rgba8(mono["background"]) == (10, 23, 48, 128), "底色应换成墨色且保留 alpha"
    assert to_rgba8(mono["ops"][0]["color"]) == (10, 23, 48, 170), "图形色应换成墨色且保留 alpha"
    # 图案参数（在 params 里）同样要覆盖
    assert to_rgba8(mono["ops"][1]["params"]["begin"]) == (10, 23, 48, 255)
    assert to_rgba8(mono["ops"][1]["params"]["end"]) == (10, 23, 48, 255)
    # 非颜色参数不许被碰
    assert mono["ops"][0]["cx"] == 3 and mono["ops"][0]["r"] == 2
    # 原字典不能被就地改掉（改了会让调用方的 base 场景失效）
    assert src["background"] == "#FF000080"
    assert src["ops"][0]["color"] == "#00FF00AA"


def test_mono_is_clean_counts_leftover_colors():
    """单色版必须真的只有一种 RGB —— 多色参数漏改时这张图会被判为"不干净"。

    这条是"静默失败"的探测器：混了原色的单色版照样能导出、退出码照样 0，
    只有真把两种墨印在同一张纸上才露馅。
    """
    import numpy as np

    from pixsmith.cli import _mono_is_clean

    one = np.zeros((4, 4, 4), dtype=np.uint8)
    one[..., 3] = 255
    one[..., 0] = 10
    assert _mono_is_clean(one) == 1

    one[0, 0, 1] = 99                       # 混进第二种颜色
    assert _mono_is_clean(one) == 2

