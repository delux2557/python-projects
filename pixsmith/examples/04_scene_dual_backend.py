"""示例 4：场景 DSL + 双后端 + 自检报告。

这个示例演示"同一个场景，两种输出" —— 也是本项目最有战略价值的一点：
底图要 PNG（逐像素纹理），图示/图标要 SVG（矢量、可无损放大、PPT 原生支持）。

    python examples/04_scene_dual_backend.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pixsmith import SvgBackend, Scene      # noqa: E402

OUT = ROOT / "output" / "scene"

# 一个"汇报封面底图"场景：渐变 → 噪声 → 模糊 → 压暗 → 颗粒 → 叠一层
# 注意 op 是**扁平**的：{"op":"blur","radius":10} 而不是 {"op":"blur","args":{...}}
SCENE = {
    "dsl": 1,
    "size": [1920, 1080],
    "background": "#0A1730",
    "layers": [
        # 第 1 层：底 —— 渐变 + 模糊的大理石质感 + 暗角，最后统一叠颗粒
        {"ops": [
            {"op": "linear_gradient", "begin": "#0A1730", "end": "#1B3A63",
             "angle": 118},
            {"op": "pattern", "pattern": "marble",
             "params": {"stone": "#12314F", "vein": "#2E7BD6", "freq": 2.4,
                        "bands": 3.0, "warp": 0.14, "detail": 0.3, "seed": 7}},
            {"op": "blur", "radius": 3},
            {"op": "adjust", "brightness": 0.92, "contrast": 1.12, "saturation": 0.8},
            {"op": "pattern", "pattern": "vignette", "params": {"strength": 0.5}},
        ]},
        # 第 2 层：光 —— 过滤色后叠上去，用滤色混合让它"发光"
        {"blend": "screen", "opacity": 0.55, "ops": [
            {"op": "radial_gradient", "inner": "#F2C14E", "outer": "#00000000"},
            {"op": "pattern", "pattern": "ray_burst",
             "params": {"count": 90, "length": 0.6, "inner": 0.15,
                        "color": "#F2C14E66", "seed": 3}},
        ]},
    ],
    "note": "汇报封面底图：深蓝 → 光，用滤色层做发光",
}

# 矢量版：同一套能力，换成矢量可表达的组合（噪点纹理在矢量域没有对应物）
VECTOR_SCENE = {
    "dsl": 1,
    "size": [1280, 720],
    "layers": [
        [{"op": "linear_gradient", "begin": "#0A1730", "end": "#C8102E",
          "angle": 118}],
        [{"op": "pattern", "pattern": "grid",
          "params": {"bg": "#00000000", "line": "#FFFFFF1A", "step": 64}}],
        # 矢量版的星星是**真的矢量元素**，放大到 20 倍依然锐利
        [{"op": "pattern", "pattern": "star",
          "params": {"bg": "#00000000", "color": "#FFE9AF",
                     "cx": 300.0, "cy": 220.0, "radius": 90.0}}],
        [{"op": "pattern", "pattern": "gear",
          "params": {"bg": "#00000000", "color": "#4FD1C5",
                     "cx": 980.0, "cy": 430.0, "radius": 150.0}}],
    ],
    "note": "矢量版：渐变 + 线框 + 星形 + 齿轮，全部可无损缩放",
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- 1) 场景 → PNG（位图后端，省略 backend 即用它） ----
    portrait = Scene.from_dict(SCENE)
    path = portrait.render().save(OUT / "cover.png")
    print(f"✅ {path}")

    # ---- 2) 场景 → SVG（矢量后端） ----
    vector = Scene.from_dict(VECTOR_SCENE)
    svg_path = vector.render(SvgBackend(*vector.size)).save(OUT / "diagram.svg")
    print(f"✅ {svg_path}")

    # ---- 3) 把场景存成 JSON —— 可进 git、可 diff、可分享、可回滚 ----
    (OUT / "cover.scene.json").write_text(portrait.to_json(), encoding="utf-8")
    print(f"✅ {OUT / 'cover.scene.json'}")

    # ---- 4) 自检报告：agent 看不见图，靠这个判断"画对没画对" ----
    print("\n[自检报告]")
    print(json.dumps(portrait.report(), ensure_ascii=False, indent=2))

    # ---- 5) 可复现：同场景两次渲染必须逐字节一致 ----
    same = portrait.render().to_png() == portrait.render().to_png()
    print(f"\n可复现（两次渲染字节一致）：{'✅' if same else '❌'}")

    # ---- 6) 能力校验：矢量后端缺能力时会**报错**而不是静默降级 ----
    try:
        Scene.from_dict({"dsl": 1, "size": [64, 64],
                         "ops": [{"op": "grain", "amount": 0.2}]}) \
            .render(SvgBackend(64, 64))
    except Exception as exc:                                  # noqa: BLE001
        print(f"矢量后端拒绝 grain：{str(exc).splitlines()[0]}")
    print(f"\n产物目录：{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
