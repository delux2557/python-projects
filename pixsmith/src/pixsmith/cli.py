"""命令行入口。

设计原则：**只依赖标准库 argparse**（numpy 已经是硬依赖，不再多引入 CLI 框架），
子命令名用动词，参数名与配方字段一致 —— 这样 CLI 用法可以原样抄进配方 JSON。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .canvas import Canvas
from .patterns import by_category, describe, get, names
from .patterns._util import fit_size
from .recipes import DEFAULT_SIZE, list_patterns, recipe_from_cli, render, to_json

__all__ = ["main", "build_parser"]


def _cmd_list(args) -> int:
    if args.json:
        print(json.dumps(list_patterns(), ensure_ascii=False, indent=2))
        return 0
    for cat, items in by_category().items():
        print(f"\n[{cat}]")
        for p in items:
            print(f"  {p.key:<20} {p.summary}")
    print(f"\n共 {len(names())} 个图案。用 `pixsmith show <图案名>` 看参数。")
    return 0


def _cmd_show(args) -> int:
    if args.pattern in ("all", "*"):
        for i, key in enumerate(names()):
            if i:
                print()
            print(describe(key))
        return 0
    if args.json:
        p = get(args.pattern)
        data = {spec.name: {"type": spec.type, "default": spec.default,
                            "doc": spec.doc} for spec in p.params}
        print(json.dumps({"key": p.key, "category": p.category,
                          "summary": p.summary, "params": data},
                         ensure_ascii=False, indent=2))
        return 0
    print(describe(args.pattern))
    return 0


def _load_scene(args) -> "Scene":
    """把命令行输入统一成 `Scene` —— 场景、旧配方、图案名三种写法都收。"""
    from .recipes import recipe_from_cli
    from .scene import Scene

    if args.recipe == "-":
        return Scene.from_dict(json.loads(sys.stdin.read()))
    as_pattern = (bool(args.set) or bool(args.size) or bool(args.background)
                  or not Path(args.recipe).exists())
    if as_pattern:
        return Scene.from_dict(recipe_from_cli(args.recipe, args.size,
                                               args.background, args.set))
    return Scene.from_file(args.recipe)


def _cmd_render(args) -> int:
    from .scene import Scene          # noqa: F401  (类型可见性)
    from .svg import SvgBackend

    scene = _load_scene(args)
    want_svg = (args.backend == "svg"
                or (args.backend is None and str(args.out or "").lower().endswith(".svg")))
    backend = SvgBackend(*scene.size) if want_svg else None
    out = args.out or (f"{args.recipe}.svg" if want_svg
                       else (f"{args.recipe}.png" if args.recipe != "-" else "scene.png"))

    if args.print_recipe:
        print(scene.to_json(compact=True))
    scene.render(backend).save(out)
    print(f"✅ {out}  ({scene.size[0]}x{scene.size[1]} · "
          f"{'svg' if want_svg else 'raster'} · {len(scene.all_ops())} ops)")

    if args.report:
        if want_svg:
            # 矢量端没有"像素"这个概念，统计口径无从谈起 —— 说清楚而不是给个假报告
            print("ℹ️ --report 需要像素，仅对位图后端可用；"
                  "要报告请加 `--backend raster`。", file=sys.stderr)
        else:
            print(json.dumps(scene.report(), ensure_ascii=False, indent=2))
    return 0


def _cmd_spec(args) -> int:
    """能力清单 —— 给 AI agent 的自述文件（agent 靠它发现能力，而不是靠猜）。"""
    from .manifest import capability_manifest

    man = capability_manifest(with_examples=not args.no_examples)
    if args.json:
        print(json.dumps(man, ensure_ascii=False, indent=2))
        return 0
    print(f"{man['name']} v{man['version']}  ·  DSL v{man['dsl_version']}")
    print(f"\n后端：")
    for name, info in man["backends"].items():
        extra = (" 不支持：" + ", ".join(info["unsupported"])
                 if info.get("unsupported") else "")
        print(f"  {name:<8} {info['note']}{extra}")
    print(f"\n动词（{len(man['verbs'])}）：")
    for cat in ("frame", "draw", "gradient", "filter"):
        keys = [k for k, v in man["verbs"].items() if v["category"] == cat]
        if keys:
            print(f"  {cat:<9} " + " ".join(sorted(keys)))
    print(f"\n图案（{len(man['patterns'])}）：")
    for cat, keys in _pattern_categories(man).items():
        print(f"  {cat:<11} " + " ".join(sorted(keys)))
    print(f"\n混合模式：{', '.join(man['blends'])}")
    print(f"噪声种类：{', '.join(man['noise_kinds'])}")
    print("\n加 --json 拿机器可读的完整清单（含每个参数的默认值/类型/后端支持）。")
    return 0


def _pattern_categories(man: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, info in man["patterns"].items():
        out.setdefault(info["category"], []).append(key)
    return out


def _cmd_gallery(args) -> int:
    from .patterns._util import fit_size as _fit
    from .scene import Scene
    from .svg import SvgBackend

    size = _fit(args.size or (640, 400))
    out_dir = Path(args.out or "gallery")
    out_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    n_svg = 0
    for cat, items in by_category().items():
        for p in items:
            scene = Scene.from_dict({"dsl": 1, "size": list(size),
                                     "pattern": p.key})
            try:
                scene.render().save(out_dir / f"{cat}__{p.key}.png")
            except Exception as exc:                      # noqa: BLE001
                print(f"  ⚠️ {p.key} 渲染失败：{exc}", file=sys.stderr)
                continue
            svg_name = ""
            if args.svg:
                # 只在真的支持矢量时才产 svg —— 用声明的 requires 判断，不试错
                if not set(p.requires):
                    try:
                        scene.render(SvgBackend(*size)).save(
                            out_dir / f"{cat}__{p.key}.svg")
                        svg_name = f"{cat}__{p.key}.svg"
                        n_svg += 1
                    except Exception as exc:              # noqa: BLE001
                        print(f"  ⚠️ {p.key} 的 svg 失败：{exc}", file=sys.stderr)
            cards.append((cat, p, f"{cat}__{p.key}.png", svg_name))
            print(f"  ✅ {cat}__{p.key}.png" + (f" + .svg" if svg_name else ""))

    if not args.no_html:
        rows = []
        cur = None
        for cat, p, name, svg_name in cards:
            if cat != cur:
                if cur is not None:
                    rows.append("</div>")
                rows.append(f'<h2>{cat}</h2><div class="grid">')
                cur = cat
            alt = f'<a class="svg" href="{svg_name}" title="矢量版（可无损缩放）">SVG</a>' \
                if svg_name else ""
            rows.append(
                f'<figure><img src="{name}" alt="{p.key}" loading="lazy">'
                f'<figcaption><b>{p.key}</b>{alt}<span>{p.summary}</span></figcaption></figure>')
        if cur is not None:
            rows.append("</div>")
        html = _GALLERY_HTML.format(version=__version__, cards="\n".join(rows))
        (out_dir / "index.html").write_text(html, encoding="utf-8")
        print(f"\n画廊索引： {out_dir / 'index.html'}")
    print(f"共 {len(cards)} 张" + (f"（其中 {n_svg} 张另附矢量版）" if args.svg else "") + "。")
    return 0


_GALLERY_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pixsmith · 图案画廊</title>
<style>
:root {{ color-scheme: light dark; --fg:#1a1a1a; --bg:#faf9f7; --muted:#6b6b6b; --card:#fff; --line:#e5e2dc; }}
@media (prefers-color-scheme: dark) {{ :root {{ --fg:#f0eee9; --bg:#141414; --muted:#a0a0a0; --card:#1e1e1e; --line:#333; }} }}
* {{ box-sizing: border-box; }}
body {{ margin:0; padding:40px 28px 64px; background:var(--bg); color:var(--fg);
  font-family: ui-sans-serif, system-ui, "Segoe UI", "Microsoft YaHei", sans-serif; }}
h1 {{ font-size:22px; font-weight:600; margin:0 0 6px; }}
p.sub {{ color:var(--muted); font-size:13px; margin:0 0 32px; }}
h2 {{ font-size:13px; font-weight:600; text-transform:uppercase; letter-spacing:.08em;
  color:var(--muted); margin:36px 0 14px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(240px, 1fr)); gap:16px; }}
figure {{ margin:0; background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden; }}
img {{ display:block; width:100%; aspect-ratio:8/5; object-fit:cover;
  background:#000; }}
figcaption {{ padding:10px 12px; font-size:12px; line-height:1.5; }}
figcaption b {{ display:block; font-size:13px; font-weight:600; }}
figcaption .svg {{ float:right; font-size:11px; color:var(--muted);
  border:1px solid var(--line); border-radius:4px; padding:0 5px; text-decoration:none; }}
figcaption span {{ color:var(--muted); }}
footer {{ margin-top:48px; color:var(--muted); font-size:12px; }}
code {{ font-family:ui-monospace, Consolas, monospace; background:var(--line);
  padding:1px 5px; border-radius:4px; }}
</style></head><body>
<h1>pixsmith · 图案画廊</h1>
<p class="sub">v{version} · 全部图片由 <code>pixsmith gallery</code> 程序生成，无外部素材、无版权风险。</p>
{cards}
<footer>重新生成：<code>pixsmith gallery --out gallery</code></footer>
</body></html>
"""


