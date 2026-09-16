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
from .backend import UnsupportedOperation
from .canvas import Canvas
from .patterns import by_category, describe, get, names
from .patterns._util import fit_size
from .playground import DEFAULT_HOST, DEFAULT_PORT
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


def _resolve_spec(key: str):
    """按名字解析能力：**先找图案，再找动词**。

    以前 `show` 只看图案，于是 `show blur` 会报"没有名为 blur 的图案" ——
    动词明明存在，agent 却拿不到它的 JSON 规格。这两类的查询入口本来就该是一个。
    """
    from .ops import VERBS
    from .patterns import REGISTRY

    if key in REGISTRY:
        return REGISTRY.get(key), "pattern"
    if key in VERBS:
        return VERBS.get(key), "verb"
    raise KeyError(f"没有名为 {key!r} 的图案或动词。"
                   f"图案：{REGISTRY.names()}；动词：{VERBS.names()}")


def _cmd_show(args) -> int:
    if args.pattern in ("all", "*"):
        for i, key in enumerate(names()):
            if i:
                print()
            print(describe(key))
        return 0
    spec, kind = _resolve_spec(args.pattern)
    if args.json:
        data = {p.name: {"type": p.type, "default": p.default, "doc": p.doc}
                for p in spec.params}
        print(json.dumps({"key": spec.key, "kind": kind, "category": spec.category,
                          "summary": spec.summary, "requires": list(spec.requires),
                          "params": data}, ensure_ascii=False, indent=2))
        return 0
    print(spec.describe())
    return 0


#: 出现这些特征就一定是**路径**，不再当图案名猜
_PATH_MARKS = ("/", "\\")
_PATH_EXTS = (".json", ".yaml", ".yml", ".toml", ".txt")


def _looks_like_path(s: str) -> bool:
    """判断输入是不是"像路径"。含分隔符或已知扩展名 → 是。

    这条判断是为了消灭一个**文不对题**的报错：以前 `as_pattern` 的启发式是
    "文件不存在就当成图案名"，于是 `validate output/typo.json` 会报
    「没有名为 'output/typo.json' 的图案」—— 明明该说"文件不存在"。
    对 agent 来说，错误的报错类型比没有报错更费 token：它会去改图案名。
    """
    return any(m in s for m in _PATH_MARKS) or s.lower().endswith(_PATH_EXTS)


_UNSET = object()


def _load_scene(args, raw=None, *, background=_UNSET) -> "Scene":
    """把命令行输入统一成 `Scene`：stdin / 场景文件 / 旧配方 / 图案名。

    判定顺序（**先路径后图案，没有"猜"的余地**）：
      1. ``-``          → 读 stdin
      2. 像路径          → 必须是文件，不存在就报**文件不存在**（附带绝对路径与当前目录）
      3. 确实是文件      → 读文件
      4. 其余            → 图案名（配合 ``--set`` / ``--size`` / ``--background``）

    ``raw`` 省略时取 ``args.recipe``；`sheet` 一次要吃多个输入，所以显式传。
    ``background`` 用来把"场景底色"与"联络表底色"分开 —— `sheet` 的 ``--background``
    指的是**整张表**的底色，不该顺手改掉格子里的场景。
    """
    from .recipes import recipe_from_cli
    from .scene import Scene

    raw = str(args.recipe if raw is None else raw)
    bg = args.background if background is _UNSET else background
    if raw == "-":
        return Scene.from_dict(json.loads(sys.stdin.read()))

    path = Path(raw)
    if _looks_like_path(raw):
        if path.is_dir():
            raise IsADirectoryError(f"{raw!r} 是目录，不是场景文件")
        if not path.exists():
            raise FileNotFoundError(
                f"文件不存在：{raw}\n"
                f"  已按路径解析为：{path.resolve()}\n"
                f"  当前目录：{Path.cwd()}\n"
                f"  如果你是想用图案名渲染，名字里不要带路径分隔符或扩展名，"
                f"例如 `pixsmith render gradient`；可用图案见 `pixsmith list`。")
        return Scene.from_file(path)
    if path.exists():
        return Scene.from_file(path)
    return Scene.from_dict(recipe_from_cli(raw, args.size, bg, args.set))


