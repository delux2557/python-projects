"""本地调参台：浏览器里拖滑块、实时看效果、一键复制场景 JSON。

它补的是 MCP 的另一半
----------------------
    MCP server（`mcp_server.py`）    服务 **agent** —— 机器调
    调参台（本模块）                  服务 **人**     —— 手工调，然后把结果沉淀成 JSON

两者产出的都是**同一个场景 JSON**，所以人工调好的参数可以直接丢给 agent / CLI / 存进 git。

为什么控件是**自动生成**的
--------------------------
前端不手写任何一个图案的控件 —— 全部从 `patterns` 的 `Param` 声明现推。
所以**加一个图案，调参台自动就支持它**（分类、参数名、类型、默认值、说明全都有了）。
这是本项目一贯的"声明一次、多处消费"：`Param` 已经同时喂给了 CLI 校验、帮助文本、
能力清单，这里是第四个消费方。

零依赖
------
只用 `http.server`。不需要 Flask / 构建工具 / npm。

安全（本地服务该有的三道）
--------------------------
1. **默认只绑 ``127.0.0.1``** —— 不给局域网开门
2. **Host 白名单** —— 挡 DNS 重绑定（攻击者把自己的域名解析到 127.0.0.1 来读你的本地服务）
3. **Origin 校验** —— 挡跨站 CSRF（别的网页偷偷 POST 到你的 localhost）
另外画布尺寸有上限，免得拖一个大滑块把机器卡住。
"""

from __future__ import annotations

import base64
import json
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .backend import UnsupportedOperation
from .params import Param
from .patterns import by_category
from .patterns._util import fit_size
from .scene import Scene

__all__ = ["make_handler", "run_server", "build_spec", "render_payload",
           "INDEX_HTML", "DEFAULT_PORT", "MAX_CANVAS_PX"]

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
MAX_CANVAS_PX = 4096
MAX_BODY_BYTES = 256 * 1024

SIZE_PRESETS = [
    ("1920x1080", "横版 16:9"),
    ("1280x720", "横版 16:9 小"),
    ("2560x1440", "2K 横版"),
    ("1080x1080", "方图"),
    ("1080x1920", "竖版 9:16"),
    ("2560x1080", "超宽"),
]


# ====================================================================== 数据
def build_spec() -> dict:
    """给前端的完整规格：图案 + 参数声明 + 尺寸预设 + 混合模式。

    **参数声明原样透出**（type / default / doc），前端据此现推控件。
    """
    from .blend import MODES

    patterns = {}
    for key, spec in ((k, v) for k, v in _all_patterns().items()):
        patterns[key] = {
            "summary": spec.summary,
            "category": spec.category,
            "requires": list(spec.requires),
            "svg": not set(spec.requires),
            "params": [{"name": p.name, "type": p.type,
                        "default": p.default, "doc": p.doc}
                       for p in spec.params],
        }
    return {
        "version": __version__,
        "patterns": patterns,
        "categories": {c: [s.key for s in items]
                       for c, items in by_category().items()},
        "size_presets": SIZE_PRESETS,
        "blends": list(MODES),
        "max_px": MAX_CANVAS_PX,
    }


def _all_patterns() -> dict:
    from .patterns import REGISTRY
    return {s.key: s for s in REGISTRY.all()}


def render_payload(payload: dict) -> dict:
    """一次请求 → 预览图 + 自检报告 + 等价场景 JSON。

    返回一个 dict（不是 HTTP 响应），方便单测直接调。
    """
    from .svg import SvgBackend

    t0 = time.perf_counter()
    key = str(payload.get("pattern") or "").strip()
    if key not in _all_patterns():
        raise KeyError(f"没有名为 {key!r} 的图案")

    size = fit_size(payload.get("size") or (1280, 720))
    if max(size) > MAX_CANVAS_PX:
        raise ValueError(f"尺寸最大 {MAX_CANVAS_PX}px（收到 {size[0]}x{size[1]}）")
    if min(size) < 1:
        raise ValueError("尺寸必须为正")

    backend = str(payload.get("backend") or "raster")
    background = payload.get("background") or None
    layers = payload.get("layers") or []
    scene_dict: dict = {"dsl": 1, "size": list(size)}
    if background:
        scene_dict["background"] = background
    scene_dict["ops"] = [{"op": "pattern", "pattern": key,
                          "params": dict(payload.get("params") or {})}]
    if layers:
        scene_dict["layers"] = list(layers)
    scene = Scene.from_dict(scene_dict)

    out: dict = {"scene": scene_dict, "backend": backend}
    if backend == "svg":
        svg = scene.render(SvgBackend(*scene.size)).to_svg()
        out["svg"] = svg
        out["note"] = "矢量后端没有像素，因此没有自检报告"
    else:
        canvas = scene.render()
        out["image"] = ("data:image/png;base64,"
                        + base64.b64encode(canvas.to_png()).decode("ascii"))
        out["report"] = scene.report(canvas)
    out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


