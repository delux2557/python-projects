"""MCP 服务器冒烟：起一个**真实子进程**走完整个握手 + 三个工具。

单元测试是喂 JSON 给处理函数（快、能覆盖分支），这里补另一面：
**进程真的起得来吗、stdout 真的没被污染吗、控制台入口真的存在吗。**
两者缺一不可 —— 这次就是它抓出"少了 `__main__` 守卫导致静默退出 0"的。

    python tools/mcp_smoke.py            # 用 python -m pixsmith.mcp_server
    python tools/mcp_smoke.py --console  # 用装好的 pixsmith-mcp 入口

退出码 0 = 全通过。
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _messages() -> list[dict]:
    return [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "spec", "arguments": {"only": ["marble"]}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "validate", "arguments": {
             "scene": {"dsl": 1, "size": [64, 64], "ops": [{"op": "grain"}]},
             "backend": "svg"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "render", "arguments": {"scene": {
             "dsl": 1, "size": [400, 260],
             "ops": [{"op": "linear_gradient", "begin": "#0A1730", "end": "#C8102E",
                     "angle": 118},
                    {"op": "pattern", "pattern": "marble", "params": {"seed": 7}}]}}}},
        # 工具级失败必须是 isError，而不是把进程打挂
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "render", "arguments": {
             "scene": {"dsl": 1, "size": [16, 16], "ops": [{"op": "没有这个动词"}]}}}},
    ]


def main() -> int:
    use_console = "--console" in sys.argv
    if use_console:
        exe = shutil.which("pixsmith-mcp") or shutil.which("pixsmith-mcp.exe")
        if not exe:
            print("❌ 找不到 pixsmith-mcp 入口（先 pip install -e .）", file=sys.stderr)
            return 1
        cmd = [exe]
    else:
        cmd = [sys.executable, "-m", "pixsmith.mcp_server"]

    out_dir = Path(tempfile.mkdtemp(prefix="pixsmith-mcp-smoke-"))
    env = dict(os.environ, PIXSMITH_MCP_OUT=str(out_dir),
               PYTHONIOENCODING="utf-8", PYTHONPATH=str(ROOT / "src"))
    payload = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in _messages())

    print(f"启动：{' '.join(cmd)}")
    proc = subprocess.run(cmd, input=payload, capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=180)

    fails: list[str] = []
    if proc.returncode != 0:
        fails.append(f"退出码 {proc.returncode}")
    lines = [x for x in proc.stdout.splitlines() if x.strip()]
    if len(lines) != 6:
        fails.append(f"响应条数 {len(lines)}，应为 6（通知不回应）")
    replies: dict = {}
    for ln in lines:
        try:
            d = json.loads(ln)                 # 每一行都必须是干净 JSON
        except json.JSONDecodeError as exc:
            fails.append(f"stdout 不是纯 JSON：{exc}；行={ln[:80]!r}")
            continue
        if "id" in d:
            replies[d["id"]] = d

    r1 = replies.get(1, {}).get("result", {})
    if r1.get("serverInfo", {}).get("name") != "pixsmith":
        fails.append("initialize 没回 serverInfo")
    if not r1.get("instructions"):
        fails.append("initialize 缺 instructions（agent 的规程就在那里）")

    tool_names = [t["name"] for t in replies.get(2, {}).get("result", {}).get("tools", [])]
    if tool_names != ["spec", "validate", "render"]:
        fails.append(f"tools/list 工具集不对：{tool_names}")

    spec = json.loads(replies.get(3, {}).get("result", {}).get("content", [{}])[0].get("text", "{}"))
    if list(spec.get("patterns", {})) != ["marble"]:
        fails.append("spec --only marble 没生效")

    val = json.loads(replies.get(4, {}).get("result", {}).get("content", [{}])[0].get("text", "{}"))
    if val.get("valid") is not False or not any("grain" in p for p in val.get("problems", [])):
        fails.append(f"validate 没挡住 svg 上的 grain：{val}")

    r5 = replies.get(5, {}).get("result", {})
    blocks = r5.get("content", [])
    if [b.get("type") for b in blocks] != ["text", "image"]:
        fails.append(f"render 内容块不对：{[b.get('type') for b in blocks]}")
    else:
        meta = json.loads(blocks[0]["text"])
        png = base64.b64decode(blocks[1]["data"])
        if not Path(meta["path"]).exists():
            fails.append(f"render 说写了 {meta['path']}，但文件不在")
        if png[:8] != b"\x89PNG\r\n\x1a\n":
            fails.append("预览不是合法 PNG")
        if not meta.get("report", {}).get("channel_range"):
            fails.append("report 缺 channel_range 探针")

    r6 = replies.get(6, {}).get("result", {})
    if r6.get("isError") is not True:
        fails.append("无效动词应当返回 isError:true（模型才看得见原因）")

    if proc.stderr.strip():
        noisy = [x for x in proc.stderr.splitlines() if x.strip()]
        print(f"stderr（{len(noisy)} 行，正常：日志走这里）")

    print(f"\n产物目录：{out_dir}（{len(list(out_dir.iterdir()))} 个文件）")
    if fails:
        print("\n❌ 冒烟失败：")
        for f in fails:
            print(f"  • {f}")
        return 1
    print("\n✅ 冒烟通过：握手 / 工具集 / spec 过滤 / validate 拦截 / render 预览 / isError 分层")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
