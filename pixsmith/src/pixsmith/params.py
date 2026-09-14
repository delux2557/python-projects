"""参数声明：能力层的**唯一**参数描述方式。

为什么单独成模块
----------------
`patterns`（素材层）与 `ops`（能力层的动词）都需要"声明参数 + 类型转换 + 生成帮助文本"。
如果让 `ops` 去 `import patterns`，依赖方向就反了 —— 素材依赖能力，不是反过来。
所以把这份最小公共契约抽到这里，两边都只依赖它。

`Param` 同时承担三件事，这也是它值得被声明式定义的理由：
  1. **CLI 校验**：`--set k=v` 的值按 type 转换，错了立刻报
  2. **文档生成**：`pixsmith show <x>` 的帮助文本直接从这里长出来
  3. **能力清单**：`pixsmith spec --json` 把它喂给 AI agent
一句声明，三处消费 —— 少写一处就会不同步。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = ["Param", "Spec", "Registry", "make_registry"]

_COLORISH = ("color", "stops", "points", "any")


@dataclass(frozen=True)
class Param:
    """一个参数的声明。``type`` ∈ color | int | float | bool | str | size | stops。"""

    name: str
    type: str
    default: Any = None
    doc: str = ""

    def coerce(self, raw):
        """把外部输入（CLI 字符串 / JSON 值）转成正确类型；``None`` 表示取默认值。"""
        if raw is None:
            return self.default
        t = self.type
        if t in _COLORISH:
            return raw if not isinstance(raw, str) else str(raw)
        if t in ("int", "size"):
            if t == "size" and isinstance(raw, str):
                return raw
            return int(raw)
        if t == "float":
            return float(raw)
        if t == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "yes", "on", "y")
        return str(raw)

    def to_json(self) -> dict:
        return {"type": self.type, "default": self.default, "doc": self.doc}


@dataclass(frozen=True)
class Spec:
    """一个可调用能力（图案 / 动词）的声明。"""

    key: str
    summary: str
    params: tuple[Param, ...] = ()
    fn: Any = None
    category: str = "misc"
    requires: tuple[str, ...] = ()      # 恒定需要的能力
    tags: tuple[str, ...] = field(default=())
    #: 参数相关的动态依赖：``params(dict) -> Iterable[str]``。
    #: 用于"只有某个参数被启用时才需要某能力"的情况（如 starfield 的银河带）。
    #: 没有它，就只能一律声明成需要 —— 那会把本来可用的组合也挡在门外。
    requires_fn: Any = None

    def defaults(self) -> dict:
        return {p.name: p.default for p in self.params}

    def bind(self, overrides: dict | None) -> dict:
        """默认值 + 覆盖值 → 已类型化的参数字典；不认识的键直接拒绝。"""
        overrides = dict(overrides or {})
        known = {p.name: p for p in self.params}
        unknown = set(overrides) - set(known)
        if unknown:
            raise KeyError(f"{self.key!r} 不认识参数：{sorted(unknown)}"
                           f"（可用：{sorted(known)}）")
        return {n: s.coerce(overrides.get(n, s.default)) for n, s in known.items()}

    def describe(self) -> str:
        lines = [f"{self.key}  [{self.category}]  {self.summary}"]
        if self.requires:
            lines.append(f"  需要后端能力：{', '.join(self.requires)}")
        if not self.params:
            lines.append("  （无参数）")
        for p in self.params:
            lines.append(f"  --{p.name:<14} {p.type:<6} 默认 {p.default!r:<14} {p.doc}")
        return "\n".join(lines)

    def dynamic_requires(self, bound: dict) -> set[str]:
        """把恒定声明与参数相关的动态声明合起来，得到这个具体调用真正需要的能力。"""
        need = set(self.requires)
        if self.requires_fn is not None:
            need |= set(self.requires_fn(bound) or ())
        return need

    def to_json(self) -> dict:
        return {"summary": self.summary, "category": self.category,
                "requires": list(self.requires), "tags": list(self.tags),
                "params": {p.name: p.to_json() for p in self.params}}


class Registry:
    """通用注册表：图案、动词、过滤器都走它 —— 一套机制，三种用途。"""

    def __init__(self, what: str):
        self.what = what
        self._items: dict[str, Spec] = {}

    def add(self, spec: Spec) -> Spec:
        if spec.key in self._items:
            raise ValueError(f"{self.what} key 重复注册：{spec.key!r}")
        self._items[spec.key] = spec
        return spec

    def get(self, key: str) -> Spec:
        try:
            return self._items[key]
        except KeyError:
            raise KeyError(f"没有名为 {key!r} 的{self.what}。可用：{self.names()}") from None

    def names(self) -> list[str]:
        return sorted(self._items)

    def all(self) -> list[Spec]:
        return [self._items[k] for k in self.names()]

    def by_category(self) -> dict[str, list[Spec]]:
        out: dict[str, list[Spec]] = {}
        for spec in self.all():
            out.setdefault(spec.category, []).append(spec)
        return out

    def __contains__(self, key) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)


def make_registry(what: str):
    """造一个注册表 + 对应的装饰器（同一个东西被注册两遍是 bug，这里挡住）。"""
    reg = Registry(what)

    def register(key: str, summary: str, params: Iterable[Param] = (),
                 category: str = "misc", requires: Iterable[str] = (),
                 tags: Iterable[str] = (), requires_fn=None):
        def deco(fn):
            reg.add(Spec(key=key, summary=summary, params=tuple(params), fn=fn,
                         category=category, requires=tuple(requires),
                         tags=tuple(tags), requires_fn=requires_fn))
            return fn
        return deco

    return reg, register
