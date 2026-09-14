"""让测试能直接 import 到 ``pixsmith`` 与 ``benchmarks``，无需先安装。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "src", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
