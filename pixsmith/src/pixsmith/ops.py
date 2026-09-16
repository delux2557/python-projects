"""动词表：场景 DSL 里能写的每一个「op」。

设计取舍：**声明表 + 通用分发**，而不是给每个 op 写一个类。
----------------------------------------------------
经典 Command 模式会给每个操作一个类（`RectCommand.apply(backend)`）。在 Python 里
那意味着十几份只有一行 `getattr` 的样板类。这里换一种等价但更省的写法：

    声明表（本文件）     op 名 → 参数 schema + 需要哪些后端能力
    通用分发（apply_ops）op 名 → getattr(backend, op 名)(**args)

命令对象仍然是数据（一个 dict），所以可序列化、可校验、可 diff；
**只是不再需要一个类来承载"执行"这件事** —— 执行就是一次按名字的方法查找。

    {"op": "rect", "x": 10, "y": 20, "w": 100, "h": 40, "fill": "#C8102E", "radius": 8}
    {"op": "blur", "radius": 18}
    {"op": "pattern", "pattern": "starfield", "params": {"count": 400, "seed": 7}}

参数为什么是**扁平**的（不用 `{"args": {...}}`）
------------------------------------------------
agent 写 DSL 是按 token 付费的。扁平写法省一层嵌套，也更好读：

    {"op":"rect","x":0,"y":0,"w":10,"h":10}   ← 少 3 个 token / 一层缩进
`op` 是保留键，其余键都是参数。
"""

from __future__ import annotations

import numpy as np  # noqa: F401  （类型提示用）

from .backend import (DRAW_METHODS, FRAME_METHODS, GRADIENT_METHODS,
                      UNARY_METHODS)
from .params import Param, Registry, Spec

__all__ = ["VERBS", "OP_KEYS", "PATTERN_OP_KEYS", "apply_ops",
           "expanded_requirements", "check_verbs", "DRAW_VERBS", "FILTER_VERBS",
           "RESERVED"]

VERBS = Registry("动词")

#: 保留键：不当作参数传给后端
RESERVED = ("op", "note")
#: 场景 JSON 允许的顶层键（`pattern`/`params` 是"等价旧配方"的语法糖）
OP_KEYS = ("dsl", "size", "aspect", "background", "layers", "ops", "note",
           "pattern", "params", "transform")
#: `pattern` 元 op 允许的顶层键 —— 图案自己的参数必须嵌在 `params` 里。
#: 多出来的键**一律报错**，理由见 `_check_pattern_keys`。
PATTERN_OP_KEYS = ("op", "note", "pattern", "params")


def _declare(key: str, summary: str, params: list[Param], category: str,
             requires: tuple[str, ...] = ()):
    """登记一个动词。``fn=None`` 是有意的 —— 执行由 `apply_ops` 按名字分发。"""
    VERBS.add(Spec(key=key, summary=summary, params=tuple(params), fn=None,
                   category=category, requires=requires))


_C = lambda name, default, doc: Param(name, "color", default, doc)      # noqa: E731
_F = lambda name, default, doc: Param(name, "float", default, doc)      # noqa: E731
_I = lambda name, default, doc: Param(name, "int", default, doc)        # noqa: E731
_B = lambda name, default, doc: Param(name, "bool", default, doc)       # noqa: E731


# ------------------------------------------------------------------ 帧
_declare("fill", "整幅填色", [_C("color", "#0A1730", "填充色（8 位 hex）")], "frame")

# ------------------------------------------------------------------ 图元
_declare("rect", "轴对齐矩形（按重叠面积抗锯齿）", [
    _F("x", 0.0, "左上 x"), _F("y", 0.0, "左上 y"),
    _F("w", 100.0, "宽"), _F("h", 100.0, "高"),
    _C("color", "#FFFFFFFF", "填充色"), _I("radius", 0, "圆角半径 px")], "draw")
