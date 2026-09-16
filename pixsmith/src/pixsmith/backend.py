"""后端协议：把「有哪些能力」与「谁来执行」解耦。

这是双后端能成立的前提
----------------------
一份图案、一段场景，凭什么能同时输出 PNG 和 SVG？因为**它们不直接碰像素**，
只调用下面这份协议里的方法名。谁实现这份协议，谁就是一种后端：

    位图后端 Canvas      (`canvas.py`)   → 逐像素，强在纹理/噪点/非线性滤镜
    矢量后端 SvgBackend  (`svg.py`)      → 写 XML，强在矢量图形/锐利缩放/可编辑

协议只约束**方法名与语义**，不约束实现（`typing.Protocol` = 结构化子类型）。
这正是设计模式里的 **Strategy**：能力是稳定的，执行策略是可替换的。

能力校验（为什么不做成"静默降级"）
----------------------------------
每个动词/图案都声明了 `requires=(...)`。渲染前 `check_ops()` 会拿后端的**方法表**
对一遍，缺什么就**直接报错并列出替代方案**。理由：静默降级会产出"看起来对但其实缺了效果"
的图，而 agent 看不见图，它只会以为自己做对了 —— 那是比报错更坏的失败。
"""

from __future__ import annotations

from typing import Any

__all__ = ["FRAME_METHODS", "DRAW_METHODS", "GRADIENT_METHODS",
           "UNARY_METHODS", "TRANSFORM_METHODS", "RASTER_ONLY_METHODS",
           "ALL_METHODS", "backend_capabilities", "check_ops",
           "UnsupportedOperation"]

# 帧与合成
FRAME_METHODS = ("fill", "new_layer", "composite", "to_png", "save")
# 图元（后端无关的几何绘制）
DRAW_METHODS = ("rect", "disc", "ring", "ellipse", "capsule", "arc", "polygon",
                "line", "regular_polygon", "star", "erase_disc")
# 渐变（后端无关：位图铺像素场，矢量写 <linearGradient>）
GRADIENT_METHODS = ("linear_gradient", "radial_gradient")
# 一元算子（对整幅已绘内容做变换）
UNARY_METHODS = ("blur", "adjust", "posterize", "solarize", "invert",
                 "grayscale", "grain")
# 几何变换（对整幅已绘内容做仿射变换）。
# 和 UNARY_METHODS 的区别只有一条：**一元算子改颜色，它改几何**。
# 两者都有"作用于目前已画内容"的语义，所以矢量端都靠 `_wrap()` 实现。
TRANSFORM_METHODS = ("transform",)
# 只有位图后端才有意义的扩展（矢量后端表达不了逐像素域）
RASTER_ONLY_METHODS = ("paint", "noise_texture", "colorfield")

ALL_METHODS = (FRAME_METHODS + DRAW_METHODS + GRADIENT_METHODS
               + UNARY_METHODS + TRANSFORM_METHODS + RASTER_ONLY_METHODS)


class UnsupportedOperation(RuntimeError):
    """后端不支持某个能力 —— 属于**用法错误**，不是运行时故障。"""


def backend_capabilities(backend: Any) -> frozenset[str]:
    """后端自报家门。优先用后端声明的 ``capabilities``，否则按方法表推断。"""
    declared = getattr(backend, "capabilities", None)
    if declared is not None:
        return frozenset(declared)
    return frozenset(m for m in ALL_METHODS if callable(getattr(backend, m, None)))


def check_ops(backend: Any, ops: list[dict], *, where: str = "") -> None:
    """预检一批 op 里用到的能力后端是否都支持；不支持就抛错。

    ``requires`` 是**声明式**的：图案/动词自己说需要什么，这里只做核对。
    这样加一种后端不需要改任何图案，加一种图案也不需要改任何后端。
    """
    have = backend_capabilities(backend)
    name = type(backend).__name__
    missing: dict[str, list[str]] = {}
    for i, op in enumerate(ops):
        verb = str(op.get("op", ""))
        need = set(op.get("_requires") or ()) | ({verb} if verb else set())
        # meta-op（pattern）由 Scene 展开后再校验，这里跳过它的内部
        if verb == "pattern":
            need.discard("pattern")
        gap = {m for m in need if m and m not in have}
        if gap:
            missing.setdefault(f"[{i}] {verb}", []).extend(sorted(gap))
    if missing:
        parts = []
        for where_, gaps in missing.items():
            verb = where_.split("] ", 1)[-1]
            if set(gaps) == {verb}:
                parts.append(f"{where_} 这个动词该后端没有")
            else:
                parts.append(f"{where_} 还缺能力 {', '.join(gaps)}")
        # ⚠️ 细节必须放在**第一行**：CLI（validate / render）只取首行做单行提示，
        # 把关键信息放到第二行等于丢掉它。
        raise UnsupportedOperation(
            f"后端 {name}{(' (' + where + ')') if where else ''} 不支持："
            + "；".join(parts)
            + f"\n  该后端支持：{', '.join(sorted(have))}"
            + "\n  可用替代：换用位图后端（pixsmith.Canvas），"
              "或改用该后端支持的效果组合。")
