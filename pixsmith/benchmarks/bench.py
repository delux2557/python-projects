"""性能基准：pixsmith(NumPy) vs 纯 Python 参考实现，**同样工作量、同样参数**。

用法
----
    python benchmarks/bench.py                 # 标准档（参考实现也能跑完）
    python benchmarks/bench.py --big           # 加一组大画布（参考实现会很久，慎用）

为什么要留这个脚本：上 NumPy 是个**有代价**的决定（多一个硬依赖）。
代价必须有对应的收益，收益必须是可测量的 —— 不能是"感觉快了很多"。
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from benchmarks.pure_python_reference import PixelCanvas      # noqa: E402
from pixsmith.canvas import Canvas                        # noqa: E402
from pixsmith.color import parse_color                    # noqa: E402


def _c255(hexcolor: str) -> tuple[int, int, int, int]:
    r, g, b, a = parse_color(hexcolor)
    return (round(r * 255), round(g * 255), round(b * 255), round(a * 255))


# 每个工作负载：fn(canvas_like, to_color) -> None
WORKLOADS = {
    "圆 ×300 (512×512)": (
        (512, 512),
        lambda c, col: [c.disc(i % 512 + 0.5, (i * 7) % 512 + 0.5, 9.0,
                               col("#F2C14E90"))
                        for i in range(300)],
    ),
    "矩形 ×400 (512×512)": (
        (512, 512),
        lambda c, col: [c.rect((i * 5) % 480, (i * 11) % 480, 30.0, 18.0,
                               col("#4FD1C580"))
                        for i in range(400)],
    ),
    "正十边形 ×25 (512×512)": (
        (512, 512),
        lambda c, col: [c.polygon(
            [(256 + 180 * math.cos(math.radians(36 * k + i)),
              256 + 180 * math.sin(math.radians(36 * k + i))) for k in range(10)],
            col("#EAE2D0C0"), ss=3) for i in range(25)],
    ),
    "放射线 ×24 / 长 400px (768×768)": (
        (768, 768),
        lambda c, col: [c.capsule(
            384, 384,
            384 + 400 * math.cos(i * math.pi / 12),
            384 + 400 * math.sin(i * math.pi / 12),
            3.0, col("#F2C14E80")) for i in range(24)],
    ),
}

BIG = {
    "放射线 ×46 / 长 1300px (2560×1440)": (
        (2560, 1440),
        lambda c, col: [c.capsule(
            1280, 720,
            1280 + 1300 * math.cos(i * math.pi * 2 / 46),
            720 + 1300 * math.sin(i * math.pi * 2 / 46),
            3.0, col("#F2C14E80")) for i in range(46)],
    ),
}


def time_numpy(size, fn):
    c = Canvas(*size)
    t = time.perf_counter()
    fn(c, parse_color)
    return time.perf_counter() - t


def time_reference(size, fn):
    r = PixelCanvas(size[0], size[1], (0, 0, 0, 0))
    t = time.perf_counter()
    fn(r, _c255)
    return time.perf_counter() - t


def run(cases: dict, title: str) -> None:
    print(f"\n## {title}\n")
    print("| 工作负载 | NumPy | 纯 Python | 加速比 |")
    print("|---|---|---|---|")
    for name, (size, fn) in cases.items():
        tn = time_numpy(size, fn)
        tr = time_reference(size, fn)
        print(f"| {name} | {tn * 1000:.1f} ms | {tr * 1000:.1f} ms | "
              f"**{tr / tn:.0f}×** |")


def main() -> int:
    ap = argparse.ArgumentParser(description="pixsmith 性能基准")
    ap.add_argument("--big", action="store_true", help="加一组大画布工作负载")
    args = ap.parse_args()

    print("# pixsmith 性能基准")
    print(f"\n透明画布、单线程、同参数同工作量。加速比 = 纯 Python 耗时 / NumPy 耗时。")
    run(WORKLOADS, "标准档")
    if args.big:
        run(BIG, "大画布档（参考实现可能需要数分钟）")

    # 全画布渐变单独测：参考实现是逐像素回调，NumPy 是整场赋值
    for size in ((1920, 1080),) + (((2560, 1440),) if args.big else ()):
        w, h = size
        t = time.perf_counter()
        c = Canvas(w, h)
        import numpy as np
        tt = np.linspace(0, 1, w, dtype=np.float32)[None, :].repeat(h, axis=0)
        from pixsmith.color import gradient_stops
        c.paint(gradient_stops([(0, "#0A1730"), (1, "#C8102E")], tt))
        tn = time.perf_counter() - t

        r = PixelCanvas(w, h, (0, 0, 0, 0))
        c0, c1 = _c255("#0A1730"), _c255("#C8102E")
        t = time.perf_counter()
        for y in range(h):
            for x in range(w):
                u = x / (w - 1)
                r.over(x, y, tuple(round(c0[i] + (c1[i] - c0[i]) * u) for i in range(4)))
        tr = time.perf_counter() - t
        print(f"\n**全画布线性渐变 {w}×{h}**：NumPy {tn * 1000:.1f} ms / "
              f"纯 Python {tr * 1000:.1f} ms → **{tr / tn:.0f}×**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