_declare("disc", "圆", [
    _F("cx", 0.0, "圆心 x"), _F("cy", 0.0, "圆心 y"), _F("r", 50.0, "半径"),
    _C("color", "#FFFFFFFF", "填充色"), _F("feather", 1.0, "边缘羽化宽度（1=常态）")], "draw")
_declare("ring", "圆环", [
    _F("cx", 0.0, "圆心 x"), _F("cy", 0.0, "圆心 y"),
    _F("r_out", 60.0, "外半径"), _F("r_in", 45.0, "内半径"),
    _C("color", "#FFFFFFFF", "环色"), _F("feather", 1.0, "羽化宽度")], "draw")
_declare("ellipse", "椭圆（可旋转）", [
    _F("cx", 0.0, "中心 x"), _F("cy", 0.0, "中心 y"),
    _F("rx", 60.0, "横半轴"), _F("ry", 30.0, "纵半轴"),
    _C("color", "#FFFFFFFF", "填充色"), _F("ang", 0.0, "旋转角（度）")], "draw")
_declare("capsule", "胶囊线段（两端半圆，任意角）", [
    _F("x0", 0.0, "起点 x"), _F("y0", 0.0, "起点 y"),
    _F("x1", 100.0, "终点 x"), _F("y1", 0.0, "终点 y"),
    _F("r", 4.0, "半宽"), _C("color", "#FFFFFFFF", "颜色")], "draw")
_declare("arc", "环段（角度用弧度，y 向下）", [
    _F("cx", 0.0, "圆心 x"), _F("cy", 0.0, "圆心 y"),
    _F("r_out", 60.0, "外半径"), _F("r_in", 45.0, "内半径"),
    _F("a0", 0.0, "起始角"), _F("a1", 3.14159, "结束角"),
    _C("color", "#FFFFFFFF", "颜色")], "draw")
_declare("polygon", "任意多边形（奇偶规则 + 超采样）", [
    Param("points", "points", None, "顶点列表 [[x,y], ...]"),
    _C("color", "#FFFFFFFF", "填充色"), _I("ss", 3, "超采样倍数（越大越平滑）")], "draw")
_declare("line", "折线（逐段胶囊，天然圆头）", [
    Param("points", "points", None, "顶点列表 [[x,y], ...]"),
    _F("width", 4.0, "线宽"), _C("color", "#FFFFFFFF", "颜色")], "draw")
_declare("regular_polygon", "正 N 边形", [
    _F("cx", 0.0, "中心 x"), _F("cy", 0.0, "中心 y"), _F("r", 50.0, "外接圆半径"),
    _I("sides", 6, "边数"), _C("color", "#FFFFFFFF", "填充色"),
    _F("ang", -90.0, "起始角（-90 = 顶点朝上）")], "draw")
_declare("star", "正 N 角星", [
    _F("cx", 0.0, "中心 x"), _F("cy", 0.0, "中心 y"), _F("r", 50.0, "外接圆半径"),
    _I("points", 5, "角数"), _C("color", "#FFE9AF", "填充色"),
    _F("ang", -90.0, "第一个尖角的方向（-90 = 朝正上）"),
    _F("inner", 0.382, "内接半径比例（0.382 = 标准五角星）")], "draw")
_declare("erase_disc", "抠透明圆孔", [
    _F("cx", 0.0, "圆心 x"), _F("cy", 0.0, "圆心 y"), _F("r", 20.0, "半径"),
    _F("feather", 1.0, "羽化宽度")], "draw")

# ------------------------------------------------------------------ 渐变
_declare("linear_gradient", "线性渐变铺满整幅", [
    _C("begin", "#0A1730", "起始色"), _C("end", "#C8102E", "结束色"),
    _F("angle", 90.0, "角度：0=从左到右，90=从上到下"),
    _C("mid", None, "中段色（可选）"), _F("mid_at", 0.5, "中段色位置 0–1")], "gradient")
_declare("radial_gradient", "径向渐变铺满整幅", [
    _C("inner", "#F2C14E", "中心色"), _C("outer", "#0A1730", "边缘色"),
    _F("cx", None, "中心 x（省略取画布中心）"), _F("cy", None, "中心 y"),
    _F("radius", None, "渐变半径（省略取到最远角）")], "gradient")