# ====================================================================== 服务
def make_handler(*, static: dict):
    """造一个请求处理器。``static`` 是预渲染好的静态响应（如首页 HTML）。"""

    class Handler(BaseHTTPRequestHandler):
        server_version = f"pixsmith/{__version__}"
        protocol_version = "HTTP/1.1"

        # -------------------------------------------------- 工具
        def _trusted(self) -> bool:
            """Host 白名单 + Origin 校验。

            挡两类真实攻击：
            - **DNS 重绑定**：攻击者把自己域名解析到 127.0.0.1，浏览器就以为同源了
            - **跨站 CSRF**：别的页面偷偷 POST 到 localhost 上的本地服务
            """
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if host not in ("127.0.0.1", "localhost", "::1"):
                return False
            origin = self.headers.get("Origin")
            if origin:
                port = self.server.server_port
                if origin not in (f"http://127.0.0.1:{port}",
                                  f"http://localhost:{port}",
                                  f"http://[::1]:{port}"):
                    return False
            return True

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def log_message(self, fmt, *args):        # 让日志走 stderr 且更安静
            pass

        # -------------------------------------------------- 路由
        def do_GET(self):                          # noqa: N802
            if not self._trusted():
                return self._json(403, {"error": "拒绝：Host/Origin 不在白名单"})
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self._send(200, static["index"], "text/html; charset=utf-8")
            if path == "/api/spec":
                return self._json(200, static["spec"])
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            return self._json(404, {"error": f"未知路径 {path}"})

        def do_POST(self):                         # noqa: N802
            if not self._trusted():
                return self._json(403, {"error": "拒绝：Host/Origin 不在白名单"})
            if self.path.split("?", 1)[0] != "/api/render":
                return self._json(404, {"error": "未知路径"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._json(400, {"error": "Content-Length 不合法"})
            if n <= 0 or n > MAX_BODY_BYTES:
                return self._json(413, {"error": f"请求体大小不合法（{n} 字节）"})
            try:
                payload = json.loads(self.rfile.read(n).decode("utf-8"))
                return self._json(200, render_payload(payload))
            except (KeyError, ValueError, TypeError, OSError,
                    UnsupportedOperation, json.JSONDecodeError) as exc:
                # 参数写错是**用法问题**，把原因原样返回给页面（跟 CLI/MCP 同一套口径）
                msg = exc.args[0] if exc.args and isinstance(exc.args[0], str) else str(exc)
                return self._json(400, {"error": msg, "type": type(exc).__name__})

    return Handler


def _is_port_free(host: str, port: int) -> bool:
    """探测端口是否真的空着。

    ⚠️ **平台差异的坑**：Windows 上 ``SO_REUSEADDR`` 允许**抢占已被监听的口**
    （Unix 上它只用来跳过 TIME_WAIT，不允许抢占）。所以探测时在 Windows 要用
    ``SO_EXCLUSIVEADDRUSE``，否则会把"已占用"误判成"空闲"，
    结果两个服务器绑在同一个口上 —— 第一次就是这么错的。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):          # Windows
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:                                               # Unix
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


class _Server(ThreadingHTTPServer):
    """同理：Windows 上关掉 ``allow_reuse_address``，让"端口被占"**真的报错**，
    而不是悄悄抢过来造成两个服务器共用一个口。Unix 上保留它来跳过 TIME_WAIT。"""

    allow_reuse_address = not hasattr(socket, "SO_EXCLUSIVEADDRUSE")

    def handle_error(self, request, client_address):
        """客户端中途断开（浏览器取消请求、关闭标签页）不该往 stderr 甩一整段 traceback。"""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                            BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def _free_port(host: str, want: int) -> int:
    """端口被占就往后找（最多试 20 个），比直接报错友好。"""
    for p in range(want, want + 20):
        if _is_port_free(host, p):
            return p
    raise OSError(f"{want}–{want + 19} 都没空端口")


def run_server(*, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
               open_browser: bool = False, quiet: bool = False):
    """起服务，返回 ``(server, url, thread)``；调用方负责 shutdown。"""
    port = _free_port(host, port)
    spec = build_spec()
    static = {"index": INDEX_HTML.replace("__VERSION__", __version__).encode("utf-8"),
              "spec": spec}
    srv = _Server((host, port), make_handler(static=static))
    url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}/"
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    if not quiet:
        print(f"pixsmith 调参台  →  {url}", flush=True)
        print(f"  图案 {len(spec['patterns'])} 个 · 尺寸上限 {MAX_CANVAS_PX}px · "
              f"Ctrl+C 退出", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    return srv, url, th


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="pixsmith serve",
        description="本地调参台：拖滑块看效果，一键复制场景 JSON")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"端口（默认 {DEFAULT_PORT}）")
    ap.add_argument("--host", default=DEFAULT_HOST,
                    help=f"监听地址（默认 {DEFAULT_HOST}；填 0.0.0.0 会暴露到局域网，谨慎）")
    ap.add_argument("--no-open", action="store_true", help="不要自动打开浏览器")
    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"⚠️ 监听 {args.host} —— 本机之外也能访问。确认这是你要的。", flush=True)
    srv, _url, _th = run_server(host=args.host, port=args.port,
                                open_browser=not args.no_open)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)
    finally:
        srv.shutdown()
        srv.server_close()
    return 0


# ====================================================================== 前端
#: 用字符串替换而不是 ``str.format`` —— 页面里全是 JS 的花括号，
#: 用 format 就得把每一个都写成 ``{{``，改一次 JS 忘一处就炸。
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pixsmith · 调参台</title>
<style>
:root { color-scheme: light dark; --fg:#1a1a1a; --bg:#faf9f7; --muted:#6b6b6b;
  --card:#fff; --line:#e5e2dc; --accent:#2f6fed; --warn:#b45309; }
@media (prefers-color-scheme: dark) { :root { --fg:#f0eee9; --bg:#141414;
  --muted:#a0a0a0; --card:#1e1e1e; --line:#333; --accent:#6ea8ff; --warn:#f0b429; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font-family: ui-sans-serif, system-ui, "Segoe UI", "Microsoft YaHei", sans-serif;
  font-size:13px; }
header { position:sticky; top:0; z-index:5; display:flex; align-items:center; gap:12px;
  flex-wrap:wrap; padding:12px 20px; background:var(--card); border-bottom:1px solid var(--line); }
h1 { font-size:15px; font-weight:600; margin:0; }
h1 small { color:var(--muted); font-weight:400; margin-left:6px; }
main { display:grid; grid-template-columns: minmax(0,1fr) 320px; gap:0; height:calc(100vh - 53px); }
.left { display:flex; flex-direction:column; min-width:0; border-right:1px solid var(--line); }
.stage { flex:1; display:flex; align-items:center; justify-content:center; padding:20px;
  min-height:0; background-image:
    linear-gradient(45deg,#0001 25%,transparent 25%,transparent 75%,#0001 75%),
    linear-gradient(45deg,#0001 25%,transparent 25%,transparent 75%,#0001 75%);
  background-size:20px 20px; background-position:0 0,10px 10px; }
.stage img, .stage svg { max-width:100%; max-height:100%; display:block;
  box-shadow:0 2px 18px #0002; }
.right { overflow:auto; padding:16px 18px 40px; }
fieldset { border:0; border-top:1px solid var(--line); margin:0 0 4px; padding:14px 0 6px; }
fieldset:first-of-type { border-top:0; padding-top:4px; }
legend, .lbl { font-size:11px; font-weight:600; text-transform:uppercase;
  letter-spacing:.06em; color:var(--muted); padding:0; margin-bottom:8px; display:block; }
select, input[type=text], input[type=number], textarea { width:100%; padding:6px 8px;
  border:1px solid var(--line); border-radius:7px; background:var(--bg); color:var(--fg);
  font:inherit; }
textarea { font-family:ui-monospace,Consolas,monospace; font-size:11.5px; min-height:150px;
  resize:vertical; white-space:pre; }
input[type=range] { width:100%; accent-color:var(--accent); }
.prow { margin:0 0 14px; }
.prow .top { display:flex; align-items:baseline; gap:6px; margin-bottom:5px; }
.prow .top b { font-weight:600; font-family:ui-monospace,Consolas,monospace; font-size:12px; }
.prow .top .val { margin-left:auto; color:var(--accent); font-variant-numeric:tabular-nums;
  font-family:ui-monospace,Consolas,monospace; }
.prow .doc { color:var(--muted); font-size:11.5px; margin:4px 0 0; }
.prow .flex { display:flex; gap:8px; align-items:center; }
.prow .flex input[type=number] { width:88px; flex:none; }
.row { display:flex; gap:8px; }
.row > * { flex:1; min-width:0; }
button { padding:7px 13px; border:1px solid var(--line); border-radius:8px;
  background:var(--card); color:var(--fg); font:inherit; cursor:pointer; }
button:hover { border-color:var(--accent); color:var(--accent); }
button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
button.primary:hover { color:#fff; opacity:.9; }
.meta { color:var(--muted); font-size:11.5px; display:flex; gap:10px; flex-wrap:wrap; }
.bad { color:#c0392b; white-space:pre-wrap; font-size:12px; }
.hint { color:var(--warn); font-size:12px; line-height:1.5; }
.chk { display:flex; align-items:center; gap:6px; }
.chk input { accent-color:var(--accent); }
.pill { font-size:10.5px; border:1px solid var(--line); border-radius:5px;
  padding:1px 5px; color:var(--muted); }
.pill.no { color:#c0392b; border-color:#c0392b55; }
table.rep { width:100%; border-collapse:collapse; font-size:11.5px; }
table.rep td { padding:3px 0; vertical-align:top; }
table.rep td:first-child { color:var(--muted); white-space:nowrap; padding-right:10px; }
code { font-family:ui-monospace,Consolas,monospace; }
a { color:var(--accent); }
</style></head><body>

<header>
  <h1>pixsmith 调参台 <small>v__VERSION__</small></h1>
  <div class="meta"><span id="status">就绪</span></div>
  <div style="margin-left:auto"></div>
  <label class="chk"><input type="checkbox" id="svg"> 矢量输出</label>
  <button id="reload">重渲染</button>
  <button id="copy" class="primary">复制场景 JSON</button>
</header>

<main>
  <div class="left">
    <div class="stage"><img id="preview" alt="预览" style="display:none"></div>
    <div style="padding:14px 20px; border-top:1px solid var(--line); max-height:42vh; overflow:auto">
      <div id="error" class="bad" style="margin-bottom:10px"></div>
      <div id="hints"></div>
      <div class="lbl" style="margin-top:12px">自检报告</div>
      <table class="rep" id="report"></table>
      <div class="lbl" style="margin-top:16px">场景 JSON（可直接给 CLI / agent / 存进 git）</div>
      <textarea id="json" readonly></textarea>
    </div>
  </div>

  <aside class="right">
    <fieldset><span class="lbl">图案</span>
      <select id="pattern"></select>
      <p class="doc" id="summary" style="color:var(--muted);font-size:11.5px;margin:6px 0 0"></p>
    </fieldset>

    <fieldset><span class="lbl">画布</span>
      <div class="row" style="margin-bottom:8px">
        <select id="preset"></select>
      </div>
      <div class="row">
        <input type="number" id="w" min="1" max="4096" step="1">
        <input type="number" id="h" min="1" max="4096" step="1">
      </div>
      <div class="prow" style="margin-top:12px">
        <div class="top"><b>background</b></div>
        <div class="flex"><input type="color" id="bgc" style="flex:1;height:32px;padding:2px">
          <input type="text" id="bgt" spellcheck="false" placeholder="留空=透明"></div>
        <p class="doc">8 位 hex：#RRGGBBAA。留空则透明底。</p>
      </div>
    </fieldset>

    <fieldset><span class="lbl">参数</span><div id="params"></div></fieldset>
  </aside>
</main>

<script>
const $ = (s) => document.querySelector(s);
let SPEC = null, CUR = "gradient", VAL = {}, TIMER = null;

function fmt(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function hexFromColor(v, fallback) {
  // 只接受 #RRGGBB / #RRGGBBAA；var(...) 之类透传给文本框
  if (typeof v === "string" && /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(v)) return v;
  return fallback || "#888888";
}

function buildParam(p) {
  const row = document.createElement("div");
  row.className = "prow";
  const top = document.createElement("div");
  top.className = "top";
  const nameEl = document.createElement("b");
  nameEl.textContent = p.name;
  const val = document.createElement("span");
  val.className = "val";
  top.append(nameEl, val);
  row.append(top);
  const holder = document.createElement("div");
  row.append(holder);
  if (p.doc) { const d = document.createElement("p"); d.className = "doc"; d.textContent = p.doc; row.append(d); }

  const set = (v) => { VAL[p.name] = v; val.textContent = fmt(v); schedule(); };

  if (p.type === "color") {
    holder.className = "flex";
    const c = document.createElement("input");
    c.type = "color"; c.style.flex = "1"; c.style.height = "32px"; c.style.padding = "2px";
    c.value = hexFromColor(p.default, "#000000").slice(0, 7);
    const t = document.createElement("input");
    t.type = "text"; t.spellcheck = false; t.style.width = "120px"; t.style.flex = "none";
    t.value = p.default == null ? "" : String(p.default);
    c.oninput = () => { t.value = c.value.toUpperCase(); set(c.value.toUpperCase()); };
    t.oninput = () => {
      const v = t.value.trim();
      if (/^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(v)) c.value = v.slice(0, 7);
      if (v === "") set(null); else set(v.toUpperCase());
    };
    holder.append(c, t);
    VAL[p.name] = p.default;
  } else if (p.type === "bool") {
    holder.className = "chk";
    const c = document.createElement("input");
    c.type = "checkbox"; c.checked = !!p.default;
    c.oninput = () => set(c.checked);
    const lab = document.createElement("span"); lab.textContent = c.checked ? "开" : "关";
    c.oninput = () => { lab.textContent = c.checked ? "开" : "关"; set(c.checked); };
    holder.append(c, lab);
    VAL[p.name] = !!p.default;
  } else if (p.type === "int" || p.type === "float") {
    const isInt = p.type === "int";
    const d = Number(p.default ?? 0);
    const lo = d > 0 ? 0 : (d < 0 ? d * 3 : -1);
    const hi = d > 0 ? d * 3 : (d < 0 ? 0 : 1);
    const step = isInt ? 1 : (Math.abs(d) >= 20 ? d / 100 : (Math.abs(d) >= 1 ? 0.05 : 0.005));
    const stepS = isInt ? "1" : String(step);
    holder.className = "flex";
    const r = document.createElement("input");
    r.type = "range"; r.min = lo.toFixed(6); r.max = (hi === lo ? lo + 1 : hi).toFixed(6);
    r.step = stepS; r.value = d;
    const n = document.createElement("input");
    n.type = "number"; n.step = stepS; n.value = d;
    const push = (raw, syncRange) => {
      const v = isInt ? parseInt(raw, 10) : parseFloat(raw);
      if (!Number.isFinite(v)) return;
      if (syncRange) r.value = v;
      n.value = v; set(v);
    };
    r.oninput = () => push(r.value, false);
    n.oninput = () => push(n.value, true);
    holder.append(r, n);
    VAL[p.name] = d;
  } else if (p.type === "str" || p.type === "points" || p.type === "stops") {
    // 结构化值用 JSON 文本框：类型不该靠猜
    const t = document.createElement(p.type === "str" ? "input" : "textarea");
    if (p.type === "str") t.type = "text";
    else { t.style.minHeight = "60px"; t.style.width = "100%"; t.style.fontFamily = "ui-monospace,Consolas,monospace"; }
    t.value = p.type === "str" ? String(p.default ?? "")
                              : JSON.stringify(p.default ?? [], null, 0);
    t.spellcheck = false;
    t.oninput = () => {
      if (p.type === "str") return set(t.value);
      try { set(JSON.parse(t.value)); t.style.borderColor = "var(--line)"; }
      catch (e) { t.style.borderColor = "#c0392b"; }
    };
    holder.append(t);
    VAL[p.name] = p.default;
  } else {
    const t = document.createElement("input");
    t.type = "text"; t.value = fmt(p.default);
    t.oninput = () => set(t.value);
    holder.append(t);
    VAL[p.name] = p.default;
  }
  return row;
}

function loadPattern(key) {
  CUR = key;
  const pat = SPEC.patterns[key];
  $("#summary").textContent = pat.summary;
  const box = $("#params");
  box.innerHTML = "";
  VAL = {};
  $("#preview").style.display = "none";
  if (!pat.params.length) {
    box.innerHTML = '<p class="doc">这个图案没有参数。</p>';
    return;
  }
  for (const p of pat.params) box.append(buildParam(p));
}

function currentPayload() {
  const params = {};
  for (const [k, v] of Object.entries(VAL)) {
    const dflt = (SPEC.patterns[CUR].params.find(x => x.name === k) || {}).default;
    if (JSON.stringify(v) !== JSON.stringify(dflt)) params[k] = v;   // 只发差异，省往返
  }
  return {
    pattern: CUR,
    params,
    size: [parseInt($("#w").value, 10) || 1280, parseInt($("#h").value, 10) || 720],
    background: $("#bgt").value.trim() || null,
    backend: $("#svg").checked ? "svg" : "raster"
  };
}

function schedule() {
  clearTimeout(TIMER);
  $("#status").textContent = "…";
  TIMER = setTimeout(render, 220);
}

async function render() {
  const payload = currentPayload();
  try {
    const res = await fetch("/api/render", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) { throw new Error(data.error || ("HTTP " + res.status)); }
    $("#error").textContent = "";
    const img = $("#preview");
    if (data.image) { img.src = data.image; img.style.display = "block"; }
    else if (data.svg) {
      img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(data.svg)));
      img.style.display = "block";
    }
    $("#json").value = JSON.stringify(data.scene, null, 2);
    showReport(data.report, data.note);
    $("#status").textContent = data.ms.toFixed(0) + " ms";
  } catch (e) {
    $("#error").textContent = "✗ " + e.message;
    $("#status").textContent = "出错";
  }
}

function showReport(rep, note) {
  const t = $("#report"), h = $("#hints");
  t.innerHTML = ""; h.innerHTML = "";
  if (!rep) { if (note) t.innerHTML = '<tr><td colspan="2">' + note + "</td></tr>"; return; }
  if (rep.hints && rep.hints.length) {
    h.innerHTML = rep.hints.map(x => '<p class="hint">⚠️ ' + x + "</p>").join("");
  }
  const cr = rep.channel_range || {};
  const rows = [
    ["尺寸", rep.size.join(" x ")],
    ["非透明占比", (rep.opaque_ratio * 100).toFixed(1) + " %"],
    ["内容包围盒", (rep.content_bbox || []).join(", ")],
    ["通道跨度", ["r","g","b"].map(c => c + " " + (cr[c]||[]).join("→")).join(" · ")],
    ["四角取样", Object.values(rep.corner_colors || {}).join(" ")],
    ["主色覆盖率", (rep.dominant_coverage * 100).toFixed(1) + " %"],
    ["主色", (rep.dominant_colors || []).join(" ")],
    ["平均亮度 / 对比", rep.mean_luma + " / " + rep.contrast]
  ];
  t.innerHTML = rows.map(([k, v]) => "<tr><td>" + k + "</td><td><code>" + v + "</code></td></tr>").join("");
}

async function boot() {
  const res = await fetch("/api/spec");
  SPEC = await res.json();
  const sel = $("#pattern");
  for (const [cat, keys] of Object.entries(SPEC.categories)) {
    const g = document.createElement("optgroup");
    g.label = cat;
    for (const k of keys) {
      const o = document.createElement("option");
      o.value = k;
      o.textContent = k + (SPEC.patterns[k].svg ? "" : "（仅位图）");
      g.append(o);
    }
    sel.append(g);
  }
  const ps = $("#preset");
  for (const [v, label] of SPEC.size_presets) {
    const o = document.createElement("option"); o.value = v; o.textContent = label + " · " + v;
    ps.append(o);
  }
  sel.value = CUR = "gradient";
  ps.value = "1280x720";
  $("#w").value = 1280; $("#h").value = 720;
  sel.onchange = () => loadPattern(sel.value);
  ps.onchange = () => {
    const [w, h] = ps.value.split("x");
    $("#w").value = w; $("#h").value = h; schedule();
  };
  $("#w").oninput = $("#h").oninput = schedule;
  $("#bgc").oninput = () => { $("#bgt").value = $("#bgc").value.toUpperCase(); schedule(); };
  $("#bgt").oninput = () => schedule();
  $("#svg").onchange = schedule;
  $("#reload").onclick = render;
  $("#copy").onclick = async () => {
    try {
      await navigator.clipboard.writeText($("#json").value);
      $("#copy").textContent = "已复制 ✓";
    } catch (e) { $("#json").select(); document.execCommand("copy"); $("#copy").textContent = "已复制 ✓"; }
    setTimeout(() => ($("#copy").textContent = "复制场景 JSON"), 1200);
  };
  loadPattern(CUR);
  await render();
}
boot();
</script>
</body></html>
"""
