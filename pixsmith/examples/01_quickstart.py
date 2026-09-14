"""示例 1：用 Python API 画一张底图（最常用的两种写法）。

    python examples/01_quickstart.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pixsmith import Canvas, render          # noqa: E402

OUT = ROOT / "output" / "examples"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- 写法 A：直接调画布（适合"我就要一张渐变底"） ----
    c = Canvas(1920, 1080, "#0A1730")
    c.save(OUT / "a_gradient.png")
    print("✅ a_gradient.png  (1920x1080)")

    # ---- 写法 B：配方（适合"参数要能改、要能存下来"） ----
    recipe = {
        "pattern": "starfield",
        "size": [1920, 1080],
        "params": {"count": 700, "seed": 42, "milky": 0.12},
    }
    render(recipe).save(OUT / "b_starfield.png")
    print("✅ b_starfield.png  配方 =", recipe["pattern"], recipe["params"])

    # ---- 写法 C：自己组合图元（Canvas 就是一块能画东西的布） ----
    d = Canvas(1200, 630, "#101820")
    for i in range(72):                       # 放射光芒
        import math
        a = i * math.pi / 36
        d.capsule(600, 315, 600 + math.cos(a) * 700, 315 + math.sin(a) * 700,
                  3.0, "#F2C14E55")
    d.ring(600, 315, 240, 228, "#F2C14EFF")   # 一个圈
    d.star(600, 315, 160, 5, "#FFE9AFFF")     # 一颗星
    d.erase_disc(600, 315, 42)                # 中间抠个透明孔
    d.save(OUT / "c_composed.png")
    print("✅ c_composed.png  (图元组合 + 透明孔)")

    print(f"\n产物目录：{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
