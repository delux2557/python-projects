"""素材层：图案注册表。

一个「图案」= 一段会用后端画东西的函数 + 一份**参数声明**。
参数声明不是装饰：CLI 校验、帮助文本、AI 能力清单**都从它生成**（见 `params.py`）。

    @pattern("gradient", "线性渐变底色", [Param("begin", "color", "#0A1730")])
    def gradient(backend, *, begin, end, ...): ...

三条分层纪律
------------
1. **参数必须声明**，不许藏在函数默认值里 —— 否则 `pixsmith show` 与 `spec --json` 会漏掉它。
2. **只调用后端协议里的方法**，不要自己拼像素。这样同一份图案在 PNG 与 SVG 两个后端
   上都能跑；一旦直接操作 `numpy` 数组，这个图案就被**锁死在位图后端上**
   （确需如此时用 `requires=(...)` 显式声明，让能力校验能提前拦住）。
3. **图案不负责尺寸与底色** —— 那是 Scene 的事。图案只管往给定后端上画。
"""

from __future__ import annotations

from ..params import Param, Registry, Spec, make_registry

__all__ = ["Param", "Pattern", "REGISTRY", "pattern", "get", "names",
           "by_category", "describe", "Spec", "Registry"]

# 兼容旧名：Pattern 就是通用的 Spec
Pattern = Spec

REGISTRY, pattern = make_registry("图案")


def get(key: str) -> Spec:
    return REGISTRY.get(key)


def names() -> list[str]:
    return REGISTRY.names()


def by_category() -> dict[str, list[Spec]]:
    return REGISTRY.by_category()


def describe(key: str) -> str:
    return REGISTRY.get(key).describe()


# 触发各图案模块的注册（必须在 REGISTRY 建好之后导入）
from . import (backgrounds, festive, geometry, natural,  # noqa: E402,F401
               textures)
