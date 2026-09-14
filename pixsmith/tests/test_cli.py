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