_PATTERN_SKELETON = '''"""<这一类图案的定位> —— <这个图案的一句话说明>。

【收录三问】提交前必须答得上，答不上就不该收：
1. **演示什么能力组合**：用了哪几个图元 / 算子（写具体名字）
2. **改哪个参数会怎样**：一句话给使用者指路
3. **什么场景该用它**：海报底图？图示装饰？占位件？
"""

from __future__ import annotations

from . import Param, pattern

__all__ = []


@pattern("{key}", "<一句话描述：会出现在 CLI list 与画廊里>", [
    Param("color", "color", "#F2C14E", "主色"),
    Param("freq", "float", 4.0, "密度（越大越密）"),
    Param("seed", "int", 0, "随机种子（决定可复现）"),
], category="{category}")
def {key}(c, *, color, freq, seed):
    """只调用**后端协议**里的方法（清单见 `pixsmith/backend.py`），两个后端才能都跑。

    确需逐像素（numpy 场 / `c.paint`）时，加上 `requires=("paint",)` 显式声明 ——
    矢量后端会在渲染前拦下并给出替代方案，而不是静默降级。
    """
    c.fill("#0A1730")
    for i in range(8):
        c.disc(20.0 + i * 12.0, 30.0, 6.0, color)
    return c
'''

_NEW_CHECKLIST = """
下一步（照做就行）：
  1. 把上面的函数贴进 src/pixsmith/patterns/<模块>.py（按类别选模块，见模块 docstring）
  2. 重装：pip install -e .
  3. pytest                      ← 新图案会自动被测试纳入，不用手写用例
  4. pixsmith show {key}          ← 检查参数声明有没有漏
  5. pixsmith gallery --out gallery --svg   ← 生成效果图并看是否满意
  6. 回答 docstring 里的【收录三问】—— 答不上就别提交

⚠️ 硬性禁忌：仓库内任何地方不得出现指向特定厂商/产品的字样
   （见 CONTRIBUTING.md 的「文字与命名禁忌」）。
"""


