"""调参台的测试：直接打真实 HTTP 端口，不 mock。

为什么要起真服务器：这层的风险几乎全在"HTTP 行为"上（状态码、头部、路由、越界拒绝），
mock 掉 `BaseHTTPRequestHandler` 等于把要验的东西全绕过。
用一个临时端口 + 后台线程，成本很低。

覆盖三件事：
1. **控件自动生成**：`/api/spec` 必须把 `Param` 声明原样透出（前端据此现推控件）
2. **端到端**：`/api/render` 回图 + 报告 + 等价场景 JSON，且**场景真的能跑**
3. **本地服务的三道安全**：Host 白名单 / Origin 校验 / 尺寸与体积上限
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from pixsmith import __version__
from pixsmith.playground import (MAX_BODY_BYTES, MAX_CANVAS_PX, build_spec,
                                 render_payload, run_server)


@pytest.fixture(scope="module")
def server():
    srv, url, _th = run_server(port=8899, quiet=True)
    yield url
    srv.shutdown()
    srv.server_close()


def _get(url: str, timeout: float = 30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def _post(url: str, payload: dict, headers: dict | None = None, timeout: float = 60):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


# ---------------------------------------------------------------- 规格
def test_spec_exposes_param_declarations_for_auto_ui():
    """前端不手写任何图案的控件 —— 全靠这份声明现推，所以它必须完整。"""
    spec = build_spec()
    assert spec["version"] == __version__
    assert len(spec["patterns"]) >= 20
    assert spec["categories"] and spec["blends"] and spec["size_presets"]
    for key, pat in spec["patterns"].items():
        assert pat["summary"], key
        assert pat["category"], key
        assert isinstance(pat["svg"], bool), key
        for p in pat["params"]:
            assert set(p) == {"name", "type", "default", "doc"}, (key, p)
            assert p["type"] in ("color", "int", "float", "bool", "str",
                                 "points", "stops", "size"), (key, p)


def test_spec_marks_bitmap_only_patterns():
    """只支持位图的图案要在下拉里标出来（否则用户选了矢量才发现不支持）。"""
    spec = build_spec()
    assert spec["patterns"]["marble"]["svg"] is False
    assert spec["patterns"]["gradient"]["svg"] is True


# ---------------------------------------------------------------- 渲染
def test_render_payload_returns_image_report_and_scene():
    out = render_payload({"pattern": "gradient", "size": [200, 120],
                          "params": {"end": "#C8102E"}, "background": "#0A1730"})
    assert out["image"].startswith("data:image/png;base64,")
    assert out["report"]["channel_range"]["r"][1] > 100
    assert out["ms"] >= 0
    scene = out["scene"]
    assert scene["dsl"] == 1 and scene["background"] == "#0A1730"
    assert scene["ops"][0]["pattern"] == "gradient"
    # ⭐ 关键：给的场景 JSON 必须"抄下来就能跑"
    from pixsmith.scene import Scene
    Scene.from_dict(scene).render()


def test_render_payload_omits_defaults_and_still_works():
    """只传与默认值不同的参数 —— 省往返，且场景 JSON 更短。"""
    out = render_payload({"pattern": "flag_cn", "size": [160, 100]})
    scene = out["scene"]
    assert scene["ops"][0]["params"] == {}
    from pixsmith.scene import Scene
    Scene.from_dict(scene).render()


def test_render_payload_svg_has_no_report_but_has_svg():
    out = render_payload({"pattern": "gradient", "size": [80, 60], "backend": "svg"})
    assert out["svg"].startswith("<svg") and "report" not in out
    assert "note" in out


def test_render_payload_rejects_bad_input():
    with pytest.raises(KeyError):
        render_payload({"pattern": "没有这个图案"})
    with pytest.raises(ValueError, match="尺寸最大"):
        render_payload({"pattern": "gradient", "size": [MAX_CANVAS_PX + 1, 10]})
    with pytest.raises(ValueError):
        render_payload({"pattern": "gradient", "size": [0, 0]})
    with pytest.raises(Exception):
        render_payload({"pattern": "gradient", "size": [32, 32],
                        "params": {"不存在的参数": 1}})


def test_render_payload_blocks_unsupported_backend_explicitly():
    """矢量后端不支持时要报错（不静默降级）—— 页面上也是这个口径。"""
    with pytest.raises(Exception) as ei:
        render_payload({"pattern": "marble", "size": [80, 60], "backend": "svg"})
    assert "marble" in str(ei.value) or "paint" in str(ei.value)


# ---------------------------------------------------------------- HTTP
def test_index_serves_the_page(server):
    status, ctype, body = _get(server)
    assert status == 200 and "text/html" in ctype
    html = body.decode("utf-8")
    assert "调参台" in html and "api/render" in html
    assert "__VERSION__" not in html, "版本占位符没被替换"
    assert __version__ in html


def test_api_spec_over_http(server):
    status, ctype, body = _get(server + "api/spec")
    assert status == 200 and "application/json" in ctype
    assert len(json.loads(body)["patterns"]) >= 20


def test_api_render_over_http(server):
    status, data = _post(server + "api/render",
                         {"pattern": "starfield", "size": [200, 120],
                          "params": {"seed": 3}})
    assert status == 200
    assert data["image"].startswith("data:image/png;base64,")
    assert data["scene"]["ops"][0]["params"] == {"seed": 3}


def test_api_render_returns_400_with_reason_on_bad_input(server):
    status, data = _post(server + "api/render", {"pattern": "nope"})
    assert status == 400
    assert "nope" in data["error"] and data["type"] == "KeyError"


def test_unknown_paths_404(server):
    with pytest.raises(urllib.error.HTTPError) as ei:
        _get(server + "nope")
    assert ei.value.code == 404


# ---------------------------------------------------------------- 安全
def test_host_header_whitelist_blocks_dns_rebinding(server):
    """Host 不在白名单就拒 —— 挡"把域名解析到 127.0.0.1 来读本地服务"那类攻击。"""
    status, data = _post(server + "api/render", {"pattern": "gradient"},
                         headers={"Host": "evil.example.com"})
    assert status == 403 and "Host" in data["error"]


def test_cross_origin_post_is_rejected(server):
    """跨站 POST 到 localhost 的本地服务 → 拒（CSRF）。"""
    status, data = _post(server + "api/render", {"pattern": "gradient"},
                         headers={"Origin": "http://evil.example.com"})
    assert status == 403
    # 同源应当放行
    status2, _ = _post(server + "api/render",
                       {"pattern": "gradient", "size": [16, 16]},
                       headers={"Origin": server.rstrip("/")})
    assert status2 == 200


def test_oversized_body_is_rejected(server):
    """超大请求体直接拒，别把服务器读爆。"""
    import socket
    from urllib.parse import urlparse
    u = urlparse(server)
    with socket.create_connection((u.hostname, u.port), timeout=15) as s:
        head = (f"POST /api/render HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {MAX_BODY_BYTES + 1}\r\n\r\n").encode()
        s.sendall(head)
        got = s.recv(4096).decode("utf-8", "replace")
    assert "413" in got.split("\r\n")[0]


def test_server_binds_loopback_by_default():
    """默认只绑 127.0.0.1 —— 不给局域网开门。"""
    import inspect
    from pixsmith.playground import DEFAULT_HOST, run_server as rs
    assert DEFAULT_HOST == "127.0.0.1"
    assert inspect.signature(rs).parameters["host"].default == "127.0.0.1"


def test_port_falls_back_when_taken():
    """端口被占则自动往后找 —— 比直接报错友好。"""
    srv1, url1, _ = run_server(port=8901, quiet=True)
    try:
        srv2, url2, _ = run_server(port=8901, quiet=True)
        try:
            assert url1 != url2, "被占用时应当换端口"
        finally:
            srv2.shutdown()
            srv2.server_close()
    finally:
        srv1.shutdown()
        srv1.server_close()
