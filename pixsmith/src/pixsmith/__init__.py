"""pixsmith —— 程序化生成背景 / 底纹 / 装饰件，支持位图与矢量双后端。

一句话：**用代码画底图，而不是去网上找图。**

    from pixsmith import Canvas, Scene

    Canvas(1920, 1080, "#0A1730").save("bg.png")              # 直接画（手感层）

    Scene.from_dict({                                          # 场景（可序列化）
        "dsl": 1, "size": [1920, 1080], "background": "#0A1730",
        "ops": [{"op": "linear_gradient", "begin": "#0A1730", "end": "#C8102E"},
                {"op": "blur", "radius": 8}],
    }).render().save("grad.png")

架构（分层，依赖单向）
----------------------
    backend.py   协议：能力有哪些（谁实现谁就是后端）
    canvas.py    位图后端（NumPy 逐像素） ｜ svg.py  矢量后端（写 XML）
    ops.py       动词表 ｜ geometry / filters / blend / noise / field  算子与几何
    patterns/    素材（图案，只用协议方法画东西）
    scene.py     编排：尺寸 + 底色 + 图层 + 混合

三条设计取舍
------------
1. **双后端从第一天就是后端无关的**，不是事后加分叉。图案只调协议方法，
   所以 23 个图案里有 15 个在 PNG 与 SVG 上都能跑（其余 8 个是逐像素场，显式声明了为什么不能）。
2. **确定性优先于"更好看"**：同 seed 必然同字节 —— 底图能进 git、能 diff、能当测试基线。
3. **不做静默降级**：后端缺能力就报错。agent 看不见图，静默降级会让它以为做对了。
"""

from __future__ import annotations

from .blend import MODES, blend_names
from .canvas import Canvas
from .codec import to_png, write_png
from .color import gradient_stops, lerp, parse_color, to_rgba8
from .geometry import (gear_points, regular_polygon_points,
                       ring_segment_points, rounded_rect_points, star_points)
from .recipes import (DEFAULT_SIZE, list_patterns, make_recipe, render,
                      render_file, to_json)
from .scene import Layer, Scene
from .svg import SvgBackend

__version__ = "0.8.1"

__all__ = [
    "Canvas", "SvgBackend", "Scene", "Layer",
    "render", "render_file", "make_recipe", "to_json", "list_patterns",
    "DEFAULT_SIZE",
    # ⚠️ 这里**刻意不导出** `blend` 函数：包级名字 `blend` 若指向函数，
    # 就会遮蔽同名子模块 `pixsmith.blend`（`from pixsmith import blend` 拿到函数而非模块）。
    # 混合用 `pixsmith.blend.blend(...)` 或 `canvas.composite(...)`。
    "MODES", "blend_names",
    "star_points", "regular_polygon_points", "ring_segment_points",
    "gear_points", "rounded_rect_points",
    "parse_color", "to_rgba8", "lerp", "gradient_stops", "to_png", "write_png",
    "__version__",
]
