"""MCP server 的协议级测试 —— 直接喂 JSON-RPC 消息，不起子进程、不引 SDK。

覆盖三件容易写错的事：
1. **协议形状**：``initialize`` 的版本回显、``tools/list`` 的 schema、通知不回应
2. **错误分层**：工具执行失败必须是 ``isError: true``（模型能看见），
   而不是 JSON-RPC error（模型看不见）—— 这条反了很多人的直觉
3. **安全边界**：只吃 JSON、不执行代码；输出名不能穿越目录
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest

from pixsmith import __version__
from pixsmith.mcp_server import (PREFERRED_PROTOCOL, SERVER_NAME,
                                 SUPPORTED_PROTOCOLS, call_tool,
                                 handle_message, serve, tool_definitions)


def _call(method, params=None, msg_id=1):
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return handle_message(msg)


def _tool(name, arguments=None):
    resp = _call("tools/call", {"name": name, "arguments": arguments or {}})
    assert "result" in resp, resp
    return resp["result"]


# ---------------------------------------------------------------- 协议形状
def test_initialize_echoes_client_protocol_version_when_supported():
    for ver in SUPPORTED_PROTOCOLS:
        r = _call("initialize", {"protocolVersion": ver,
                                 "capabilities": {}, "clientInfo": {"name": "t"}})
        assert r["result"]["protocolVersion"] == ver, ver


def test_initialize_degrades_gracefully_on_unknown_version():
    """规范要求版本不匹配时优雅降级，而不是报错。"""
    r = _call("initialize", {"protocolVersion": "1999-01-01"})
    assert "error" not in r
    assert r["result"]["protocolVersion"] == PREFERRED_PROTOCOL


def test_initialize_reports_server_info_and_instructions():
    r = _call("initialize", {"protocolVersion": PREFERRED_PROTOCOL})
    res = r["result"]
    assert res["serverInfo"]["name"] == SERVER_NAME
    assert res["serverInfo"]["version"] == __version__
    assert res["capabilities"]["tools"] == {}
    # instructions 是"怎么用我"的官方位置 —— 三条规程必须在里面
    ins = res["instructions"]
    for needle in ("spec", "validate", "render", "channel_range", "dominant_colors"):
        assert needle in ins, f"instructions 缺少 {needle}"


def test_notifications_get_no_response():
    """通知**不能**有响应，否则客户端会把响应当成对不上号的垃圾消息。"""
    for method in ("notifications/initialized", "notifications/cancelled"):
        assert handle_message({"jsonrpc": "2.0", "method": method}) is None


def test_tools_list_schema_is_usable():
    tools = _call("tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {"spec", "validate", "render"}
    for t in tools:
        assert t["description"] and t["inputSchema"]["type"] == "object"
        # additionalProperties=false：让客户端早一步发现拼错的参数名
        assert t["inputSchema"].get("additionalProperties") is False
    render = next(t for t in tools if t["name"] == "render")
    props = render["inputSchema"]["properties"]
    assert props["embed_preview"]["default"] is True, "默认应回预览图"
    assert set(render["inputSchema"]["required"]) == {"scene"}


def test_unknown_method_and_bad_message_shapes():
    assert _call("nope")["error"]["code"] == -32601
    assert handle_message("not an object")["error"]["code"] == -32600
    assert handle_message({"jsonrpc": "2.0", "id": 1})["error"]["code"] == -32600


def test_ping_is_answered():
    assert _call("ping")["result"] == {}


def test_serve_reads_newline_delimited_json_and_skips_blank_lines():
    """stdio 是**换行分隔**的 JSON（不是 LSP 的 Content-Length 分帧）。"""
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        "",                                            # 空行应被跳过
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        "{ this is not json",                          # 解析错误
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]
    out = io.StringIO()
    serve(io.StringIO("\n".join(lines) + "\n"), out, on_log=lambda s: None)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert len(replies) == 3, f"通知不该产生响应：{replies}"
    assert replies[0]["id"] == 1 and "result" in replies[0]
    assert replies[1]["error"]["code"] == -32700
    assert replies[2]["id"] == 2


# ---------------------------------------------------------------- 错误分层
def test_tool_execution_error_is_isError_not_jsonrpc_error():
    """⭐ 工具失败要 ``isError: true`` —— 内容块会交给模型；JSON-RPC error 不会。"""
    r = _tool("render", {"scene": {"dsl": 1, "size": [16, 16],
                                   "ops": [{"op": "没有这个动词"}]}})
    assert r["isError"] is True
    assert "error" in json.loads(r["content"][0]["text"])
    # 外层仍是正常的 result，不是 JSON-RPC error
    resp = _call("tools/call", {"name": "render",
                                "arguments": {"scene": {"dsl": 1, "size": [16, 16],
                                                        "ops": [{"op": "x"}]}}})
    assert "result" in resp and "error" not in resp


def test_error_payload_is_machine_readable_and_specific():
    r = _tool("spec", {"only": ["没有这个"]})
    assert r["isError"] is True
    err = json.loads(r["content"][0]["text"])["error"]
    assert err["type"] == "KeyError"
    assert "没有这个" in err["message"]


def test_unknown_tool_name():
    r = _tool("nope")
    assert r["isError"] is True
    assert "没有名为" in json.loads(r["content"][0]["text"])["error"]["message"]


# ---------------------------------------------------------------- 各工具
def test_spec_filters_cut_the_payload_size():
    full = json.loads(_tool("spec")["content"][0]["text"])
    one = json.loads(_tool("spec", {"only": ["marble"]})["content"][0]["text"])
    assert len(full["patterns"]) > 20 and len(full["verbs"]) > 15
    assert list(one["patterns"]) == ["marble"] and one["verbs"] == {}
    assert len(json.dumps(one, ensure_ascii=False)) < \
        len(json.dumps(full, ensure_ascii=False)) / 5


def test_spec_supports_kind_and_category():
    verbs = json.loads(_tool("spec", {"kind": "verb"})["content"][0]["text"])
    assert verbs["patterns"] == {} and verbs["verbs"]
    nat = json.loads(_tool("spec", {"category": "natural"})["content"][0]["text"])
    assert set(nat["patterns"]) == {"marble", "clouds", "cracks", "brushed"}


def test_spec_include_examples_gives_copyable_minimal_scene():
    man = json.loads(_tool("spec", {"only": ["marble"],
                                   "include_examples": True})["content"][0]["text"])
    minimal = man["patterns"]["marble"]["minimal"]
    assert minimal["dsl"] == 1 and minimal["ops"][0]["pattern"] == "marble"
    # 这个最小场景必须真的能渲染 —— 参考物的价值就在"抄下来就能跑"
    r = _tool("render", {"scene": minimal, "embed_preview": False})
    assert r.get("isError") is not True


def test_validate_does_not_write_anything(tmp_path, monkeypatch):
    monkeypatch.setenv("PIXSMITH_MCP_OUT", str(tmp_path))
    out = json.loads(_tool("validate", {
        "scene": {"dsl": 1, "size": [32, 32],
                  "ops": [{"op": "blur", "radius": 3}]}})["content"][0]["text"])
    assert out["valid"] is True and out["problems"] == []
    assert out["requires"] == ["blur"]
    assert list(tmp_path.iterdir()) == [], "validate 不该产生任何文件"


def test_validate_catches_unsupported_backend_before_rendering():
    out = json.loads(_tool("validate", {
        "scene": {"dsl": 1, "size": [32, 32], "ops": [{"op": "grain"}]},
        "backend": "svg"})["content"][0]["text"])
    assert out["valid"] is False
    assert any("grain" in p for p in out["problems"])


def test_validate_reports_layer_problems():
    out = json.loads(_tool("validate", {
        "scene": {"dsl": 1, "size": [32, 32],
                  "layers": [{"blend": "nope", "opacity": 2.0, "ops": []}]}
    })["content"][0]["text"])
    assert out["valid"] is False
    assert len(out["problems"]) == 2


# ---------------------------------------------------------------- render
def test_render_returns_path_report_and_preview(tmp_path, monkeypatch):
    monkeypatch.setenv("PIXSMITH_MCP_OUT", str(tmp_path))
    r = _tool("render", {"scene": {"dsl": 1, "size": [240, 160], "background": "#0A1730",
                                   "ops": [{"op": "linear_gradient",
                                            "begin": "#0A1730", "end": "#C8102E"}]}})
    assert r.get("isError") is not True
    text = json.loads(r["content"][0]["text"])
    assert text["backend"] == "raster" and text["bytes"] > 0
    assert (tmp_path / "scene.png").exists()
    rep = text["report"]
    # 报告必须带上能回答"参数生效没"的探针
    assert rep["channel_range"]["r"][1] > 150
    assert set(rep["corner_colors"]) == {"tl", "tr", "bl", "br"}
    assert rep["hints"], "渐变场景应给出主色提示"
    # 预览图块
    img = r["content"][1]
    assert img["type"] == "image" and img["mimeType"] == "image/png"
    assert base64.b64decode(img["data"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_preview_is_downscaled():
    small = _tool("render", {"scene": {"dsl": 1, "size": [1200, 800],
                                       "ops": [{"op": "fill", "color": "#123456"}]},
                             "embed_preview": True, "preview_max_px": 200})
    raw = base64.b64decode(small["content"][1]["data"])
    assert len(raw) < 20000, f"预览应被缩小，实际 {len(raw)} 字节"


def test_render_can_skip_the_preview():
    r = _tool("render", {"scene": {"dsl": 1, "size": [32, 32], "ops": []},
                         "embed_preview": False})
    assert len(r["content"]) == 1
    assert r["content"][0]["type"] == "text"


def test_render_svg_has_no_report_and_says_why(tmp_path, monkeypatch):
    monkeypatch.setenv("PIXSMITH_MCP_OUT", str(tmp_path))
    r = _tool("render", {"backend": "svg",
                         "scene": {"dsl": 1, "size": [64, 64],
                                   "ops": [{"op": "fill", "color": "#102030"}]}})
    text = json.loads(r["content"][0]["text"])
    assert text["backend"] == "svg" and "report" not in text
    assert "pixel" in text["note"] or "像素" in text["note"]
    assert (tmp_path / "scene.svg").exists()
    assert len(r["content"]) == 1, "矢量后端没有像素可预览"


# ---------------------------------------------------------------- 安全
def test_out_name_cannot_escape_the_output_dir(tmp_path, monkeypatch):
    """唯一有文件写入面的地方 —— 路径穿越必须一次性挡死。"""
    monkeypatch.setenv("PIXSMITH_MCP_OUT", str(tmp_path))
    for evil in ("../../evil", "..\\..\\evil", "/etc/passwd", "C:/Windows/x",
                 "sub/dir/x", ".hidden"):
        r = _tool("render", {"scene": {"dsl": 1, "size": [16, 16], "ops": []},
                             "out": evil, "embed_preview": False})
        assert r.get("isError") is not True, evil
        p = json.loads(r["content"][0]["text"])["path"]
        assert Path(p).parent == tmp_path, f"{evil} 逃出了输出目录：{p}"
        assert Path(p).name != "passwd" or p.endswith("passwd.png")
    # 目录里不该出现子目录
    assert all(x.is_file() for x in tmp_path.iterdir()), list(tmp_path.iterdir())


def test_extension_is_forced_to_match_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("PIXSMITH_MCP_OUT", str(tmp_path))
    r = _tool("render", {"scene": {"dsl": 1, "size": [16, 16], "ops": []},
                         "out": "logo.svg", "embed_preview": False})
    p = json.loads(r["content"][0]["text"])["path"]
    assert p.endswith("logo.png"), p


def test_server_never_executes_code():
    """⭐ 安全边界：只吃 JSON 场景，不接代码 —— 声明式那层就是现成的沙箱。

    给一个"看起来像代码"的字符串，它只会被当成**参数值**去解析颜色，不会被求值。
    判据不是"输出里没有那段代码"（报错信息本来就会回显它），
    而是**失败原因必须是"颜色格式不对"** —— 证明它走的是字符串解析路径。
    """
    payload = "__import__('os').system('echo pwned')"
    r = _tool("render", {"scene": {"dsl": 1, "size": [16, 16],
                                   "background": payload, "ops": []},
                         "embed_preview": False})
    assert r["isError"] is True
    err = json.loads(r["content"][0]["text"])["error"]
    assert "颜色" in err["message"], f"应当是颜色解析失败，实际：{err}"
    assert err["type"] == "ValueError", err


def test_stdout_is_not_polluted_by_tool_prints(capsys, tmp_path, monkeypatch):
    """工具执行期间的 stdout 被重定向到 stderr —— 否则会冲坏 JSON-RPC 流。"""
    monkeypatch.setenv("PIXSMITH_MCP_OUT", str(tmp_path))
    with monkeypatch.context() as m:
        # 让 spec 内部"意外"打印一句（模拟将来某次不经意的 print）
        import pixsmith.manifest as man
        orig = man.capability_manifest

        def noisy(*a, **k):
            print("这句绝不该出现在协议流里")
            return orig(*a, **k)
        m.setattr(man, "capability_manifest", noisy)
        out = io.StringIO()
        lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
                 json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                             "params": {"name": "spec", "arguments": {}}})]
        serve(io.StringIO("\n".join(lines) + "\n"), out, on_log=lambda s: None)
    text = out.getvalue()
    assert "绝不该出现在协议流里" not in text
    assert len([x for x in text.splitlines() if x.strip()]) == 2
    for line in text.splitlines():
        json.loads(line)          # 每一行都必须是合法 JSON


def test_selftest_has_no_side_effects(tmp_path, monkeypatch, capsys):
    """``--selftest`` 只该打印信息 —— **不该凭空造出目录**。

    这条是补一个真实事故：它原先会顺手 mkdir 出默认输出目录，
    于是那个目录（连同里面的渲染残渣）被 git 当成新文件提交进了仓库。
    打印路径不该有副作用。
    """
    from pixsmith.mcp_server import main as mcp_main
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PIXSMITH_MCP_OUT", raising=False)
    assert mcp_main(["--selftest"]) == 0
    assert list(tmp_path.iterdir()) == [], \
        f"--selftest 不该产生任何文件或目录，实际：{list(tmp_path.iterdir())}"
    assert "输出目录" in capsys.readouterr().err


def test_render_still_creates_the_out_dir_when_needed(tmp_path, monkeypatch):
    """"不主动造目录"不能把正常渲染也挡了 —— 真要用时仍要建。"""
    target = tmp_path / "deep" / "nested"
    monkeypatch.setenv("PIXSMITH_MCP_OUT", str(target))
    r = _tool("render", {"scene": {"dsl": 1, "size": [16, 16], "ops": []},
                         "embed_preview": False})
    assert r.get("isError") is not True
    assert target.is_dir() and (target / "scene.png").exists()
