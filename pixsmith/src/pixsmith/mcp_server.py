"""MCP server：把 pixsmith 的能力暴露成 MCP 工具，供任何 MCP 客户端（agent）直接调用。

为什么**手写** JSON-RPC 而不是引 `mcp` SDK
------------------------------------------
MCP 的 stdio 部分协议面很小：换行分隔的 JSON-RPC 2.0，四个方法
（``initialize`` / ``notifications/initialized`` / ``tools/list`` / ``tools/call``）。
为它引一个 SDK 会破坏本项目"只用 numpy"的承诺，还会让服务器无法离线单测。
这里约 300 行覆盖全部需要，且 `tests/test_mcp_server.py` 直接喂 JSON 就能测。

⭐ 安全边界：**只接受 JSON 场景，不接受代码**
--------------------------------------------
这个服务器**刻意只暴露"快捷通道"**（声明式 JSON），不暴露 Python 创作通道。
于是它天然没有代码执行面 —— 这正是"把能力分成两条通道"的架构回报：
需要给不可信输入一个安全沙箱时，声明式那层就是现成的沙箱。

工具设计：**少而准**（3 个）
----------------------------
`spec` 用参数收拢了「列清单 / 看单个规格 / 看最小示例」三件事，
而不是拆成 `list` + `show` + `examples` 三个工具 —— 工具描述本身也要占上下文，
重叠的工具只会让 agent 选错。

Agent 友好的几个关键决定
------------------------
1. **执行错误用 ``isError: true`` 返回，不用 JSON-RPC error** —— 前者模型能看见并自我修正，
   后者在多数客户端里会被当成传输故障，模型看不到原因。
2. **``render`` 默认回一张缩小预览图**（``embed_preview``）—— agent 看不见图是最大的障碍，
   给它一双眼睛比给它更多数字有用。
3. **``initialize`` 的 ``instructions`` 里直接写操作规程** —— 那是协议给的位置，
   不用它就得指望 agent 去翻 AGENTS.md。
4. **stdout 只走协议**：工具执行期间 ``sys.stdout`` 被重定向到 stderr，
   免得任何一句 ``print`` 污染 JSON-RPC 流。
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import sys
from pathlib import Path

import numpy as np

from . import __version__
from .filters import resize

__all__ = ["SERVER_NAME", "serve", "handle_message", "tool_definitions",
           "call_tool", "main"]

SERVER_NAME = "pixsmith"

#: 本服务器支持的协议版本；``initialize`` 时**回显客户端要的版本**（在支持列表内），
#: 否则回 ``PREFERRED`` —— 规范要求版本不匹配时优雅降级，而不是报错。
SUPPORTED_PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
PREFERRED_PROTOCOL = "2025-06-18"

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

#: 放进 ``initialize.instructions`` —— 这是协议专门给"怎么用我"留的位置。
INSTRUCTIONS = (
    f"pixsmith {__version__}：用 JSON 场景生成图片（背景 / 底纹 / 装饰件），"
    "输出 PNG（位图）或 SVG（矢量）。不联网、同 seed 必然同字节。\n"
    "\n"
    "工作循环（照这个顺序走，能省掉一半往返）：\n"
    "  1. spec --only <图案名>   先查参数名与默认值，**不要猜**\n"
    "  2. validate               只校验不渲染，提前知道能不能出矢量\n"
    "  3. render                 渲染；默认回一张缩小预览图，你能直接看见结果\n"
    "  4. 看返回的 report 判断画对没画对；不对就改，回到 2\n"
    "\n"
    "三条关键规程：\n"
    "  • render 只吃**场景 JSON**（快捷通道）。JSON 装不下的需求（循环参数化、"
    "数学几何、条件逻辑）请让调用方改用 pixsmith 的 Python API（创作通道）。\n"
    "  • 判断「颜色参数生效了吗」看 report.channel_range 与 report.corner_colors，"
    "**不要用 dominant_colors** —— 对角渐变里中间调占面积最多，它必然全是中间调。"
    "report.hints 会在容易误判时直接提示。\n"
    "  • 后端不支持某个效果时会**报错**，不会静默降级。用 validate 提前发现。\n"
    "\n"
    "场景 JSON 形态：{\"dsl\":1,\"size\":[w,h],\"background\":\"#RRGGBBAA\","
    "\"ops\":[{\"op\":\"blur\",\"radius\":8}]}；多图层用 \"layers\"。"
)

#: 输出目录：`PIXSMITH_MCP_OUT` 环境变量，缺省在服务器工作目录下开 `pixsmith-out/`。
DEFAULT_OUT_ENV = "PIXSMITH_MCP_OUT"
DEFAULT_OUT_DIR = "pixsmith-out"


# ====================================================================== 工具
def tool_definitions() -> list[dict]:
    """``tools/list`` 的返回内容。描述写给模型看，所以要交代**什么时候用**和**坑在哪**。"""
    scene_prop = {
        "type": "object",
        "description": "场景 JSON：{dsl:1, size:[w,h] 或 \"WxH\" 或 aspect, "
                       "background, ops:[...]}；多图层用 layers。"
                       "op 参数是**扁平**的，如 {\"op\":\"blur\",\"radius\":8}。",
    }
    backend_prop = {
        "type": "string", "enum": ["raster", "svg"], "default": "raster",
        "description": "raster 输出 PNG（支持全部效果）；svg 输出矢量"
                       "（更快更清晰，但逐像素类图案会被拒绝）。",
    }
    return [
        {
            "name": "spec",
            "description": (
                "查询能力清单：有哪些图案 / 动词、各自的参数名与默认值、需要哪个后端。"
                "**第一次用 pixsmith 或要写某个效果前先调它，不要猜参数名。**"
                "全量清单约 29KB，所以强烈建议用 only / kind / category 收窄 ——"
                "查单个能力只要几 KB。"),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "only": {
                        "type": "array", "items": {"type": "string"},
                        "description": "只要这些图案 / 动词的规格，例如 [\"marble\",\"blur\"]。"
                                       "这是最省 token 的用法。"},
                    "kind": {"type": "string", "enum": ["all", "pattern", "verb"],
                             "default": "all", "description": "只看图案或只看动词。"},
                    "category": {
                        "type": "string",
                        "enum": ["background", "texture", "natural", "shape", "festive"],
                        "description": "按分类过滤图案。"},
                    "include_examples": {
                        "type": "boolean", "default": False,
                        "description": "附带每个图案的**最小可用场景 JSON** —— "
                                       "想抄改某个效果时打开它，比自己拼快得多。"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "validate",
            "description": (
                "**只校验场景，不渲染**：检查 DSL 版本 / 键名 / 动词与图案是否存在 / "
                "参数名与类型 / 混合模式 / 后端能力是否满足。"
                "省掉一轮「生成 → 渲染 → 看报错 → 改」。"
                "用 backend=\"svg\" 可以提前知道这份场景能不能出矢量。"),
            "inputSchema": {
                "type": "object",
                "properties": {"scene": scene_prop, "backend": backend_prop},
                "required": ["scene"],
                "additionalProperties": False,
            },
        },
        {
            "name": "render",
            "description": (
                "渲染场景并把文件写到输出目录。返回文件路径 + **自检报告**，"
                "默认还回一张缩小预览图（你可以直接看见结果）。"
                "报告里 channel_range / corner_colors 用来判断参数是否生效，"
                "hints 会在容易误判时给出提示。"),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scene": scene_prop,
                    "backend": backend_prop,
                    "out": {
                        "type": "string",
                        "description": "输出文件名（**只能是文件名，不能带目录**）。"
                                       "省略则用 scene.png / scene.svg。扩展名会按后端自动纠正。"},
                    "embed_preview": {
                        "type": "boolean", "default": True,
                        "description": "是否附一张缩小预览图。默认开 —— 你能看见图，"
                                       "比多看十个数字有用。只支持 raster 后端。"},
                    "preview_max_px": {
                        "type": "integer", "default": 512, "minimum": 64, "maximum": 1024,
                        "description": "预览图最长边像素数。调小更省，调大看得更清。"},
                },
                "required": ["scene"],
                "additionalProperties": False,
            },
        },
    ]


def _json_text(obj) -> dict:
    return {"type": "text", "text": json.dumps(obj, ensure_ascii=False)}


def _tool_error(exc: BaseException, *, where: str = "") -> dict:
    """**工具执行错误 → ``isError: true``**，而不是 JSON-RPC error。

    这是 MCP 里一个容易搞反的点：JSON-RPC error 表示"协议/传输"层面的问题，
    多数客户端只会报一句故障，**模型看不到原因**；而 ``isError: true`` 的内容块会
    原样交给模型，它才能自己改正。
    """
    msg = exc.args[0] if exc.args and isinstance(exc.args[0], str) else str(exc)
    return {
        "content": [_json_text({"error": {"type": type(exc).__name__,
                                          "message": msg,
                                          "where": where or None}})],
        "isError": True,
    }


def _out_dir() -> Path:
    d = Path(os.environ.get(DEFAULT_OUT_ENV) or DEFAULT_OUT_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_out_name(raw, ext: str) -> str:
    """把用户给的输出名收敛成一个**安全的文件名**。

    只取 basename 并强制正确扩展名 —— 这是这个服务器唯一的文件写入面，
    所以路径穿越（``../``、绝对路径、Windows 盘符）在这里一次性挡掉。
    """
    name = str(raw or "scene").replace("\\", "/").split("/")[-1].strip()
    if not name or name.startswith("."):
        name = "scene"
    stem = name.rsplit(".", 1)[0] if "." in name else name
    stem = stem.strip() or "scene"
    return f"{stem}{ext}"


def _encode_rgba_to_png(rgba: np.ndarray) -> bytes:
    from .codec import to_png
    arr = rgba if rgba.dtype == np.uint8 else \
        (np.clip(rgba, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return to_png(np.ascontiguousarray(arr))


# ------------------------------------------------------------------ 各工具实现
def _tool_spec(args: dict) -> dict:
    from .manifest import capability_manifest

    only = {str(k) for k in (args.get("only") or [])}
    kind = str(args.get("kind") or "all")
    category = args.get("category")
    man = capability_manifest(with_examples=bool(args.get("include_examples")))
    if only:
        unknown = only - set(man["patterns"]) - set(man["verbs"])
        if unknown:
            raise KeyError(f"没有这些图案或动词：{sorted(unknown)}。"
                           f"可用图案 {sorted(man['patterns'])}；动词 {sorted(man['verbs'])}")
        man["patterns"] = {k: v for k, v in man["patterns"].items() if k in only}
        man["verbs"] = {k: v for k, v in man["verbs"].items() if k in only}
    if kind == "pattern":
        man["verbs"] = {}
    elif kind == "verb":
        man["patterns"] = {}
    if category:
        man["patterns"] = {k: v for k, v in man["patterns"].items()
                           if v["category"] == category}
        man["verbs"] = {k: v for k, v in man["verbs"].items()
                        if v["category"] == category}
    man["filtered"] = bool(only or kind != "all" or category)
    return {"content": [_json_text(man)]}


def _tool_validate(args: dict) -> dict:
    from .blend import is_mode
    from .scene import Scene
    from .svg import SvgBackend

    scene = Scene.from_dict(args["scene"])
    problems: list[str] = []
    for i, layer in enumerate(scene.layers):
        if not is_mode(layer.blend):
            problems.append(f"第 {i + 1} 层的混合模式 {layer.blend!r} 不存在")
        if not 0.0 <= layer.opacity <= 1.0:
            problems.append(f"第 {i + 1} 层的 opacity={layer.opacity} 超出 0–1")
    if args.get("backend") == "svg":
        try:
            scene.check_backend(SvgBackend(*scene.size))
        except Exception as exc:                          # noqa: BLE001
            problems.append(str(exc).splitlines()[0])
    warnings = []
    if not scene.layers:
        warnings.append("场景没有任何图层：会输出一张纯底色（或全透明）的图")
    return {"content": [_json_text({
        "valid": not problems,
        "problems": problems,
        "warnings": warnings,
        "size": list(scene.size),
        "layers": len(scene.layers),
        "ops": len(scene.all_ops()),
        "requires": sorted(scene.requires()),
    })]}


def _tool_render(args: dict) -> dict:
    from .scene import Scene
    from .svg import SvgBackend

    backend = args.get("backend") or "raster"
    scene = Scene.from_dict(args["scene"])
    ext = ".svg" if backend == "svg" else ".png"
    name = _safe_out_name(args.get("out"), ext)
    path = _out_dir() / name

    if backend == "svg":
        scene.render(SvgBackend(*scene.size)).save(path)
        out = {"path": str(path), "bytes": path.stat().st_size, "backend": "svg",
               "note": "矢量后端没有像素，因此不返回 preview 与 report —— "
                       "要自检请再用 backend=\"raster\" 渲染一次。"}
        return {"content": [_json_text(out)]}

    canvas = scene.render()
    canvas.save(path)
    out = {
        "path": str(path),
        "bytes": path.stat().st_size,
        "backend": "raster",
        "report": scene.report(canvas),
    }
    blocks = [_json_text(out)]
    if args.get("embed_preview", True):
        max_px = int(args.get("preview_max_px") or 512)
        # 预览直接缩 canvas 的浮点缓冲，不经 PNG 编解码往返
        h, w = canvas.h, canvas.w
        scale = min(1.0, max_px / max(w, h))
        small = (resize(canvas.buf, max(1, int(round(w * scale))),
                        max(1, int(round(h * scale)))) if scale < 1.0
                 else canvas.buf)
        blocks.append({"type": "image",
                       "data": base64.b64encode(_encode_rgba_to_png(small)).decode("ascii"),
                       "mimeType": "image/png"})
    return {"content": blocks}


_TOOLS = {"spec": _tool_spec, "validate": _tool_validate, "render": _tool_render}


def call_tool(name: str, arguments: dict | None) -> dict:
    """执行工具。**任何异常都变成 isError 结果**，绝不让它冒成 JSON-RPC error。"""
    fn = _TOOLS.get(str(name))
    if fn is None:
        raise KeyError(f"没有名为 {name!r} 的工具。可用：{sorted(_TOOLS)}")
    args = dict(arguments or {})
    # stdout 是协议通道：把工具执行期间的 print 全部赶到 stderr，
    # 否则将来某句不经意的 print 就会把 JSON-RPC 流冲坏（这种 bug 极难查）
    with contextlib.redirect_stdout(sys.stderr):
        return fn(args)


# ====================================================================== 协议
def _result(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": err}


def handle_message(msg: dict):
    """处理一条 JSON-RPC 消息。**返回 ``None`` 表示这是通知，不该有响应。**"""
    if not isinstance(msg, dict):
        return _error(None, JSONRPC_INVALID_REQUEST, "消息必须是 JSON 对象")
    method = msg.get("method")
    msg_id = msg.get("id")
    is_notification = "id" not in msg

    if not isinstance(method, str):
        return None if is_notification else _error(
            msg_id, JSONRPC_INVALID_REQUEST, "缺少 method 字段")

    if method == "notifications/initialized" or method.startswith("notifications/"):
        return None                                     # 通知：不回应，这是规范要求

    if method == "initialize":
        params = msg.get("params") or {}
        want = str(params.get("protocolVersion") or "")
        ver = want if want in SUPPORTED_PROTOCOLS else PREFERRED_PROTOCOL
        return _result(msg_id, {
            "protocolVersion": ver,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "instructions": INSTRUCTIONS,
        })

    if method == "ping":
        return _result(msg_id, {})

    if method == "tools/list":
        return _result(msg_id, {"tools": tool_definitions()})

    if method == "tools/call":
        params = msg.get("params") or {}
        try:
            return _result(msg_id, call_tool(params.get("name"),
                                             params.get("arguments")))
        except Exception as exc:                        # noqa: BLE001
            return _result(msg_id, _tool_error(exc, where="tools/call"))

    return _error(msg_id, JSONRPC_METHOD_NOT_FOUND, f"未知方法：{method}")


def serve(stdin=None, stdout=None, *, on_log=None) -> int:
    """stdio 主循环：**换行分隔的 JSON**，一条一行，无内嵌换行。

    ⚠️ 不要套用 LSP 的 ``Content-Length`` 分帧 —— MCP 的 stdio 不走那一套。
    """
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    log = on_log or (lambda s: print(s, file=sys.stderr))
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            resp = _error(None, JSONRPC_PARSE_ERROR, f"JSON 解析失败：{exc}")
        else:
            try:
                resp = handle_message(msg)
            except Exception as exc:                    # noqa: BLE001
                resp = _error(msg.get("id") if isinstance(msg, dict) else None,
                              JSONRPC_INTERNAL_ERROR, f"内部错误：{exc}")
        if resp is None:
            continue
        stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        stdout.flush()
    log("客户端关闭输入，pixsmith MCP 退出")
    return 0


def main(argv=None) -> int:
    """入口。``--selftest`` 打一遍工具清单，方便人肉确认没坏。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        print(f"{SERVER_NAME} mcp server v{__version__}", file=sys.stderr)
        print(f"支持的协议版本：{', '.join(SUPPORTED_PROTOCOLS)}", file=sys.stderr)
        print(f"工具：{', '.join(t['name'] for t in tool_definitions())}", file=sys.stderr)
        print(f"输出目录：{_out_dir()}", file=sys.stderr)
        return 0
    if "--version" in argv:
        print(f"{SERVER_NAME}-mcp {__version__}")
        return 0
    return serve()


# ⚠️ 这个守卫不能省：包内的 `__main__.py` 归 CLI 用（`python -m pixsmith` = 命令行），
# 所以 MCP 服务器只能靠 `python -m pixsmith.mcp_server` 启动。
# 少了它，那条命令会**静默退出 0 且零输出** —— 这种失败最难查。
if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