def _cmd_new(args) -> int:
    """生成一个图案骨架 —— 让"加一个图案"从"读源码猜格式"变成"填模板"。"""
    import re

    key = str(args.key).strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
        print("❌ 图案名只能用小写字母 / 数字 / 下划线，且以字母开头", file=sys.stderr)
        return 2
    from .patterns import REGISTRY
    exists = key in REGISTRY
    cat = args.category or "misc"
    body = _PATTERN_SKELETON.format(key=key, category=cat)
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        print(f"✅ 已写入 {p}")
    else:
        print(body)
    if exists:
        print(f"\n⚠️ 注意：图案 key {key!r} **已存在**，重名会在导入时直接报错。"
              f"请换一个名字，或先确认是否与已有图案重复。", file=sys.stderr)
    print(_NEW_CHECKLIST.format(key=key))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pixsmith",
        description="程序化生成背景 / 底纹 / 装饰件 PNG（零素材、可复现）",
    )
    p.add_argument("--version", action="version", version=f"pixsmith {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="列出全部图案")
    s.add_argument("--json", action="store_true", help="以 JSON 输出")
    s.set_defaults(func=_cmd_list)

    s = sub.add_parser("show", help="查看某个图案的参数说明")
    s.add_argument("pattern", help="图案名；用 all 看全部")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_show)

    s = sub.add_parser("render", help="渲染：吃场景 JSON、旧配方，或直接给图案名 + --set")
    s.add_argument("recipe", help="场景 JSON 路径 / 配方路径 / 图案名 / - 读 stdin")
    s.add_argument("-o", "--out", help="输出路径（.svg 后缀会自动切到矢量后端）")
    s.add_argument("--size", help="画布尺寸 WxH，如 1920x1080")
    s.add_argument("--background", help="底色，如 '#0A1730' 或 '#00000000'")
    s.add_argument("--set", action="append", metavar="K=V",
                   help="覆盖图案参数（可多次）")
    s.add_argument("--backend", choices=["raster", "svg"],
                   help="输出后端（默认按 -o 后缀推断，无后缀则用 raster）")
    s.add_argument("--report", action="store_true",
                   help="打印自检报告（非透明占比/主色/对比度…）给 agent 当眼睛")
    s.add_argument("--print-recipe", action="store_true",
                   help="顺便把等价的**场景 JSON** 打到 stdout")
    s.set_defaults(func=_cmd_render)

    s = sub.add_parser("spec", help="能力清单（给 AI agent 的自述文件）")
    s.add_argument("--json", action="store_true", help="机器可读的完整清单")
    s.add_argument("--no-examples", action="store_true",
                   help="不附带每个图案的最小可用场景")
    s.set_defaults(func=_cmd_spec)

    s = sub.add_parser("new", help="生成一个图案骨架（贡献新素材时用）")
    s.add_argument("key", help="图案名（小写字母/数字/下划线，如 my_texture）")
    s.add_argument("--category", help="分类：background|texture|natural|shape|festive")
    s.add_argument("-o", "--out", help="写入文件（省略则打到 stdout）")
    s.set_defaults(func=_cmd_new)

    s = sub.add_parser("gallery", help="一次渲染全部图案 + 生成 HTML 索引")
    s.add_argument("-o", "--out", help="输出目录（默认 gallery/）")
    s.add_argument("--size", help="单张尺寸 WxH（默认 640x400）")
    s.add_argument("--svg", action="store_true",
                   help="为支持矢量后端的图案**额外**产出 .svg（演示双后端）")
    s.add_argument("--no-html", action="store_true", help="只出图，不生成 index.html")
    s.set_defaults(func=_cmd_gallery)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (KeyError, ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
