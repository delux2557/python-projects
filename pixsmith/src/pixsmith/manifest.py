"""能力清单（manifest）：**给 AI agent 看的自述文件**。

为什么必须有
------------
"agent 友好"的技术门槛不在渲染，在**可发现性**：agent 得先能"看见"有哪些能力、
每个能力的参数是什么、什么后端支持它 —— 否则它只能靠猜，猜错就得重试。
`pixsmith spec --json` 把整份能力清单一次吐出来（对标 SlickFast 的 `spec` / `explore` 工具）。

两个刻意的设计
--------------
1. **参数带默认值与类型**：agent 不需要填全参数，只填差异部分（省 token）。
2. **显式标出后端支持情况**：`"svg": false` 的能力让 agent 提前换方案，
   而不是生成完才发现渲染不了。
"""

from __future__ import annotations

from . import __version__
from .backend import RASTER_ONLY_METHODS
from .blend import blend_names
from .noise import KINDS
from .ops import VERBS
from .patterns import REGISTRY
from .scene import DEFAULT_ASPECT_WIDTH, DSL_VERSION
from .svg import SVG_CAPABILITIES

__all__ = ["capability_manifest", "SCENE_SCHEMA"]

_SCENE_HINT = {
    "dsl": DSL_VERSION,
    "size": "画布尺寸：[w, h] 或 'WxH'；也可用 aspect（如 '16:9'）代替",
    "background": "底色（可省）。8 位 hex：'#RRGGBBAA'",
    "ops": "语法糖：单层的 op 数组，等价于 layers 只有一层",
    "layers": "图层数组。每层可以是裸数组（op 列表），或 "
              "{ops:[...], blend:'multiply', opacity:0.5, note:'...'}",
    "op": "每个 op 是一个对象，'op' 键是动词名，其余键是它的参数（扁平，不嵌套）",
    "sweet": "旧的单图案配方 {pattern,params} 仍可用，会被当成一层 pattern op",
}

SCENE_SCHEMA = {
    "dsl": {"type": "int", "const": DSL_VERSION,
            "doc": "格式版本，必须写。不认识的版本会被拒绝（而不是猜着解析）"},
    "size": {"type": "size|[int,int]", "doc": _SCENE_HINT["size"]},
    "aspect": {"type": "str", "doc": "宽高比，如 '16:9'；缺省宽度 "
                                     f"{DEFAULT_ASPECT_WIDTH}px"},
    "background": {"type": "color?", "doc": _SCENE_HINT["background"]},
    "ops": {"type": "[op]", "doc": _SCENE_HINT["ops"]},
    "layers": {"type": "[layer]", "doc": _SCENE_HINT["layers"]},
}


def _backend_support(requires) -> dict:
    """某个能力对位图/矢量后端的支持情况。"""
    need = set(requires)
    return {"raster": not (need & set(RASTER_ONLY_METHODS)),
            "svg": not need}


def capability_manifest(*, with_examples: bool = True) -> dict:
    """完整能力清单。``with_examples`` 会附带每个图案的最小可用场景（agent 抄改的起点）。"""
    verbs = {}
    for spec in VERBS.all():
        entry = spec.to_json()
        entry["backend"] = _backend_support(spec.requires)
        verbs[spec.key] = entry

    patterns = {}
    for spec in REGISTRY.all():
        entry = spec.to_json()
        entry["backend"] = {"raster": True,
                            "svg": not set(spec.requires)}
        entry["dynamic"] = bool(spec.requires_fn)
        if with_examples:
            entry["minimal"] = minimal_scene(op={"op": "pattern", "pattern": spec.key})
        patterns[spec.key] = entry

    return {
        "name": "pixsmith",
        "version": __version__,
        "dsl_version": DSL_VERSION,
        "scene_schema": SCENE_SCHEMA,
        "backends": {
            "raster": {"class": "pixsmith.Canvas",
                       "output": ["png"], "note": "逐像素；支持全部能力"},
            "svg": {"class": "pixsmith.SvgBackend",
                    "output": ["svg"],
                    "unsupported": sorted(set(m for m in RASTER_ONLY_METHODS
                                              if m not in SVG_CAPABILITIES)),
                    "note": "矢量；不支持的能力会报错，不会静默降级"},
        },
        "verbs": verbs,
        "patterns": patterns,
        "blends": blend_names(),
        "noise_kinds": list(KINDS) + ["fbm"],
        "usage": {
            "one_op": {"op": "blur", "radius": 12},
            "scene": {"dsl": DSL_VERSION, "size": [1920, 1080],
                      "background": "#0A1730",
                      "ops": [{"op": "linear_gradient", "begin": "#0A1730",
                               "end": "#C8102E"},
                              {"op": "blur", "radius": 10}]},
            "layered": {"dsl": DSL_VERSION, "size": [1920, 1080],
                        "layers": [
                            [{"op": "fill", "color": "#0A1730"}],
                            {"blend": "screen", "opacity": 0.7,
                             "ops": [{"op": "pattern", "pattern": "ray_burst"}]},
                        ]},
        },
    }


def minimal_scene(op: dict) -> dict:
    """一个 op 的最小可用场景 —— agent 拿它当模板改，比读 schema 快。"""
    return {"dsl": DSL_VERSION, "size": [960, 540], "ops": [op]}