def _cmd_render(args) -> int:
    from .scene import Scene          # noqa: F401  (类型可见性)
    from .svg import SvgBackend

    scene = _load_scene(args)
    want_svg = (args.backend == "svg"
                or (args.backend is None and str(args.out or "").lower().endswith(".svg")))
    backend = SvgBackend(*scene.size) if want_svg else None
    ext = ".svg" if want_svg else ".png"
    if args.out:
        out = args.out
    elif _looks_like_path(args.recipe):
        # 输入是路径时，输出名从它派生（scene.json → scene.png），
        # 而不是拼成 scene.json.png 那种怪东西
        out = str(Path(args.recipe).with_suffix(ext))
    else:
        out = f"{args.recipe}{ext}" if args.recipe != "-" else f"scene{ext}"

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


def _parse_sizes(spec, default: tuple[int, int]) -> list[tuple[int, int]]:
    """解析 `--sizes`：``512,64,32,16``（方图）或 ``800x600,1200x630``（显式宽高）。

    不写 `--sizes` 就只用场景自己的尺寸 —— 也就是说 `export` 退化成
    "render + 顺便出矢量 / 单色版"，不擅自替用户决定他需要哪几个尺寸。
    """
    if not spec:
        return [tuple(default)]                      # type: ignore[arg-type]
    out: list[tuple[int, int]] = []
    for part in str(spec).split(","):
        t = part.strip().lower().replace("*", "x")
        if not t:
            continue
        if "x" in t:
            w, _, h = t.partition("x")
            if not (w.strip().isdigit() and h.strip().isdigit()):
                raise ValueError(f"看不懂的尺寸 {part!r}：写法是 N（方图）或 WxH，"
                                 f"例如 512 或 1200x630")
            out.append((int(w), int(h)))
        elif t.isdigit():
            out.append((int(t), int(t)))
        else:
            raise ValueError(f"看不懂的尺寸 {part!r}：写法是 N（方图）或 WxH，"
                             f"例如 512 或 1200x630")
    if not out:
        raise ValueError("--sizes 是空的")
    return out


def _export_stem(recipe: str) -> str:
    """输出文件名的主干：路径取文件名、stdin 叫 scene、其余当图案名。"""
    raw = str(recipe)
    if raw == "-":
        return "scene"
    if _looks_like_path(raw):
        return Path(raw).stem
    return raw


def _mono_dict(obj: dict, ink: str) -> dict:
    """把场景里所有 `color` 类型的参数换成单一墨色，**保留各自透明度**。

    单色（一种墨印在任意底色上）是标识最常见的用法，手工一个个改颜色既容易漏、
    又容易把透明度丢掉（丢掉的后果是抗锯齿边缘变成硬边）。
    这里按 `Param` 声明的类型精确下手，**不靠参数名猜**。

    ⚠️ 覆盖不到 `points` 类型的多色参数（部分图案的色阶列表）——
    调用方会在渲染后用 `_mono_is_clean()` 检查出来并报警，不静默糊弄过去。
    """
    from .color import parse_color, with_alpha
    from .ops import VERBS
    from .patterns import REGISTRY as PATTERNS

    def ink_of(v):
        return with_alpha(ink, parse_color(v)[3]) if v is not None else None

    def fix_ops(ops: list) -> list:
        fixed = []
        for op in ops:
            if not isinstance(op, dict):
                fixed.append(op)
                continue
            op = dict(op)
            if str(op.get("op", "")) == "pattern":
                spec = PATTERNS.get(str(op.get("pattern")))
                params = dict(op.get("params") or {})
                if spec is not None:
                    for p in spec.params:
                        if p.type == "color" and params.get(p.name) is not None:
                            params[p.name] = ink_of(params[p.name])
                if params:
                    op["params"] = params
            else:
                spec = VERBS.get(str(op.get("op", "")))
                if spec is not None:
                    for p in spec.params:
                        if p.type == "color" and op.get(p.name) is not None:
                            op[p.name] = ink_of(op[p.name])
            fixed.append(op)
        return fixed

    out = dict(obj)
    if out.get("background") is not None:
        out["background"] = ink_of(out["background"])
    if isinstance(out.get("ops"), list):
        out["ops"] = fix_ops(out["ops"])
    if isinstance(out.get("layers"), list):
        layers = []
        for ly in out["layers"]:
            if isinstance(ly, dict) and isinstance(ly.get("ops"), list):
                layers.append({**ly, "ops": fix_ops(ly["ops"])})
            elif isinstance(ly, list):
                layers.append(fix_ops(ly))
            else:
                layers.append(ly)
        out["layers"] = layers
    return out


