"""文档防过期测试。

为什么需要这个文件
------------------
`docs/能力边界.md` 曾经停留在 v0.1：它写着"做不到 SVG / 矢量""没有真正的混合模式"
"没有模糊"—— 而当时的代码**已经全都有了**。

结果比"没有文档"更糟：**一份说我做不到的过期文档，会让 agent 主动放弃本来能用的能力。**
人会怀疑文档，agent 不会。

文档里的自然语言没法自动校验，但**数字和版本号可以**。
所以这里只钉两类会腐烂的东西：版本标记、能力计数。改代码忘了改文档 → 测试失败。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import pixsmith
from pixsmith.patterns import by_category, names

ROOT = Path(__file__).resolve().parent.parent
BOUNDARY = ROOT / "docs" / "能力边界.md"
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"


def _read(p: Path) -> str:
    assert p.exists(), f"缺少文件 {p.relative_to(ROOT)}"
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("doc", ["docs/能力边界.md", "AGENTS.md",
                                     "docs/31-MCP接入.md"])
def test_doc_has_version_stamp_matching_code(doc):
    """文档必须标出它对应哪个版本，且与 `__version__` 一致。"""
    text = _read(ROOT / doc)
    m = re.search(r"对应版本[：:]\s*v(\d+\.\d+\.\d+)", text)
    assert m, f"{doc} 缺少『对应版本：vX.Y.Z』标记"
    assert m.group(1) == pixsmith.__version__, (
        f"{doc} 标的是 v{m.group(1)}，代码是 v{pixsmith.__version__} —— "
        f"改了能力请同步更新文档")


def test_boundary_doc_dual_backend_counts_match_code():
    """`能力边界.md` 里「23 / 23 ｜ 15 / 23」这行必须与代码一致。

    这行最容易腐烂 —— 加一个图案就会变，而图案是最常被贡献的东西。
    """
    text = _read(BOUNDARY)
    m = re.search(r"\|\s*图案支持\s*\|\s*\*\*(\d+)\s*/\s*(\d+)\*\*\s*\|\s*\*\*(\d+)\s*/\s*(\d+)\*\*\s*\|",
                  text)
    assert m, "「能力边界.md」里找不到『图案支持 | N / N | N / N』这一行"
    raster_ok, total_r, svg_ok, total_s = (int(g) for g in m.groups())

    all_names = names()
    svg_capable = [k for k in all_names if not _requires(k)]
    assert (raster_ok, total_r) == (len(all_names), len(all_names)), \
        f"文档写位图 {raster_ok}/{total_r}，实际 {len(all_names)}/{len(all_names)}"
    assert (svg_ok, total_s) == (len(svg_capable), len(all_names)), \
        f"文档写矢量 {svg_ok}/{total_s}，实际 {len(svg_capable)}/{len(all_names)}"


def test_boundary_doc_lists_the_exact_raster_only_patterns():
    """文档点名列出了"矢量后端不支持的 8 个图案"—— 那份名单也要对得上。"""
    text = _read(BOUNDARY)
    m = re.search(r"矢量后端不支持的\s*\*{0,2}(\d+)\s*个图案\*{0,2}全是[^\n]*", text)
    assert m, "找不到『矢量后端不支持的 N 个图案』这句"
    stated = int(m.group(1))
    actual = _raster_only_names()
    assert stated == len(actual), \
        f"文档说 {stated} 个，实际 {len(actual)} 个：{sorted(actual)}"
    for key in actual:
        assert f"`{key}`" in text, f"文档点名的名单里缺 `{key}`"


def test_readme_pattern_count_matches_code():
    """README 的「图案一览（N 个，M 类）」也要对得上。"""
    text = _read(README)
    m = re.search(r"##\s*图案一览（(\d+)\s*个，(\d+)\s*类）", text)
    assert m, "README 里找不到『图案一览（N 个，M 类）』标题"
    assert int(m.group(1)) == len(names()), f"README 说 {m.group(1)} 个图案"
    assert int(m.group(2)) == len(by_category()), f"README 说 {m.group(2)} 类"


def test_agents_md_covers_the_three_operating_rules():
    """`AGENTS.md` 的存在理由是那三条操作规程 —— 少了任何一条就失去意义。"""
    text = _read(AGENTS)
    for needle, why in (
        ("快捷通道", "必须先讲清「优先 JSON 快通道，装不下再走创作通道」"),
        ("requires", "必须讲清「图案只用协议方法，逐像素要声明 requires」"),
        ("--report", "必须讲清「用 --report 自查，agent 看不见图」"),
    ):
        assert needle in text, f"AGENTS.md 缺少关于「{why}」的内容"


# ------------------------------------------------------------------ 小工具
def _requires(key: str) -> tuple:
    from pixsmith.patterns import get
    return get(key).requires


def _raster_only_names() -> set[str]:
    return {k for k in names() if _requires(k)}