# ------------------------------------------------------------------ 一元算子
_declare("blur", "高斯模糊（盒式×3 近似，alpha 感知）", [
    _F("radius", 12.0, "模糊半径（约 2σ）"), _I("passes", 3, "盒式次数")], "filter")
_declare("adjust", "调色（1.0 = 原样）", [
    _F("brightness", 1.0, "亮度倍数"), _F("contrast", 1.0, "对比度倍数"),
    _F("saturation", 1.0, "饱和度倍数（0=去色）"), _F("hue", 0.0, "色相旋转（度）"),
    _F("gamma", 1.0, "伽马校正")], "filter")
_declare("posterize", "色阶量化（海报效果）", [
    _I("levels", 6, "每通道保留档数（≥2）")], "filter")
_declare("solarize", "曝光过度（亮于阈值取反）", [
    _F("threshold", 0.5, "阈值 0–1")], "filter")
_declare("invert", "反相（alpha 不变）", [], "filter")
_declare("grayscale", "去色（0=原样、1=全灰）", [
    _F("amount", 1.0, "去色强度 0–1")], "filter")
_declare("grain", "胶片颗粒（seed 保证可复现）", [
    _F("amount", 0.05, "颗粒强度"), _I("seed", 0, "随机种子"),
    _B("mono", True, "灰度颗粒（false = 彩色）")], "filter",
    requires=("grain",))

# ------------------------------------------------------------------ 几何变换
_declare("transform", "整幅仿射变换（旋转/等比缩放/平移/镜像/取景）——**不改画布尺寸**", [
    _F("rotate", 0.0, "旋转角（度，正 = 屏幕上顺时针）"),
    _F("scale", 1.0, "等比缩放倍数（必须 > 0；镜像请用 flip）"),
    Param("translate", "points", None, "[dx, dy] 平移（px）"),
    Param("pivot", "points", None, "[x, y] 旋转/缩放的支点（默认画布中心）"),
    Param("flip", "str", "none", "镜像：none | h（左右）| v（上下）| both"),
    Param("crop", "points", None,
          "[x, y, w, h] 取景区铺满整张画布；取景比例≠画布比例时即为非等比拉伸"),
], "transform")

DRAW_VERBS = tuple(k for k in VERBS.names()
                   if k in DRAW_METHODS or k in GRADIENT_METHODS or k in FRAME_METHODS)
FILTER_VERBS = tuple(k for k in VERBS.names() if k in UNARY_METHODS)


# ------------------------------------------------------------------ 分发
def _split(op: dict) -> tuple[str, dict]:
    if not isinstance(op, dict):
        raise TypeError(f"op 必须是对象，收到 {type(op).__name__}")
    name = op.get("op")
    if not name:
        raise KeyError(f"op 缺少 'op' 字段：{op!r}")
    args = {k: v for k, v in op.items() if k not in RESERVED}
    return str(name), args


def _check_pattern_keys(i: int, args: dict, spec) -> None:
    """校验 `pattern` 元 op 的**顶层键**。

    为什么必须单独查（这个洞很隐蔽）：
    `apply_ops` 对 pattern 只做 `spec.bind(args.get("params"))` ——
    也就是说**只有 `params` 会被 bind，op 上其它键既不 bind 也不报错，直接被丢掉**。
    于是 `{"op": "pattern", "pattern": "star", "points": 3}`
    （参数忘了嵌进 `params`）会渲染成功、退出码 0，而 `points` 根本没生效。
    这正好踩中项目的立身之本「不静默降级」：agent 拿到 exit 0 和一张
    参数没生效的图，会当成成功结果继续往下走 —— 它没有眼睛，看不出图不对。

    场景顶层键、图层键、动词名、动词参数名都已经是严格校验的，
    这里补上最后一层，四层才对称。`spec` 为 None 时（图案不存在）
    只报未知键，注册与否由 `check_verbs` 上游负责。
    """
    extra = set(args) - set(PATTERN_OP_KEYS)
    if not extra:
        return
    bad = sorted(extra)
    msg = f"[{i}] pattern op 不认识键 {bad}（可用：{list(PATTERN_OP_KEYS)}）"
    if spec is not None:
        known = {p.name for p in spec.params}
        # 名字对、层级错 —— 最常犯的一种，专门给一句可直接照抄的提示
        misplaced = [k for k in bad if k in known]
        if misplaced:
            msg += (f"\n    → {'、'.join(misplaced)} 是 {spec.key!r} 的合法参数，"
                    f"但要嵌在 params 里："
                    f"{{'op': 'pattern', 'pattern': {spec.key!r}, "
                    f"'params': {{{misplaced[0]!r}: …}}}}")
    raise KeyError(msg)


