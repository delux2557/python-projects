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
    """一张图的完整描述：尺寸、底色、若干层。"""

    size: tuple[int, int]
    background: str | None = None
    layers: list[Layer] = field(default_factory=list)
    note: str | None = None

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
        return cls(size=size, background=obj.get("background"), layers=layers,
                   note=obj.get("note"))

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
        check_ops(backend, expanded_requirements(self.all_ops()),
                  where="scene")

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
        return backend

    def render_to_file(self, path, backend=None, **kw) -> str:
        return self.render(backend, **kw).save(path)

    # ------------------------------------------------------------ 自检报告
    def report(self, backend=None) -> dict:
        """给 **agent 的"眼睛"**：agent 看不到图，所以需要程序化的间接反馈。

        返回的都是"能拿来判断画对没画对"的量，而不是像素统计的堆砌：
        全透明 → 一定画错了；非透明占比过低 → 大概率画到画布外了；
        主色不对 → 参数传错了。
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
        }
        if opaque.any():
            ys, xs = np.nonzero(opaque)
            rep["content_bbox"] = [int(xs.min()), int(ys.min()),
                                   int(xs.max()), int(ys.max())]
            rep["touches_edge"] = bool(xs.min() == 0 or ys.min() == 0
                                       or xs.max() == w - 1 or ys.max() == h - 1)
            rgb = arr[..., :3][opaque].astype(np.float32) / 255.0
            luma = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
            rep["mean_luma"] = round(float(luma.mean()), 4)
            rep["contrast"] = round(float(luma.std()), 4)
            rep["dominant_colors"] = _dominant_colors(arr[..., :3][opaque])
            rep["transparent_ratio"] = round(1.0 - float(opaque.mean()), 4)
        return rep


def _dominant_colors(px: np.ndarray, *, top: int = 4, bits: int = 4) -> list[str]:
    """量化后的主色（每通道保留高 ``bits`` 位）—— 用来一眼看出"颜色对不对"。"""
    if px.size == 0:
        return []
    q = (px >> (8 - bits)).astype(np.uint16)
    keys = (q[:, 0].astype(np.uint32) << (bits * 2)) | \
           (q[:, 1].astype(np.uint32) << bits) | q[:, 2].astype(np.uint32)
    vals, counts = np.unique(keys, return_counts=True)
    order = np.argsort(counts)[::-1][:top]
    out = []
    scale = 255.0 / ((1 << bits) - 1)
    for i in order:
        k = int(vals[i])
        r = (k >> (bits * 2)) & ((1 << bits) - 1)
        g = (k >> bits) & ((1 << bits) - 1)
        b = k & ((1 << bits) - 1)
        out.append("#%02X%02X%02X" % (round(r * scale), round(g * scale),
                                      round(b * scale)))
    return out
