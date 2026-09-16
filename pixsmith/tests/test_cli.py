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


# ------------------------------------------------------------------ sheet
def _spy_sheet(monkeypatch):
    """把最后一次 `Canvas.save` 的**像素**截下来 —— 联络表的断言全在像素上。"""
    from pixsmith.canvas import Canvas

    seen: dict = {}
    real = Canvas.save

    def spy(self, path):
        seen["arr"] = self.to_rgba8()
        return real(self, path)

    monkeypatch.setattr(Canvas, "save", spy)
    return seen


def test_sheet_places_each_size_verbatim_without_resampling(tmp_path, monkeypatch,
                                                            capsys):
    """**这条是 `sheet` 的核心承诺**：每个格子都是按目标尺寸单独渲染的原始像素。

    不是"缩过的大图"：把 512 采样到 16 会让抗锯齿边缘糊成灰，而真按 16px 渲染
    可能是干净的 3 个像素。两者看起来"差不多"，判断结论却可能相反。
    所以这里不看"像不像"，直接比字节。

    场景带不透明底色：格子里全被盖住，才谈得上"原样"（透空处本就该露出棋盘格）。
    """
    import numpy as np

    from pixsmith.scene import Scene

    seen = _spy_sheet(monkeypatch)
    src = tmp_path / "s.json"
    base = {"dsl": 1, "size": [64, 64], "background": "#102030", "pattern": "star"}
    src.write_text(json.dumps(base), encoding="utf-8")

    assert main(["sheet", str(src), "--sizes", "64,32",
                 "-o", str(tmp_path / "a.png"), "--json"]) == 0
    lay = json.loads(capsys.readouterr().out)
    sheet = seen["arr"]
    assert sheet.shape[:2] == (lay["sheet_size"][1], lay["sheet_size"][0])
    assert len(lay["tiles"]) == 2

    for t in lay["tiles"]:
        w, h = t["size"]
        x, y = t["at"]
        want = Scene.from_dict({**base, "size": [w, h]}).render().to_rgba8()
        assert want[..., 3].min() == 255, "夹具场景必须是全不透明的，否则断言会空过"
        assert np.array_equal(sheet[y:y + h, x:x + w], want), \
            f"{w}px 那格不是原样放进去的（被重采样了）"


def test_sheet_is_a_grid_of_recipes_by_sizes(tmp_path, capsys):
    """行 = 配方，列 = 尺寸档 —— 版式图必须机器可读，否则格子没标签就没人知道谁是谁。"""
    out = tmp_path / "g.png"
    assert main(["sheet", "star", "gradient", "--size", "40x40",
                 "--sizes", "40,20", "-o", str(out), "--json"]) == 0
    lay = json.loads(capsys.readouterr().out)
    assert (lay["rows"], lay["cols"]) == (2, 2)
    assert lay["cell"] == [40, 40]
    assert [(t["row"], t["col"], t["recipe"], t["size"]) for t in lay["tiles"]] == [
        (0, 0, "star", [40, 40]), (0, 1, "star", [20, 20]),
        (1, 0, "gradient", [40, 40]), (1, 1, "gradient", [20, 20])]
    # 每格落点必须落在画布内，且左上角就是外边距起点
    assert lay["tiles"][0]["at"] == [lay["pad"], lay["pad"]]
    for t in lay["tiles"]:
        assert 0 <= t["at"][0] and t["at"][0] + t["size"][0] <= lay["sheet_size"][0]
        assert 0 <= t["at"][1] and t["at"][1] + t["size"][1] <= lay["sheet_size"][1]
    assert out.exists() and out.stat().st_size > 0


def test_sheet_json_is_the_only_thing_on_stdout(tmp_path, capsys):
    """`--json` 的 stdout 必须**只有** JSON —— agent 是按行解析的。"""
    assert main(["sheet", "star", "--size", "32x32", "--sizes", "32",
                 "-o", str(tmp_path / "a.png"), "--json"]) == 0
    json.loads(capsys.readouterr().out)          # 多一行都会被这里炸出来


def test_sheet_default_background_is_checkerboard(tmp_path, monkeypatch):
    """默认底色是棋盘格，**不是纯色** —— 否则「透空」与「画了一块纯色」肉眼分不开。"""
    import numpy as np

    seen = _spy_sheet(monkeypatch)
    assert main(["sheet", "star", "--size", "16x16", "--sizes", "16",
                 "-o", str(tmp_path / "c.png")]) == 0
    sheet = seen["arr"]
    corner = sheet[0, 0]                          # 左上角必落在外边距（无格子的地方）
    assert corner[3] == 255, "默认底色不能是透明的"
    padding = sheet[0, :, :3].reshape(-1, 3)
    assert len(np.unique(padding, axis=0)) == 2, "底色应该是两色棋盘，不是纯色"


def test_sheet_background_none_keeps_the_padding_transparent(tmp_path, monkeypatch):
    seen = _spy_sheet(monkeypatch)
    assert main(["sheet", "star", "--size", "16x16", "--sizes", "16",
                 "--background", "none", "-o", str(tmp_path / "n.png")]) == 0
    assert seen["arr"][0, 0, 3] == 0, "`--background none` 时外边距应当透空"


def test_sheet_rejects_oversized_sheet(tmp_path, capsys):
    """尺寸是硬约束：宁可报错也不替你缩 —— 缩了这张表的结论就作废了。"""
    assert main(["sheet", "star", "--sizes", "4000,3500",
                 "-o", str(tmp_path / "big.png")]) == 2
    err = capsys.readouterr().err
    assert "上限" in err and "MP" in err


def test_sheet_rejects_set_with_multiple_recipes(tmp_path, capsys):
    """`--set` 只能配单个配方：多份配方套同一份覆盖＝静默改错场景。"""
    assert main(["sheet", "star", "gradient", "--size", "32x32",
                 "--set", "color=#FF0000", "-o", str(tmp_path / "s.png")]) == 2
    assert "--set" in capsys.readouterr().err


def test_canvas_blit_only_translates(tmp_path):
    """`blit` 是拼版用的平移合成：越界裁掉而不是炸，负数落点直接报错。"""
    import numpy as np
    import pytest as _pytest

    from pixsmith.canvas import Canvas

    src = np.zeros((4, 4, 4), dtype=np.uint8)
    src[..., 0], src[..., 3] = 200, 255

    c = Canvas(6, 6)
    c.blit(src, 2, 2)                            # 右下角溢出 2 行 2 列，裁掉即可
    assert tuple(c.to_rgba8()[2, 2, :3]) == (200, 0, 0)
    assert c.to_rgba8()[5, 5, 3] == 255

    c2 = Canvas(4, 4)
    c2.blit(src, 10, 0)                          # 完全在画布外 → 什么都不做
    assert c2.to_rgba8()[..., 3].max() == 0

    with _pytest.raises(ValueError, match="落点"):
        Canvas(4, 4).blit(src, -1, 0)
    with _pytest.raises(ValueError, match="\\(h, w, 4\\)"):
        Canvas(4, 4).blit(np.zeros((4, 4, 3), dtype=np.uint8), 0, 0)

