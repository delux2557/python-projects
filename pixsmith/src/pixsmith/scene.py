"""场景：图层树 + op 序列 + 双后端渲染。

三层职责，各管各的
------------------
    Canvas / SvgBackend    会画（能力层）
    patterns / ops         画什么（素材层与词汇层）
    Scene                  画在哪儿、叠几层、怎么合（编排层）

Scene 是唯一知道"图层、不透明度、混合模式、画布尺寸"的地方；
后端完全不知道有图层这回事（它只会 `new_layer()` + `composite()`）。
这样加后端不用理解图层，改图层不用碰后端。

JSON 形态（**面向 agent：扁平、可省、token 最省**）
--------------------------------------------------
    {
      "dsl": 1,
      "size": [1920, 1080],           // 或 "1920x1080"；或给 "aspect":"16:9"
      "background": "#0A1730",
      "layers": [
        [ {"op":"linear_gradient","begin":"#0A1730","end":"#C8102E"} ],   // 裸数组 = 一层
        {"blend":"multiply", "opacity":0.6, "ops":[ {"op":"pattern","pattern":"noise"} ]}
      ]
    }
三处语法糖都是为了少打字：`ops`（单层）、裸数组（一层）、顶层 `pattern`（等价旧配方）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .backend import check_ops
from .ops import OP_KEYS, apply_ops, check_verbs, expanded_requirements
from .patterns._util import fit_size

__all__ = ["Layer", "Scene", "DEFAULT_ASPECT_WIDTH"]

DSL_VERSION = 1
DEFAULT_ASPECT_WIDTH = 1920
_LAYER_KEYS = ("ops", "blend", "opacity", "note")
_ASPECTS = {"16:9": (16, 9), "9:16": (9, 16), "4:3": (4, 3), "3:2": (3, 2),
            "2:3": (2, 3), "1:1": (1, 1), "21:9": (21, 9), "1.414:1": (1414, 1000)}


def _parse_aspect(a) -> tuple[int, int]:
    s = str(a).replace("：", ":").replace("／", "/")
    if s in _ASPECTS:
        aw, ah = _ASPECTS[s]
    else:
        parts = s.split(":")
        if len(parts) != 2:
            raise ValueError(f"宽高比写法不合法：{a!r}（如 '16:9'）")
        aw, ah = float(parts[0]), float(parts[1])
    w = DEFAULT_ASPECT_WIDTH
    return w, max(1, int(round(w * ah / aw)))


@dataclass
class Layer:
    """一层：一串 op + 图层级的不透明度与混合模式。

    **不透明度与混合模式只存在于图层一级，op 一级没有。**
    这不是遗漏 —— 想要"某个 op 带透明度"，就把它单独放一层。
    规则越少，agent 越难写错。
    """

    ops: list[dict] = field(default_factory=list)
    blend: str = "normal"
    opacity: float = 1.0
    note: str | None = None

    def __post_init__(self) -> None:
        # 构造即校验：未知动词/图案在这里就报，不留到渲染时
        check_verbs(self.ops)

    @classmethod
    def from_obj(cls, obj) -> "Layer":
        if isinstance(obj, (list, tuple)):
            return cls(ops=[dict(o) for o in obj])
        if not isinstance(obj, dict):
            raise TypeError(f"层必须是数组或对象，收到 {type(obj).__name__}")
        unknown = set(obj) - set(_LAYER_KEYS)
        if unknown:
            raise KeyError(f"层里有不认识的键 {sorted(unknown)}（可用：{list(_LAYER_KEYS)}）")
        ops = obj.get("ops") or []
        if not isinstance(ops, list):
            raise TypeError("层的 ops 必须是数组")
        return cls(ops=[dict(o) for o in ops], blend=str(obj.get("blend", "normal")),
                   opacity=float(obj.get("opacity", 1.0)), note=obj.get("note"))

    def to_dict(self) -> dict:
        out: dict = {}
        if self.blend != "normal":
            out["blend"] = self.blend
        if self.opacity != 1.0:
            out["opacity"] = self.opacity
        if self.note:
            out["note"] = self.note
        out["ops"] = list(self.ops)
        return out


@dataclass
class Scene:
    """一张图的完整描述：尺寸、底色、若干层、可选的整幅变换。

    ``transform`` 与图层里写的 ``{"op": "transform"}`` 语义**不同，也不冗余**：

    ==============================  ==========================================
    场景级 ``transform``             作用在**最终合成结果**上 →「整幅图的姿态」
    图层里的 ``{"op":"transform"}``  作用在**该层已绘内容**上 →「画 A → 转 30° → 画 B」
    ==============================  ==========================================

    为什么不能只留图层里的那个：多层场景里**没有"最后"这个位置** ——
    每层各画进自己的子画布再 `composite` 上来，op 只能影响它所在那一层。
    所以「把整张成品转 15°」这个需求必须由场景级字段承接。
    """

    size: tuple[int, int]
    background: str | None = None
    layers: list[Layer] = field(default_factory=list)
    note: str | None = None
    #: 整幅仿射变换（`transform` 动词的同名参数），在全部图层合成**之后**套用。
    #: 存**原始 dict**（不是 `bind()` 归一化后的结果）—— 归一化会把每个参数的默认值
    #: 都填进去，`to_dict()` 就不是忠实往返了。
    transform: dict | None = None

    # ------------------------------------------------------------ 构造
    @classmethod
    def from_dict(cls, obj: dict) -> "Scene":
        if not isinstance(obj, dict):
            raise TypeError("场景必须是对象")
        unknown = set(obj) - set(OP_KEYS)
        if unknown:
            raise KeyError(f"场景里有不认识的顶层键 {sorted(unknown)}"
                           f"（可用：{list(OP_KEYS)}）")
        ver = obj.get("dsl", DSL_VERSION)
        if int(ver) != DSL_VERSION:
            raise ValueError(f"不支持的 DSL 版本 {ver}（本版只认 {DSL_VERSION}）")

        if "size" in obj:
            size = fit_size(obj["size"])
        elif "aspect" in obj:
            size = _parse_aspect(obj["aspect"])
        else:
            raise KeyError("场景缺少 'size'（或 'aspect'）")

        layers: list[Layer] = []
        if "layers" in obj:
            raw = obj["layers"]
            if not isinstance(raw, list):
                raise TypeError("layers 必须是数组")
            layers = [Layer.from_obj(x) for x in raw]
        if "ops" in obj:                                   # 语法糖：单层
            layers.append(Layer(ops=[dict(o) for o in obj["ops"]]))
        if "pattern" in obj:                               # 语法糖：等价旧配方
            layers.append(Layer(ops=[{"op": "pattern", "pattern": obj["pattern"],
                                      "params": dict(obj.get("params") or {})}]))

        # 场景级 transform：**构造时就校验**，不留到渲染 ——
        # 和 `Layer.__post_init__` 里那句 `check_verbs` 同一个理由：早一步报错，
        # agent 就少一次"生成 → 跑 → 改"的循环。
        tf = obj.get("transform")
        if tf is not None:
            if not isinstance(tf, dict):
                raise TypeError(f"场景的 transform 必须是对象，收到 {type(tf).__name__}")
            from .ops import VERBS
            VERBS.get("transform").bind(tf)                # 未知键/类型错误在这里就炸
            tf = dict(tf)
        return cls(size=size, background=obj.get("background"), layers=layers,
                   note=obj.get("note"), transform=tf)

    @classmethod
    def from_json(cls, text: str) -> "Scene":
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_file(cls, path) -> "Scene":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    # ------------------------------------------------------------ 序列化
    def to_dict(self, *, compact: bool = False) -> dict:
        out: dict = {"dsl": DSL_VERSION, "size": list(self.size)}
        if self.background is not None:
            out["background"] = self.background
        # transform 要在 compact 的提前 return **之前**写 —— 它是"整幅图"的属性，
        # 和单层/多层无关，漏在这里就会静默丢掉（`export --sizes` 正是靠 to_dict 传下去的）
        # `is not None` 而不是真值判断：`{}` 是合法的恒等变换，
        # 真值判断会让它静默消失，`to_dict()` 就不是忠实往返了
        if self.transform is not None:
            out["transform"] = dict(self.transform)
        if compact:                                        # 单层且无混合 → 直接铺开
            if len(self.layers) == 1 and self.layers[0].blend == "normal" \
                    and self.layers[0].opacity == 1.0:
                out["ops"] = self.layers[0].ops
                return out
        out["layers"] = [ly.to_dict() for ly in self.layers]
        if self.note:
            out["note"] = self.note
        return out

    def to_json(self, *, compact: bool = False, indent: int = 2) -> str:
        return json.dumps(self.to_dict(compact=compact), ensure_ascii=False,
                          indent=indent)

    # ------------------------------------------------------------ 查询
    def all_ops(self) -> list[dict]:
        return [op for ly in self.layers for op in ly.ops]

    def requires(self) -> set[str]:
        """本场景用到的全部后端能力 —— 由 op 与图案**自己声明**聚合而来。"""
        need: set[str] = set()
        for item in expanded_requirements(self.all_ops()):
            need |= set(item.get("_requires") or ())
        return need

    def check_backend(self, backend) -> None:
        """渲染前预检：后端缺能力就直接报错（不静默降级，见 `backend.py`）。"""
        ops = expanded_requirements(self.all_ops())
        if self.transform is not None:
            # 场景级 transform 不是 op，不带 `_requires` —— 手工补一条进来，
            # 否则"后端不支持它"这件事会被漏检（现在两个后端都支持，但别靠这个巧合）
            ops = ops + [{"op": "transform", "_requires": ["transform"]}]
        check_ops(backend, ops, where="scene")

    # ------------------------------------------------------------ 渲染
    def render(self, backend=None):
        """渲染到任意后端。省略 ``backend`` 时用位图后端（`canvas.Canvas`）。

        - 单层且无混合：直接画在目标后端上（零拷贝的快路径）
        - 多层或带混合：每层先画进独立帧，再按 `blend` / `opacity` 合成
        """
        from .canvas import Canvas

        if backend is None:
            backend = Canvas(*self.size)
        if tuple(backend.size) != tuple(self.size):
            raise ValueError(f"后端尺寸 {tuple(backend.size)} 与场景 {tuple(self.size)} 不符")
        self.check_backend(backend)
        if self.background is not None:
            backend.fill(self.background)

        simple = (len(self.layers) == 1 and self.layers[0].blend == "normal"
                  and self.layers[0].opacity == 1.0)
        for layer in self.layers:
            if simple:
                apply_ops(backend, layer.ops)
                continue
            sub = backend.new_layer()
            apply_ops(sub, layer.ops)
            backend.composite(sub, layer.blend, layer.opacity)
        # 场景级变换：在**全部图层合成之后**套用 —— 这才是"整幅图"的姿态
        if self.transform is not None:
            from .ops import VERBS
            backend.transform(**VERBS.get("transform").bind(self.transform))
        return backend

    def render_to_file(self, path, backend=None, **kw) -> str:
        return self.render(backend, **kw).save(path)

    # ------------------------------------------------------------ 自检报告
    def report(self, backend=None) -> dict:
        """给 **agent 的"眼睛"**：agent 看不到图，所以需要程序化的间接反馈。

        ⚠️ 这份报告最容易误导人的地方是 ``dominant_colors``：
        它回答的是「**哪种颜色占的面积最多**」，而 agent 真正想问的是
        「**我的参数生效了吗**」。两者不是一回事 —— 对角渐变的颜色分布是**梯形**的，
        中间调占面积最多，所以 top-4 必然全是中间调，中国红一个都进不去，
        看起来像参数传错了。**渐变本身完全没问题。**

        所以除了主色，另外给两个**直接回答"参数生效没"**的探针：

        - ``channel_range``：每个通道的最小/最大值跨度 —— 你设了红渐变，R 就该有跨度
        - ``corner_colors``：四角取样 —— 渐变端点与方向的直接证据

        并且在主色集中度低时，报告会**自己给出 ``hints``**，而不是指望 agent 去翻文档。
        """
        from .canvas import Canvas

        b = backend if backend is not None else self.render()
        if not isinstance(b, Canvas):
            raise TypeError("report() 目前只支持位图后端（矢量后端没有像素可统计）")
        arr = b.to_rgba8()
        h, w = arr.shape[:2]
        alpha = arr[..., 3].astype(np.float32) / 255.0
        opaque = alpha > 0.02
        rep: dict = {
            "size": [w, h],
            "layers": len(self.layers),
            "ops": len(self.all_ops()),
            "requires": sorted(self.requires()),
            "opaque_ratio": round(float(opaque.mean()), 4),
            "fully_transparent": bool(opaque.sum() == 0),
            "transparent_ratio": round(1.0 - float(opaque.mean()), 4),
        }
        hints: list[str] = []

        if opaque.any():
            ys, xs = np.nonzero(opaque)
            rep["content_bbox"] = [int(xs.min()), int(ys.min()),
                                   int(xs.max()), int(ys.max())]
            rep["touches_edge"] = bool(xs.min() == 0 or ys.min() == 0
                                       or xs.max() == w - 1 or ys.max() == h - 1)
            rgb8 = arr[..., :3][opaque]
            rgb = rgb8.astype(np.float32) / 255.0
            luma = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
            rep["mean_luma"] = round(float(luma.mean()), 4)
            rep["contrast"] = round(float(luma.std()), 4)

            # 探针一：通道跨度 —— 直接回答"颜色参数生效了吗"
            rep["channel_range"] = {
                ch: [int(rgb8[:, i].min()), int(rgb8[:, i].max())]
                for i, ch in enumerate("rgb")}
            # 探针二：四角取样 —— 渐变端点与方向的直接证据（内缩 2px 躲开抗锯齿边）
            rep["corner_colors"] = {
                "tl": _hex_at(arr, 2, 2), "tr": _hex_at(arr, w - 3, 2),
                "bl": _hex_at(arr, 2, h - 3), "br": _hex_at(arr, w - 3, h - 3),
            }
            dom, coverage = _dominant_colors(rgb8)
            rep["dominant_colors"] = dom
            # dominant_coverage = **最多的那一种颜色**占多少像素（不是 top-4 之和）。
            # 阈值 0.25 是实测出来的，不是拍的：
            #   纯色 100% · 纯色+图形 98.7% · 条纹 50.3% · 棋盘 50.5% · 星空 90.5%
            #     ↑ 这些都有"主色"，报出来有意义
            #   渐变 118° 12.9% · 渐变 90° 8.4% · 三色渐变 18.4% · 大理石 19.2%
            #     ↑ 这些是连续场，根本没有"主色"
            # 注意别用 top-4 之和来判：星空 top-4 高达 94.8%，可它明明是噪点类。
            rep["dominant_coverage"] = round(coverage, 3)
            if coverage < 0.25:
                hints.append(
                    f"主色覆盖率低（最多的颜色只占 {coverage:.0%} 像素）："
                    "这张图**没有**「主色」，多半是渐变或噪声类。"
                    "别用 dominant_colors 判断颜色参数是否生效 —— "
                    "请看 channel_range（通道跨度）与 corner_colors（四角取样）。")
            if rep["opaque_ratio"] < 0.05:
                hints.append(
                    f"非透明像素仅占 {rep['opaque_ratio']:.1%}：内容可能大部分画到画布外了，"
                    "或者尺寸/坐标写错。")
        else:
            hints.append("整幅全透明：参数没生效，或全部画到了画布外。")

        if hints:
            rep["hints"] = hints
        return rep


def _hex_at(arr: np.ndarray, x: int, y: int) -> str:
    """取某点的 ``#RRGGBB``（越界自动夹取）。"""
    h, w = arr.shape[:2]
    xi = min(max(int(x), 0), w - 1)
    yi = min(max(int(y), 0), h - 1)
    return "#%02X%02X%02X" % tuple(int(v) for v in arr[yi, xi, :3])


