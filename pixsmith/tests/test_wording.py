"""措辞铁律的自动守卫。

为什么要有这个文件
------------------
`tools/check_wording.py` 早就写好了，但**只靠"人工记得跑一下"** ——
结果是连续两次独立提交都把禁用词重新写了进去：
一次在 `examples/showcase/make_themes.py` 的图标用途串里（6 处），
一次在 `recipes/dashboard_2560.json` 的 note 里。

⚠️ 本文件的 docstring 也**刻意不引用**那两处的原文 —— 引用了就会被检查器抓到
（第一版就是这么挂的）。

这类约定**不会因为写进文档就自动成立**：写文档不会犯错，写代码会。
所以它必须变成一条会失败的红线，而不是一段提醒。

这个测试跑真实的命令行入口（不是 import 内部函数）—— 顺带把
"脚本本身能不能跑起来、退出码对不对"也一起验了。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "tools" / "check_wording.py"


def test_repo_has_no_vendor_specific_wording():
    assert CHECKER.exists(), f"缺少 {CHECKER.relative_to(ROOT)}"
    proc = subprocess.run([sys.executable, str(CHECKER)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(ROOT), timeout=120)
    assert proc.returncode == 0, (
        "措辞检查未通过 —— 仓库里出现了指向特定厂商 / 产品的字样：\n"
        f"{proc.stdout}\n{proc.stderr}")


def test_checker_does_not_contain_the_denylist_itself():
    """检查器自身必须一尘不染 —— 否则"检查通过"就是空话。

    第一版就踩过：提示文案里明文写了禁用词，结果脚本命中自己 4 处。
    现在中文走 ``\\uXXXX``、ASCII 走片段拼接、连提示都从表里现推。
    """
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import check_wording as cw          # noqa: PLC0415
    finally:
        sys.path.pop(0)
    raw = CHECKER.read_text(encoding="utf-8")
    for word, _why, _fix in cw._DENY:
        assert word not in raw, (
            f"检查器文件里出现了禁用词的明文 {word!r} —— "
            f"它应当用 \\u 转义或片段拼接表示")
    # 反过来也要成立：转义后的词确实还在表里（别把表写成空的糊弄过去）
    assert len(cw._DENY) >= 8
    assert cw.check() == [], "自检：仓库应当干净"
