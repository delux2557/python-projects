"""措辞检查：仓库里不得出现指向特定厂商 / 产品的字样。

⚠️ 为什么禁用词在本文件里是**转义写法**（``\\u770b\\u677f``）和**字符串拼接**
--------------------------------------------------------------------------
为了保住一条干净的不变式：**仓库里任何项目文件都不含这些词。**
要是检查脚本自己把禁用词明文写出来，"检查通过"就成了一句空话 —— 它会命中自己
（第一版就是这样：提示文案里写了禁用词，结果自己报了 4 处）。

所以：中文用 ``\\uXXXX``、ASCII 用片段拼接、**连提示文案都从表里现推**。
运行时才还原，文件里搜不到。

`CONTRIBUTING.md` 的「文字与命名禁忌」一节是唯一例外 —— 规则必须写出被禁的东西
才能用，本脚本自动跳过那一节。

用法
----
    python tools/check_wording.py            # 退出码 0 = 干净，1 = 有命中
    python tools/check_wording.py --verbose  # 连扫描范围一起打印

CI 里会跑它。**这是必须的**：曾经靠"人工记得跑一下 grep"，结果连续两次提交
都把禁用词重新写了进去（examples 与 recipes 各一次）。
凡是"跟着别处一起该变、但没人强制它变"的清单，都得有自动检查兜着。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 跳过这些目录（生成物、缓存、第三方）
SKIP_DIRS = {".git", "output", ".pytest_cache", "__pycache__", ".ruff_cache",
             ".workbuddy", "pixsmith-out", "node_modules", ".venv"}

#: 只扫文本类文件
TEXT_EXT = {".py", ".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".cfg",
            ".ini", ".html", ".css", ".js"}

#: 唯一允许出现禁用词的文件（且只允许在某一节里）
RULE_DOC = "CONTRIBUTING.md"
#: 「## 六、文字与命名禁忌」—— 同样转义写，免得本文件命中自己
RULE_SECTION_MARK = "## \u516d\u3001\u6587\u5b57\u4e0e\u547d\u540d\u7981\u5fcc"

#: 禁用词表：(词, 为什么禁, 建议改用什么)。**词一律转义 / 拼接**，参见模块 docstring。
_DENY: tuple[tuple[str, str, str], ...] = (
    ("\u5e06\u8f6f", "\u5382\u5546\u540d", "\u76f4\u63a5\u5220\u9664"),
    ("Fine" + "Report", "\u4ea7\u54c1\u540d", "\u76f4\u63a5\u5220\u9664"),
    ("fi" + "nereport", "\u4ea7\u54c1\u540d\uff08\u5c0f\u5199\uff09", "\u76f4\u63a5\u5220\u9664"),
    ("F" + "V" + "S", "\u4ea7\u54c1\u7f29\u5199", "\u76f4\u63a5\u5220\u9664"),
    ("." + "f" + "vs", "\u6587\u4ef6\u540e\u7f00", "\u76f4\u63a5\u5220\u9664"),
    ("FR" + "_HOME", "\u73af\u5883\u53d8\u91cf", "\u76f4\u63a5\u5220\u9664"),
    ("\u770b\u677f", "\u6307\u5411\u7279\u5b9a\u8f6f\u4ef6\u54c1\u7c7b",
     "\u754c\u9762\u7a3f / \u9762\u677f / \u6c47\u62a5\u6750\u6599"),
    ("\u5927\u5c4f", "\u6307\u5411\u7279\u5b9a\u8f6f\u4ef6\u54c1\u7c7b",
     "\u5927\u5e45\u9762\u753b\u9762 / \u5c55\u677f"),
    ("\u62a5\u8868", "\u6307\u5411\u7279\u5b9a\u8f6f\u4ef6\u54c1\u7c7b",
     "\u56fe\u8868 / \u6c47\u62a5\u6750\u6599"),
    ("\u8bbe\u8ba1\u5668", "\u6307\u5411\u7279\u5b9a\u8f6f\u4ef6\u54c1\u7c7b",
     "\u6392\u7248\u5de5\u5177 / \u8bbe\u8ba1\u8f6f\u4ef6"),
    ("\u9003\u751f\u901a\u9053", "\u65e7\u672f\u8bed", "\u521b\u4f5c\u901a\u9053"),
)


def _exempt_text(rel: str, text: str) -> str:
    """贡献指南只豁免「文字与命名禁忌」那一节，前面的正文照常检查。"""
    if rel != RULE_DOC:
        return text
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(RULE_SECTION_MARK):
            return "\n".join(lines[:i])
    return text


def check(*, verbose: bool = False) -> list[tuple[str, int, str, str]]:
    """返回命中列表 ``[(相对路径, 行号, 禁用词, 原因), ...]``。"""
    hits: list[tuple[str, int, str, str]] = []
    scanned = 0
    for path in sorted(ROOT.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if not path.is_file() or path.suffix.lower() not in TEXT_EXT:
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        text = _exempt_text(rel, text)
        for word, why, _fix in _DENY:
            for i, line in enumerate(text.splitlines(), 1):
                if word in line:
                    hits.append((rel, i, word, why))
    if verbose:
        print(f"扫描了 {scanned} 个文本文件（跳过 {sorted(SKIP_DIRS)}）")
    return hits


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    hits = check(verbose="--verbose" in argv)
    if not hits:
        print("\u2705 \u63aa\u8f9e\u68c0\u67e5\u901a\u8fc7\uff1a"
              "\u4ed3\u5e93\u91cc\u6ca1\u6709\u6307\u5411\u7279\u5b9a\u5382\u5546 / "
              "\u4ea7\u54c1\u7684\u5b57\u6837")
        return 0
    print(f"\u274c \u63aa\u8f9e\u68c0\u67e5\u672a\u901a\u8fc7\uff0c"
          f"\u547d\u4e2d {len(hits)} \u5904\uff1a\n")
    for rel, line, word, why in hits:
        print(f"  {rel}:{line}  \u300c{word}\u300d\uff08{why}\uff09")
    # 替代表达**从表里现推**，不在源码里硬编码（硬编码就会命中自己）
    print("\n\u6539\u7528\u4e2d\u6027\u7684\u8bf4\u6cd5\uff1a")
    for word, _why, fix in _DENY:
        print(f"  {word} \u2192 {fix}")
    print("\n\u89c4\u5219\u89c1 CONTRIBUTING.md \u7684"
          "\u300c\u6587\u5b57\u4e0e\u547d\u540d\u7981\u5fcc\u300d\u3002")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