def _dominant_colors(px: np.ndarray, *, top: int = 4, bits: int = 4
                     ) -> tuple[list[str], float]:
    """量化后的主色 + **主色覆盖率**。

    ``coverage`` 是**最多的那一种颜色**占的像素比例（不是 top-N 之和）——
    它是判断"这张图到底有没有主色"的唯一可靠依据，见 `report()` 里的阈值说明。
    """
    if px.size == 0:
        return [], 0.0
    q = (px >> (8 - bits)).astype(np.uint16)
    keys = (q[:, 0].astype(np.uint32) << (bits * 2)) | \
           (q[:, 1].astype(np.uint32) << bits) | q[:, 2].astype(np.uint32)
    vals, counts = np.unique(keys, return_counts=True)
    order = np.argsort(counts)[::-1][:top]
    scale = 255.0 / ((1 << bits) - 1)
    out = []
    for i in order:
        k = int(vals[i])
        out.append("#%02X%02X%02X" % (
            round(((k >> (bits * 2)) & ((1 << bits) - 1)) * scale),
            round(((k >> bits) & ((1 << bits) - 1)) * scale),
            round((k & ((1 << bits) - 1)) * scale)))
    top_order = np.argsort(counts)[::-1]
    coverage = float(counts[top_order[0]]) / float(counts.sum())
    return out, coverage