def check_verbs(ops) -> None:
    """校验 op 名合法（动词表里有，或是指向已注册图案的 `pattern` 元 op）。

    **在构造场景时就查，不等渲染** —— 早一步报错，agent 就少一次"生成→跑→修"的循环。
    """
    from .patterns import REGISTRY as PATTERNS
    for i, op in enumerate(ops):
        name, args = _split(op)
        if name == "pattern":
            key = args.get("pattern")
            if not key:
                raise KeyError(f"[{i}] pattern op 缺少 'pattern' 字段")
            if str(key) not in PATTERNS:
                raise KeyError(f"[{i}] 没有名为 {key!r} 的图案（可用：{PATTERNS.names()}）")
            _check_pattern_keys(i, args, PATTERNS.get(str(key)))
            continue
        if name not in VERBS:
            raise KeyError(f"[{i}] 未知动词 {name!r}（可用：{VERBS.names()}）")


def apply_ops(backend, ops) -> None:
    """把一串 op 依次作用到后端上。

    - 每个 op 的参数先过 `Spec.bind()`（类型转换 + 未知键拒绝）
    - `pattern` 元 op 的顶层键也过一遍 `_check_pattern_keys()`（它只 bind `params`，
      不查的话顶层多余键会被静默丢掉）
    - 然后按名字分发给后端 —— 这就是全部的"执行"逻辑
    """
    from .patterns import REGISTRY as PATTERNS
    for i, op in enumerate(ops):
        name, args = _split(op)
        if name == "pattern":
            key = args.get("pattern")
            if not key:
                raise KeyError(f"[{i}] pattern op 缺少 'pattern' 字段")
            spec = PATTERNS.get(str(key))
            _check_pattern_keys(i, args, spec)
            spec.fn(backend, **spec.bind(args.get("params")))
            continue
        spec = VERBS.get(name)
        try:
            getattr(backend, name)(**spec.bind(args))
        except AttributeError as exc:      # pragma: no cover - 由 check_ops 提前拦
            raise AttributeError(
                f"[{i}] 后端 {type(backend).__name__} 没有实现动词 {name!r}") from exc


def expanded_requirements(ops) -> list[dict]:
    """给每个 op 补上 `_requires`（动词自身 + 引用图案的**动态**声明），供 `check_ops` 使用。

    图案的依赖可以是**参数相关**的（见 `Spec.requires_fn`）：
    例如 `starfield` 只有在 `milky > 0` 时才需要位图能力 —— 按默认参数它其实是双后端通用的。
    """
    from .patterns import REGISTRY as PATTERNS
    out = []
    for op in ops:
        name, args = _split(op)
        need: set[str] = set()
        if name == "pattern":
            key = args.get("pattern")
            if key and str(key) in PATTERNS:
                spec = PATTERNS.get(str(key))
                need |= spec.dynamic_requires(spec.bind(args.get("params")))
            need.discard("pattern")
        else:
            spec = VERBS.get(name)
            need.add(name)
            need |= spec.dynamic_requires(spec.bind(args))
        out.append({**op, "_requires": sorted(need)})
    return out