def _mono_is_clean(rgba) -> int:
    """数一下单色图里有几种 RGB —— 1 种才叫真单色。

    为什么值得查：单色版最常见的失败是"看着是单色、其实混进了原色"
    （多色参数没被改写）。它是**静默**的：图照样出得来、退出码照样是 0，
    只有真的把两种墨印在同一张纸上才会露馅。所以这里主动查、主动报。
    """
    import numpy as np

    a = np.asarray(rgba)
    if a.ndim != 3 or a.shape[2] < 4:
        return 1
    opaque = a[..., 3] > 0
    if not opaque.any():
        return 1
    return int(len(np.unique(a[..., :3][opaque].reshape(-1, 3), axis=0)))


def _cmd_export(args) -> int:
    """批量导出：一次出多尺寸 + 矢量 + 两种单色墨。

    为什么单独做一个子命令：做标识 / 图标时，"同一份设计 × 尺寸阶梯 × 单色墨"
    这个矩阵是**固定套路**，但手工循环既啰嗦又容易漏（真实踩过的坑：
    只做了深墨单色版，忘了"深墨压在深底上等于没画"的白墨版）。
    这类"逻辑固定、容易漏项"的活正好该由工具兜住。

    退出码与 `render` 一致：0 成功，2 用法/输入错误。
    """
    from .scene import Scene
    from .svg import SvgBackend

    scene = _load_scene(args)
    sizes = _parse_sizes(getattr(args, "sizes", None), scene.size)
    base = scene.to_dict()
    out_dir = Path(args.out or ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.name or _export_stem(args.recipe)

    def label(w: int, h: int) -> str:
        return f"{w}" if w == h else f"{w}x{h}"

    made: list[str] = []
    for w, h in sizes:
        d = {**base, "size": [w, h]}
        p = out_dir / f"{stem}_{label(w, h)}.png"
        Scene.from_dict(d).render().save(p)
        made.append(p.name)
        print(f"  ✅ {p.name}  ({w}x{h})")

    if args.svg:
        w, h = max(sizes, key=lambda s: s[0] * s[1])
        p = out_dir / f"{stem}.svg"
        Scene.from_dict({**base, "size": [w, h]}).render(SvgBackend(w, h)).save(p)
        made.append(p.name)
        print(f"  ✅ {p.name}  (矢量，按最大档 {w}x{h})")

    for ink, tag in ((args.mono, "mono"), (args.mono_light, "mono_light")):
        if not ink:
            continue
        d = _mono_dict(base, ink)
        for w, h in sizes:
            sc = Scene.from_dict({**d, "size": [w, h]})
            p = out_dir / f"{stem}_{tag}_{label(w, h)}.png"
            sc.render().save(p)
            made.append(p.name)
            print(f"  ✅ {p.name}  ({w}x{h} · 单色 {ink})")
            kinds = _mono_is_clean(sc.render().to_rgba8())
            if kinds > 1:
                print(f"  ⚠️ {p.name} 里有 {kinds} 种颜色，不是纯单色 —— "
                      f"这份场景含 `points` 类型的多色参数（如色阶列表），"
                      f"单色改写覆盖不到，请手工确认该参数。", file=sys.stderr)

    if args.report:
        w, h = max(sizes, key=lambda s: s[0] * s[1])
        print(json.dumps(Scene.from_dict({**base, "size": [w, h]}).report(),
                         ensure_ascii=False, indent=2))

    print(f"\n共 {len(made)} 个文件 → {out_dir}（主名 {stem}）")
    return 0


#: 联络表默认底色：透明区的通用棋盘格（白 / 浅灰）。
#: 刻意不用纯色 —— 纯色会把「透空」和「画了一块纯色」混成同一件事，
#: 而画布上真正透空的部分恰恰是 agent 需要**看见**的（`report()` 只能看见数字）。
_SHEET_CHECKER = ("#FFFFFF", "#D6D6D6")
#: 格子分隔线（只在不止一格时画）
_SHEET_SEPARATOR = "#B9B9B9"
#: 联络表总像素上限。超了就**明确报错**，不做"偷偷抽稀"这种事 ——
#: 悄悄换掉尺寸会让"16px 那档还认不认得出"这个判断直接失效。
#: 16 MP 同时也是内存护栏：画布 ``buf`` 是 float32 四通道（16 B/px），
#: 算上棋盘格的 RGB 场（12 B/px），16 MP 的峰值约 350 MB —— 再往上就不体面了。
_SHEET_MAX_PIXELS = 16_000_000


def _checker_field(w: int, h: int, tile: int, c0: str, c1: str):
    """两色棋盘格的 RGB 场（不透明），交给 `Canvas.paint` 铺底。"""
    import numpy as np

    from .color import parse_color

    t = max(2, int(tile))
    ix = np.arange(w, dtype=np.int64) // t
    iy = np.arange(h, dtype=np.int64) // t
    parity = ((ix[None, :] + iy[:, None]) % 2).astype(bool)
    a, b = parse_color(c0), parse_color(c1)
    field = np.empty((h, w, 3), dtype=np.float32)
    for i in range(3):
        field[..., i] = np.where(parity, b[i], a[i])
    return field


def _cmd_sheet(args) -> int:
    """联络表：把**多个配方 × 多个尺寸**渲染进同一张画布，一图看全。

    为什么需要它
    ------------
    `export` 出的是**一堆文件**：4 档尺寸就是 4 个 PNG。agent 要判断"16px 那档
    还认得出吗"，得连着读 4 次图 —— 既费 token，又**看不出相对大小**
    （4 张图摆在眼前是一样大的）。联络表把同一份设计的不同档位按**真实像素尺寸**
    摆在一张图上：512 与 16 的格子边长比就是 32:1，看不清就是看不清，一眼的事。

    为什么不需要 PNG 解码器，也没碰「刻意不做」
    ------------------------------------------
    每个格子都是**先按目标尺寸渲染、再原样摆进去**（`Canvas.blit`），
    全程没有重采样，也没有读任何外部图片文件。所以它用的是现有能力，
    不是"图像编辑"—— 「不做图像编辑（裁剪 / 合成已有照片）」那条边界完好无损。

    代价与补救
    ----------
    本项目不碰字体光栅化（见「刻意不做」），所以**格子画不了标签**。
    补救是把版式做成机器可读的输出：stdout 上每格一行 ``[行,列]`` 映射，
    ``--json`` 给出完整的 ``tiles``（配方 / 尺寸 / 像素矩形）。

    退出码与 `render` 一致：0 成功，2 用法/输入错误。
    """
    from .canvas import Canvas
    from .scene import Scene

    raws = [str(r) for r in args.recipe]
    if "-" in raws and len(raws) > 1:
        raise ValueError("`-`（读 stdin）只能单独用：stdin 只读得到一份场景")
    if args.set and len(raws) > 1:
        raise ValueError(
            "--set 只能配单个配方用 —— 多份配方要覆盖的键十有八九不一样，"
            "套同一份覆盖会静默改错场景。请先把参数写进各自的场景 JSON 再拼。")

    # 行 = 配方，列 = 尺寸档位。这样同一行横向比档位、同一列纵向比设计。
    variants: list[tuple[str, Scene, list[tuple[int, int]]]] = []
    for raw in raws:
        scene = _load_scene(args, raw, background=None)
        variants.append((_export_stem(raw), scene,
                         _parse_sizes(getattr(args, "sizes", None), scene.size)))

    rows = len(variants)
    cols = max(len(s) for _, _, s in variants)
    cell_w = max(w for _, _, ss in variants for w, _ in ss)
    cell_h = max(h for _, _, ss in variants for _, h in ss)
    gap = int(args.gap) if args.gap else max(8, round(min(cell_w, cell_h) / 16))
    pad = gap
    sheet_w = pad * 2 + cols * cell_w + (cols - 1) * gap
    sheet_h = pad * 2 + rows * cell_h + (rows - 1) * gap
    if sheet_w * sheet_h > _SHEET_MAX_PIXELS:
        raise ValueError(
            f"联络表会到 {sheet_w}x{sheet_h}"
            f"（{sheet_w * sheet_h / 1e6:.1f} MP），超过上限 "
            f"{_SHEET_MAX_PIXELS / 1e6:.0f} MP —— 请减少档位 / 配方数，"
            f"或把最大档调小（尺寸是硬约束，这里不会替你缩）。")

    sheet = Canvas(sheet_w, sheet_h)
    bg = args.background
    if bg is None or str(bg).lower() in ("checker", "棋盘", "棋盘格"):
        sheet.paint(_checker_field(sheet_w, sheet_h, args.checker, *_SHEET_CHECKER))
    elif str(bg).lower() not in ("none", "transparent", "透明"):
        sheet.fill(bg)
    if rows > 1 or cols > 1:                               # 一格时画线纯属噪音
        for c in range(1, cols):
            x = pad + c * (cell_w + gap) - gap
            sheet.rect(x, 0, gap, sheet_h, _SHEET_SEPARATOR)
        for r in range(1, rows):
            y = pad + r * (cell_h + gap) - gap
            sheet.rect(0, y, sheet_w, gap, _SHEET_SEPARATOR)

    tiles: list[dict] = []
    for r, (name, scene, sizes) in enumerate(variants):
        base = scene.to_dict()
        for c, (w, h) in enumerate(sizes):
            arr = Scene.from_dict({**base, "size": [w, h]}).render().to_rgba8()
            # 居中摆放：格子统一成最大档，小档原地不动（**不缩放、不重采样**）
            x = pad + c * (cell_w + gap) + (cell_w - w) // 2
            y = pad + r * (cell_h + gap) + (cell_h - h) // 2
            sheet.blit(arr, x, y)
            tiles.append({"row": r, "col": c, "recipe": name, "size": [w, h],
                          "at": [x, y]})

    out = args.out or "sheet.png"
    sheet.save(out)
    layout = {"out": str(out), "sheet_size": [sheet_w, sheet_h],
              "cell": [cell_w, cell_h], "gap": gap, "pad": pad,
              "rows": rows, "cols": cols, "tiles": tiles}
    if args.json:
        print(json.dumps(layout, ensure_ascii=False, indent=2))
        return 0
    for t in tiles:
        print(f"  ✅ [{t['row']},{t['col']}] {t['recipe']} "
              f"{t['size'][0]}x{t['size'][1]} → ({t['at'][0]}, {t['at'][1]})")
    print(f"\n✅ {out}  {sheet_w}x{sheet_h} · {rows} 行 × {cols} 列 · "
          f"单格 {cell_w}x{cell_h}（尺寸按真实像素摆，未缩放）")
    print(f"   行 = 配方（{rows} 个）· 列 = 尺寸档位（{cols} 档）· "
          f"每格居中；尺寸档从大到小摆最便于横向比较。")
    print("   ℹ️ 格子没有标签（本项目不画文字）—— 行列表见上面的映射，"
          "或加 --json 拿机器可读的 tiles。")
    return 0


def _cmd_validate(args) -> int:
    """**只校验不渲染** —— 省掉 agent 一轮"生成 → 渲染 → 看报错 → 改"的循环。

    校验内容：DSL 版本 / 顶层键 / 尺寸 / 动词与图案是否存在 / 参数名与类型 /
    图层混合模式 / 后端能力是否满足。用 ``--backend svg`` 可以**提前**知道
    这份场景能不能出矢量，而不必真渲染一次再失败。
    """
    from .blend import is_mode
    from .scene import Scene
    from .svg import SvgBackend

    problems: list[str] = []
    try:
        scene = _load_scene(args)
    except (KeyError, ValueError, TypeError) as exc:
        problems.append(_error_payload(exc)["error"]["message"])
        scene = None

    report: dict = {"valid": False, "problems": problems, "warnings": [],
                    "requires": [], "size": None, "ops": 0, "layers": 0}
    if scene is not None:
        report.update(size=list(scene.size), ops=len(scene.all_ops()),
                      layers=len(scene.layers),
                      requires=sorted(scene.requires()))
        for i, layer in enumerate(scene.layers):
            if not is_mode(layer.blend):
                problems.append(f"第 {i + 1} 层的混合模式 {layer.blend!r} 不存在")
            if not 0.0 <= layer.opacity <= 1.0:
                problems.append(f"第 {i + 1} 层的 opacity={layer.opacity} 超出 0–1")
        backend = None
        if args.backend == "svg":
            backend = SvgBackend(*scene.size)
        elif args.backend is None and args.assume_svg:
            backend = SvgBackend(*scene.size)
        if backend is not None:
            try:
                scene.check_backend(backend)
            except UnsupportedOperation as exc:
                problems.append(str(exc).splitlines()[0].removeprefix("后端 "))
        if not scene.layers:
            report["warnings"].append("场景没有任何图层：会输出一张纯底色（或全透明）的图")
    report["valid"] = not problems
    report["problems"] = problems

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        head = "✅ 校验通过" if report["valid"] else "❌ 校验未通过"
        print(f"{head}  （{report['ops']} 个 op · {report['layers']} 层 · "
              f"尺寸 {report['size']}）")
        for p in report["problems"]:
            print(f"  ❌ {p}")
        for w in report["warnings"]:
            print(f"  ⚠️ {w}")
        if report["requires"]:
            print(f"  需要后端能力：{', '.join(report['requires'])}")
    return 0 if report["valid"] else 2


def _cmd_spec(args) -> int:
    """能力清单 —— 给 AI agent 的自述文件（agent 靠它发现能力，而不是靠猜）。

    ``--only`` 是关键：全量清单约 49 KB，而 agent 通常只想问"这一个图案/动词
    需要哪些参数"。``spec --json --only marble`` 会降到 1 KB 量级。
    """
    from .manifest import capability_manifest

    man = capability_manifest(with_examples=not args.no_examples)
    only = {str(k) for k in (args.only or ())}
    if only:
        unknown = only - set(man["patterns"]) - set(man["verbs"])
        if unknown:
            raise KeyError(f"--only 里有不存在的名字 {sorted(unknown)}"
                           f"（可用图案 {len(man['patterns'])} 个、动词 {len(man['verbs'])} 个）")
        man["patterns"] = {k: v for k, v in man["patterns"].items() if k in only}
        man["verbs"] = {k: v for k, v in man["verbs"].items() if k in only}
    if args.kind == "pattern":
        man["verbs"] = {}
    elif args.kind == "verb":
        man["patterns"] = {}
    if args.category:
        cat = args.category
        man["patterns"] = {k: v for k, v in man["patterns"].items()
                           if v["category"] == cat}
        man["verbs"] = {k: v for k, v in man["verbs"].items() if v["category"] == cat}
    man["filtered"] = bool(only or args.kind != "all" or args.category)

    if args.json:
        print(json.dumps(man, ensure_ascii=False, indent=2 if args.pretty else None))
        return 0
    if man["filtered"]:
        for kind, items in (("图案", man["patterns"]), ("动词", man["verbs"])):
            for key, info in sorted(items.items()):
                print(f"{key}  [{info['category']}]  {info['summary']}")
                for name, p in info["params"].items():
                    print(f"  --{name:<14} {p['type']:<6} 默认 {p['default']!r:<14} {p['doc']}")
        if not man["patterns"] and not man["verbs"]:
            print("（没有匹配项）")
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
    print("清单较大时可缩小：`spec --json --only marble` 或 `--kind verb`。")
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
            print(f"  ✅ {cat}__{p.key}.png" + (" + .svg" if svg_name else ""))

    # 清理上一轮遗留：图案改名或**换分类**时，旧文件不会被覆盖 ——
    # 上一次把 natural 类的图案从 texture 改过来，就留下了 4 个同名孤儿文件。
    # 只清理符合本命令命名规范（<分类>__<key>.<ext>）且本轮没产出的文件，不碰用户自己的文件。
    produced = {c[2] for c in cards} | {c[3] for c in cards if c[3]}
    known_cats = set(by_category())
    stale = [f for f in out_dir.iterdir()
             if f.is_file() and f.suffix.lower() in (".png", ".svg")
             and f.name not in produced
             and f.stem.split("__", 1)[0] in known_cats
             and "__" in f.stem]
    for f in stale:
        f.unlink()
        print(f"  清理陈旧文件 {f.name}")

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


def _cmd_serve(args) -> int:
    """本地调参台（浏览器里拖滑块看效果）。

    它补的是 MCP 的另一半：MCP 服务 agent，调参台服务人 ——
    两边产出的都是**同一个场景 JSON**，所以手工调好的参数能直接给 agent / CLI / 存进 git。
    """
    from .playground import DEFAULT_HOST, DEFAULT_PORT, main as serve_main

    argv = ["--port", str(args.port), "--host", args.host]
    if args.no_open:
        argv.append("--no-open")
    return serve_main(argv)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pixsmith",
        description="程序化生成背景 / 底纹 / 装饰件 PNG（零素材、可复现）",
    )
    p.add_argument("--version", action="version", version=f"pixsmith {__version__}")
    p.add_argument("--json-errors", action="store_true",
                   help="错误输出为机器可读的 JSON（便于 agent 按行解析）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="列出全部图案")
    s.add_argument("--json", action="store_true", help="以 JSON 输出")
    s.set_defaults(func=_cmd_list)

    s = sub.add_parser("show", help="查看某个图案或动词的参数说明")
    s.add_argument("pattern", help="图案名或动词名；用 all 看全部图案")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_show)

    s = sub.add_parser("validate", help="只校验场景，不渲染（省一轮往返）")
    s.add_argument("recipe", help="场景 JSON / 配方 / 图案名 / - 读 stdin")
    s.add_argument("-o", "--out", help="仅为与 render 参数对齐，validate 不写文件")
    s.add_argument("--size", help="画布尺寸 WxH（配合图案名写法时用）")
    s.add_argument("--background", help="底色")
    s.add_argument("--set", action="append", metavar="K=V", help="覆盖图案参数")
    s.add_argument("--backend", choices=["raster", "svg"],
                   help="顺带检查该后端是否满足全部能力需求")
    s.add_argument("--assume-svg", action="store_true",
                   help="按矢量后端校验（等价于 --backend svg，对 agent 更顺手）")
    s.add_argument("--json", action="store_true", help="输出机器可读结果")
    s.set_defaults(func=_cmd_validate)

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

    s = sub.add_parser("export",
                       help="批量导出：多尺寸 + 矢量 + 两种单色墨（做图标 / 标识用）")
    s.add_argument("recipe", help="场景 JSON 路径 / 配方路径 / 图案名 / - 读 stdin")
    s.add_argument("-o", "--out", help="输出目录（默认当前目录）")
    s.add_argument("--name", help="输出文件名主干（默认从输入派生）")
    s.add_argument("--sizes", metavar="LIST",
                   help="尺寸列表，如 512,64,32,16（方图）或 800x600,1200x630；"
                        "省略则只用场景自己的尺寸")
    s.add_argument("--svg", action="store_true",
                   help="另外出一份矢量（按最大档尺寸）")
    s.add_argument("--mono", metavar="COLOR",
                   help="单色·深墨版（印浅底），如 '#0A1730'")
    s.add_argument("--mono-light", metavar="COLOR",
                   help="单色·白墨版（压深底），如 '#FFFFFF' —— "
                        "只做深墨版等于漏了一半：深墨压在深底上就是没画")
    s.add_argument("--size", help="场景基础尺寸 WxH（省略 --sizes 时使用）")
    s.add_argument("--background", help="底色，如 '#0A1730' 或 '#00000000'")
    s.add_argument("--set", action="append", metavar="K=V",
                   help="覆盖图案参数（可多次）")
    s.add_argument("--report", action="store_true",
                   help="打印自检报告（按最大档尺寸）")
    s.set_defaults(func=_cmd_export)

    s = sub.add_parser("sheet",
                       help="联络表：把多个配方 × 多个尺寸摆进同一张图，一图看全")
    s.add_argument("recipe", nargs="+",
                   help="一个或多个场景 JSON / 配方 / 图案名；- 读 stdin（只能单独用）")
    s.add_argument("-o", "--out", help="输出 PNG（默认 sheet.png）")
    s.add_argument("--sizes", metavar="LIST",
                   help="尺寸阶梯，如 512,64,32,16（每个配方都套这份，建议大到小）；"
                        "省略则各用自己场景的尺寸")
    s.add_argument("--size", help="场景基础尺寸 WxH（配合图案名写法时用）")
    s.add_argument("--background", metavar="COLOR",
                   help=f"**整张表**的底色（默认 {_SHEET_CHECKER[0]}/"
                        f"{_SHEET_CHECKER[1]} 棋盘格，好让透空区显形）；"
                        f"填 none 透空，或给色值如 '#0A1730'")
    s.add_argument("--checker", type=int, default=8, help="棋盘格边长 px（默认 8）")
    s.add_argument("--gap", type=int, help="格子间距与外边距（默认取最大档的 1/16）")
    s.add_argument("--set", action="append", metavar="K=V",
                   help="覆盖图案参数（只能配单个配方用）")
    s.add_argument("--json", action="store_true",
                   help="只输出**版式图** JSON（行列 → 配方 / 尺寸 / 像素矩形），给 agent 读")
    s.set_defaults(func=_cmd_sheet)

    s = sub.add_parser("spec", help="能力清单（给 AI agent 的自述文件）")
    s.add_argument("--json", action="store_true", help="机器可读的完整清单")
    s.add_argument("--pretty", action="store_true", help="JSON 缩进美化（默认紧凑，省 token）")
    s.add_argument("--no-examples", action="store_true",
                   help="不附带每个图案的最小可用场景")
    s.add_argument("--only", action="append", metavar="KEY",
                   help="只要这些图案/动词（可多次）—— 把 49KB 清单压到 1KB 的关键")
    s.add_argument("--kind", choices=["all", "pattern", "verb"], default="all",
                   help="只列图案或只列动词")
    s.add_argument("--category", help="按分类过滤：background|texture|natural|shape|festive")
    s.set_defaults(func=_cmd_spec)

    s = sub.add_parser("new", help="生成一个图案骨架（贡献新素材时用）")
    s.add_argument("key", help="图案名（小写字母/数字/下划线，如 my_texture）")
    s.add_argument("--category", help="分类：background|texture|natural|shape|festive")
    s.add_argument("-o", "--out", help="写入文件（省略则打到 stdout）")
    s.set_defaults(func=_cmd_new)

    s = sub.add_parser("serve", help="本地调参台：拖滑块看效果，一键复制场景 JSON")
    s.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"端口（默认 {DEFAULT_PORT}；被占用会自动 +1 找空位）")
    s.add_argument("--host", default=DEFAULT_HOST,
                   help=f"监听地址（默认 {DEFAULT_HOST}；填 0.0.0.0 会暴露到局域网，谨慎）")
    s.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    s.set_defaults(func=_cmd_serve)

    s = sub.add_parser("gallery", help="一次渲染全部图案 + 生成 HTML 索引")
    s.add_argument("-o", "--out", help="输出目录（默认 gallery/）")
    s.add_argument("--size", help="单张尺寸 WxH（默认 640x400）")
    s.add_argument("--svg", action="store_true",
                   help="为支持矢量后端的图案**额外**产出 .svg（演示双后端）")
    s.add_argument("--no-html", action="store_true", help="只出图，不生成 index.html")
    s.set_defaults(func=_cmd_gallery)
    return p


def _error_payload(exc: BaseException) -> dict:
    """异常 → 机器可读的错误对象。

    ``str(KeyError)`` 会给消息**额外套一层引号**（``"没有名为 'x' 的图案"``），
    对人是小事，对按行解析 stderr 的 agent 是噪音 —— 所以统一取 ``args[0]``。
    """
    msg = exc.args[0] if exc.args and isinstance(exc.args[0], str) else str(exc)
    return {"error": {"type": type(exc).__name__, "message": msg}}


def _emit_error(exc: BaseException, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(_error_payload(exc), ensure_ascii=False), file=sys.stderr)
    else:
        print(f"❌ {_error_payload(exc)['error']['message']}", file=sys.stderr)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (KeyError, ValueError, TypeError, OSError,
            json.JSONDecodeError, UnsupportedOperation) as exc:
        # UnsupportedOperation 继承 RuntimeError，**不会**被上面任何一个的父类覆盖 ——
        # 漏掉它，最友好的那句报错（换后端/换方案）就会连整段栈一起塞进 traceback，
        # 而 agent 最容易踩到的正是"想输出 SVG"这条路径。
        _emit_error(exc, as_json=getattr(args, "json_errors", False))
        return 2
