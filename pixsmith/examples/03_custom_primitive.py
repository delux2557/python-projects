"""示例 3：不用内置图案，直接拿图元画一个自己的（含坐标换算的小套路）。

内置图案是起点，不是边界。这个例子里所有东西都由「圆 / 线段 / 多边形 / 抠洞」拼出来。

    python examples/03_custom_primitive.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pixsmith import Canvas, lerp, parse_color      # noqa: E402

OUT = ROOT / "output" / "examples"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    W, H = 1280, 400
    c = Canvas(W, H, "#0B1220")

    # 1) 底部光带：一层层半透明圆叠出"发光"的感觉（没有 blur，就用衰减替代）
    for i in range(28, 0, -1):
        r = 90 + i * 12
        cy = H - 40
        col = parse_color("#2E7BD6")
        c.disc(W / 2, cy, r, (col[0], col[1], col[2], 0.045), feather=r * 0.6)

    # 2) 刻度尺：让"参数化"这件事一眼可见（i 同时决定位置与高度）
    for i in range(-20, 21):
        x = W / 2 + i * 28
        major = (i % 5 == 0)
        h = 42 if major else 20
        alpha = 0.85 if major else 0.35
        col = parse_color("#9FD2FF")
        c.capsule(x, H - 40, x, H - 40 - h, 1.6 if major else 1.0,
                  (col[0], col[1], col[2], alpha))

    # 3) 一段用色阶插值画出的"数据条"
    bars = [0.35, 0.52, 0.44, 0.68, 0.61, 0.83, 0.77, 0.95]
    bw, gap = 60, 22
    for i, v in enumerate(bars):
        x = 120 + i * (bw + gap)
        h = 250 * v
        col = lerp("#4FD1C5", "#C8102E", v)            # 低→高，青→红
        c.rect(x, H - 90 - h, bw, h, col)
        c.rect(x, H - 90 - h, bw, 6, "#FFFFFFFF")      # 顶部高光

    # 4) 一个"靶心"：三次抠洞做出真透明的环
    cx, cy = W - 170, 120
    c.disc(cx, cy, 76, "#F2C14EFF")
    c.erase_disc(cx, cy, 56)
    c.disc(cx, cy, 36, "#C8102EFF")
    c.erase_disc(cx, cy, 18)

    # 5) 用多边形画一颗 9 角星（顶点全部由公式给出，外/内半径交替）
    sx, sy = 150, 90
    pts = []
    for i in range(9 * 2):
        a = math.radians(-90 + i * 20)
        rr = 34 if i % 2 == 0 else 15
        pts.append((sx + math.cos(a) * rr, sy + math.sin(a) * rr))
    c.polygon(pts, "#9B8CFAFF", ss=3)

    path = c.save(OUT / "d_custom.png")
    print(f"✅ {path}  ({W}x{H})")
    print("   全部由 圆 / 线段 / 多边形 / 抠洞 拼成，未使用任何内置图案。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
