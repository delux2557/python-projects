"""配方（recipe）= 可序列化的绘图指令。

配方是这块东西**能交给非程序员**的关键：JSON 里改颜色和尺寸，不用碰 Python。

    {
      "pattern": "gradient",
      "size": [1920, 1080],
      "background": "#00000000",
      "params": {"begin": "#0A1730", "end": "#C8102E", "angle": 90}
    }
"""

from __future__ import annotations

import json
from pathlib import Path

from .canvas import Canvas
from .patterns import REGISTRY, by_category, get, names
from .patterns._util import fit_size

__all__ = ["DEFAULT_SIZE", "render", "render_file", "make_recipe", "to_json",
           "list_patterns", "recipe_from_cli"]

DEFAULT_SIZE = (1920, 1080)
_ALLOWED_KEYS = {"pattern", "size", "background", "params", "note"}


def render(recipe: dict) -> Canvas:
    """配方 dict → ``Canvas``。

    v0.2 起**统一走 `Scene`**：配方（单图案）只是场景的一个特例
    （`{"pattern":..., "params":...}` 是顶层语法糖，见 `Scene.from_dict`）。
    这样"单图案"和"多图层"不再有两套渲染路径 —— 一套代码，一种语义。
    """
    from .scene import Scene

    return Scene.from_dict(recipe).render()


def render_file(path, out=None) -> tuple[str, Canvas]:
    """读一份配方 JSON 并渲染；``out`` 给了就顺便落盘。返回 (输出路径, 画布)。"""
    src = Path(path)
    recipe = json.loads(src.read_text(encoding="utf-8"))
    c = render(recipe)
    if out is None:
        out = src.with_suffix(".png")
    written = c.save(out)
    return written, c


def make_recipe(key: str, size=None, background=None, **params) -> dict:
    """构造一份配方（参数只填**与默认值不同**的项，保持配方可读）。"""
    spec = get(key)
    defaults = spec.defaults()
    diff = {k: v for k, v in params.items() if v is not None and defaults.get(k) != v}
    unknown = set(diff) - set(defaults)
    if unknown:
        raise KeyError(f"图案 {key!r} 不认识参数：{sorted(unknown)}")
    rec: dict = {"pattern": key, "size": list(fit_size(size or DEFAULT_SIZE))}
    if background is not None:
        rec["background"] = background
    if diff:
        rec["params"] = diff
    return rec


def to_json(recipe: dict, indent: int = 2) -> str:
    return json.dumps(recipe, ensure_ascii=False, indent=indent)


def list_patterns() -> dict[str, list[str]]:
    return {cat: [p.key for p in items] for cat, items in by_category().items()}


def recipe_from_cli(key: str, size=None, background=None, sets=None) -> dict:
    """CLI 的 ``--set k=v`` 列表 → 配方 dict。"""
    spec = get(key)
    overrides = {}
    for item in (sets or []):
        if "=" not in item:
            raise ValueError(f"--set 需要 k=v 形式，收到 {item!r}")
        k, v = item.split("=", 1)
        overrides[k.strip()] = v.strip()
    bound = spec.bind(overrides)
    defaults = spec.defaults()
    rec: dict = {"pattern": key, "size": list(fit_size(size or DEFAULT_SIZE))}
    if background is not None:
        rec["background"] = background
    diff = {k: v for k, v in bound.items() if v != defaults.get(k)}
    if diff:
        rec["params"] = diff
    return rec


# 让 `from pixsmith.recipes import REGISTRY / names` 这类用法也能工作
__all__ += ["REGISTRY", "names"]
