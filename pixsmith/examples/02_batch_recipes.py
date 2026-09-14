"""示例 2：把配方当**配置文件**用 —— 批量出一套风格一致的底图。

这是这个项目真正的用法：一次定好参数，批量产出几十张风格统一的底图，
而不是去图库里一张张挑、再一张张调色。

    python examples/02_batch_recipes.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pixsmith import render, to_json          # noqa: E402

OUT = ROOT / "output" / "batch"
SIZE = [1920, 1080]

# 同一套配色，换图案 → 风格统一的系列底图
PALETTE = {
    "deep": "#0A1730",
    "red": "#C8102E",
    "gold": "#F2C14E",
    "cyan": "#4FD1C5",
}

SERIES = [
    {"pattern": "gradient", "params": {"begin": PALETTE["deep"],
                                       "end": PALETTE["red"], "angle": 118}},
    {"pattern": "stripes", "params": {"c0": PALETTE["deep"], "c1": "#132244",
                                       "count": 30, "angle": 60, "soft": 0.18}},
    {"pattern": "grid", "params": {"bg": PALETTE["deep"], "line": "#27456E",
                                   "major": PALETTE["gold"], "step": 60}},
    {"pattern": "dots", "params": {"bg": PALETTE["deep"], "dot": "#27456E",
                                   "cell": 56, "radius": 7}},
    {"pattern": "ray_burst", "params": {"bg": PALETTE["deep"], "count": 90,
                                        "color": PALETTE["gold"], "length": 0.55}},
    {"pattern": "starfield", "params": {"bg": "#05070F", "count": 800,
                                        "seed": 7, "milky": 0.1}},
    {"pattern": "halftone", "params": {"bg": "#F7F0E2", "dot": PALETTE["deep"],
                                       "cell": 30, "mode": "radial"}},
    {"pattern": "perspective_grid", "params": {"bg": PALETTE["deep"],
                                               "line": PALETTE["cyan"]}},
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    for i, item in enumerate(SERIES, 1):
        recipe = {"pattern": item["pattern"], "size": SIZE,
                  "params": item["params"]}
        name = f"{i:02d}_{item['pattern']}"
        render(recipe).save(OUT / f"{name}.png")
        (OUT / f"{name}.json").write_text(to_json(recipe), encoding="utf-8")
        print(f"  ✅ {name}.png + .json")
    dt = time.perf_counter() - t0

    # 顺手证明「可复现」：同配方重渲染，字节应完全一致
    r = json.loads((OUT / "01_gradient.json").read_text(encoding="utf-8"))
    first = render(r).to_png()
    second = render(r).to_png()
    ok = first == second
    print(f"\n共 {len(SERIES)} 张，耗时 {dt:.2f}s（{dt / len(SERIES) * 1000:.0f} ms/张）")
    print(f"可复现校验（同配方两次渲染字节一致）：{'✅ 通过' if ok else '❌ 失败'}")
    print(f"产物目录：{OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
