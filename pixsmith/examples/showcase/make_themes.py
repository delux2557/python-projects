"""主题系列图标：电子制造 / 天气 / 节气 / IT 元素。

    python examples/showcase/make_themes.py

设计原则（很重要）：
**只用协议图元 + 支持矢量的图案**（disc/ring/rect/ellipse/capsule/arc/polygon/line/
star/regular_polygon/erase_disc + gradient/dots/grid/rings/star/gear/ray_burst 等）。
为什么：clouds / marble / stripes / noise / vignette / brushed / cracks 这些是"逐像素场"，
只支持位图后端（需要 paint）；一旦用了，这个图标就**没法导出 SVG**，也就没法拖进 PPT 无损放大。
图案要当图标用，矢量能力比纹理质感更重要。

产出：output/showcase/themes/<key>.png + .svg + recipes/<key>.json，
并写一份 themes.json 供页面读取。
（写在 output/ 是仓库约定 —— 那里是"随手产物"；挑中的作品再复制进 gallery/ 提交。）
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from pixsmith import Scene, SvgBackend          # noqa: E402

WORKS = ROOT / "output/showcase/themes"
RECIPES = WORKS / "recipes"
W, H = 480, 360
MANIFEST: list[dict] = []


# ---------------------------------------------------------------- 图元简写
def fill(color, **kw):
    return {"op": "fill", "color": color, **kw}


def d(cx, cy, r, color, feather=1.0):
    return {"op": "disc", "cx": cx, "cy": cy, "r": r, "color": color, "feather": feather}


def rg(cx, cy, r_out, r_in, color, feather=1.0):
    return {"op": "ring", "cx": cx, "cy": cy, "r_out": r_out, "r_in": r_in,
            "color": color, "feather": feather}


def rc(x, y, w, h, color, radius=0):
    return {"op": "rect", "x": x, "y": y, "w": w, "h": h, "color": color, "radius": radius}


def el(cx, cy, rx, ry, color, ang=0.0):
    return {"op": "ellipse", "cx": cx, "cy": cy, "rx": rx, "ry": ry, "color": color, "ang": ang}


def cap(x0, y0, x1, y1, r, color):
    return {"op": "capsule", "x0": x0, "y0": y0, "x1": x1, "y1": y1, "r": r, "color": color}


def arc(cx, cy, r_out, r_in, a0, a1, color):
    return {"op": "arc", "cx": cx, "cy": cy, "r_out": r_out, "r_in": r_in,
            "a0": a0, "a1": a1, "color": color}


def poly(points, color, ss=3):
    return {"op": "polygon", "points": [list(p) for p in points], "color": color, "ss": ss}


def ln(points, width, color):
    return {"op": "line", "points": [list(p) for p in points], "width": width, "color": color}


def st(cx, cy, r, points, color, ang=-90.0, inner=0.382):
    return {"op": "star", "cx": cx, "cy": cy, "r": r, "points": points, "color": color,
            "ang": ang, "inner": inner}


def rp(cx, cy, r, sides, color, ang=-90.0):
    return {"op": "regular_polygon", "cx": cx, "cy": cy, "r": r, "sides": sides,
            "color": color, "ang": ang}


def erase(cx, cy, r, feather=1.0):
    return {"op": "erase_disc", "cx": cx, "cy": cy, "r": r, "feather": feather}


def lgrad(begin, end, angle=90.0, mid=None, mid_at=0.5):
    return {"op": "linear_gradient", "begin": begin, "end": end, "angle": angle,
            "mid": mid, "mid_at": mid_at}


def rgrad(inner, outer, cx=None, cy=None, radius=None):
    return {"op": "radial_gradient", "inner": inner, "outer": outer,
            "cx": cx, "cy": cy, "radius": radius}


def pat(name, **params):
    return {"op": "pattern", "pattern": name, "params": params}


def ly(ops, blend="normal", opacity=1.0):
    return {"blend": blend, "opacity": opacity, "ops": ops}


# ---------------------------------------------------------------- 落盘
def save(key: str, group: str, title: str, use: str, layers: list, note: str = "") -> None:
    obj = {"dsl": 1, "size": [W, H], "note": note or f"{group} · {title}", "layers": layers}
    scene = Scene.from_dict(obj)
    scene.render().save(WORKS / f"{key}.png")
    svg_ok = True
    try:
        scene.render(SvgBackend(W, H)).save(WORKS / f"{key}.svg")
    except Exception:                                  # noqa: BLE001
        svg_ok = False
    (RECIPES / f"{key}.json").write_text(
        json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST.append({"key": key, "group": group, "title": title, "use": use, "svg": svg_ok})


# ================================================================ 电子制造
def cloud_discs(cx, cy, scale, color, n=5):
    """用重叠圆拼一朵云（协议图元，可出矢量）。"""
    out = []
    for i in range(n):
        t = i / (n - 1)
        out.append(d(cx + (t - 0.5) * 190 * scale, cy + (0.0 if i % 2 else 10 * scale),
                     38 * scale + 14 * scale * math.sin(t * math.pi), color))
    return out


def build_electronics() -> None:
    G = "电子制造"

    # 1 电路板走线：45° 折线 + 焊盘 + 元件封装
    base = [fill("#08221A"), pat("grid", bg="#00000000", line="#12402A", step=24,
                                 every=5, width=1.0, major_width=1.8)]
    traces = []
    paths = [
        [(-20, 70), (110, 70), (150, 110), (330, 110), (370, 70), (500, 70)],
        [(-20, 200), (90, 200), (130, 240), (250, 240), (290, 200), (500, 200)],
        [(80, -20), (80, 130), (120, 170), (120, 380)],
        [(360, -20), (360, 120), (320, 160), (320, 380)],
        [(-20, 300), (170, 300), (200, 270), (300, 270), (300, 380)],
    ]
    for i, p in enumerate(paths):
        traces.append(ln(p, 3.0, "#D9A43A" if i % 2 == 0 else "#1D9E75"))
    pads = [rg(x, y, 7, 3.2, "#E8B33C") for x, y in
            ((110, 70), (330, 110), (90, 200), (250, 240), (80, 130), (360, 120), (170, 300))]
    ic_a = [rc(190, 40, 120, 60, "#0D3325", radius=4),
            *[rc(196 + j * 18, 34, 8, 8, "#C8A15A") for j in range(6)],
            *[rc(196 + j * 18, 98, 8, 8, "#C8A15A") for j in range(6)]]
    ic_b = [rc(120, 250, 90, 74, "#0D3325", radius=4),
            *[rc(126 + j * 18, 244, 8, 8, "#C8A15A") for j in range(4)],
            *[rc(126 + j * 18, 318, 8, 8, "#C8A15A") for j in range(4)]]
    save("em_pcb", G, "电路板走线", "底图 / 章节分隔",
         [base, ly(traces + pads + ic_a + ic_b)])

    # 2 IC 芯片：封装 + 引脚 + 1 脚标记 + 半圆缺口
    body = [rc(120, 76, 240, 208, "#161B23", radius=6),
            rc(132, 88, 216, 184, "#1E2530", radius=4)]
    pins = ([rc(96, 96 + j * 24, 28, 12, "#C8A15A") for j in range(7)]
            + [rc(356, 96 + j * 24, 28, 12, "#C8A15A") for j in range(7)]
            + [rc(140 + j * 26, 52, 12, 26, "#C8A15A") for j in range(7)]
            + [rc(140 + j * 26, 282, 12, 26, "#C8A15A") for j in range(7)])
    mark = [d(156, 112, 11, "#C8A15A"),
            rc(170, 150, 140, 8, "#3A4756"), rc(170, 168, 96, 8, "#3A4756"),
            rc(170, 206, 140, 8, "#3A4756"), rc(170, 224, 64, 8, "#3A4756")]
    save("em_chip", G, "IC 芯片", "底图 / 图示",
         [[rgrad("#12212E", "#05070F", 240, 180, 300)], ly(body + pins + mark),
          ly([erase(240, 76, 22)])])

    # 3 晶圆：圆片 + 晶粒网格 + 平边切口
    die = []
    step, r = 26, 148
    for gy in range(-6, 7):
        for gx in range(-6, 7):
            x, y = 240 + gx * step, 180 + gy * step
            if math.hypot(gx * step, gy * step) < r - 14:
                die.append(rc(x - 10, y - 10, 20, 20, "#2BB3A3" if (gx + gy) % 3 else "#3E88C7"))
    save("em_wafer", G, "晶圆 / 晶粒", "底图 / 数据切片比喻",
         [[fill("#05070F")], ly([d(240, 180, r, "#16324F")]), ly(die),
          ly([rg(240, 180, r + 2, r - 3, "#85B7EB"), poly(
              [(150, 322), (330, 322), (330, 360), (150, 360)], "#05070F")]),
          ly([pat("halftone", bg="#00000000", dot="#85B7EB", cell=26, mode="radial",
                  min_ratio=0.0, max_ratio=0.5)], blend="screen", opacity=0.25)])

    # 4 CPU 封装：菱形基板 + 针脚阵列 + 中央晶片
    pins = []
    for gy in range(-6, 7):
        for gx in range(-6, 7):
            pins.append(rc(240 + gx * 15 - 4, 180 + gy * 15 - 4, 8, 8, "#8F7A3E"))
    dia = poly([(240, 40), (400, 180), (240, 320), (80, 180)], "#1D3A57")
    die_sq = poly([(240, 132), (288, 180), (240, 228), (192, 180)], "#E8B33C")
    save("em_cpu", G, "CPU 封装", "图示 / 章节分隔",
         [[rgrad("#0F2233", "#05070F", 240, 180, 330)], ly([dia]), ly(pins),
          ly([die_sq, d(268, 156, 6, "#FFF3D0")]),
          ly([poly([(240, 40), (400, 180), (240, 320), (80, 180)], "#00000000")])])

    # 5 手机：机身 + 屏幕 + 灵动孔 + 摄像头
    save("em_phone", G, "手机", "底图 / 移动端章节",
         [[lgrad("#0B1220", "#16283E", 118)],
          ly([rc(174, 34, 132, 292, "#0A0D13", radius=22),
              rc(182, 42, 116, 276, "#0F2233", radius=16)]),
          ly([pat("grid", bg="#00000000", line="#2BB3A3", step=20, every=4,
                  width=0.8, major_width=1.4)], blend="screen", opacity=0.45),
          ly([rc(214, 52, 52, 10, "#06080C", radius=5),
              rg(288, 78, 13, 9, "#2A3542"), d(288, 78, 7, "#4C6A8A"),
              rg(288, 110, 9, 6, "#2A3542"), d(288, 110, 4.5, "#3E5A78"),
              cap(174, 110, 174, 150, 3, "#2A3542"), cap(174, 168, 174, 200, 3, "#2A3542")])])

    # 6 散热风扇：叶片 + 轮毂 + 外框
    blades, cx, cy = [], 240, 180
    for i in range(7):
        a = math.radians(i * 360 / 7)
        pts = [(cx + math.cos(a + math.radians(16 + 26 * t)) * (34 + 56 * t),
                cy + math.sin(a + math.radians(16 + 26 * t)) * (34 + 56 * t))
               for t in (0.0, 0.35, 0.7, 1.0)]
        pts += [(cx + math.cos(a - math.radians(4 + 10 * t)) * (34 + 56 * t),
                 cy + math.sin(a - math.radians(4 + 10 * t)) * (34 + 56 * t))
                for t in (1.0, 0.6, 0.25)]
        blades.append(poly(pts, "#2E4055" if i % 2 else "#3A5170"))
    save("em_fan", G, "散热风扇", "图示 / 设备状态",
         [[rgrad("#101C2B", "#05070F", 240, 180, 300)], ly(blades),
          ly([d(cx, cy, 30, "#1B2836"), rg(cx, cy, 26, 12, "#85B7EB"), d(cx, cy, 9, "#E8B33C")]),
          ly([arc(cx, cy, 122, 116, 0, 6.283185, "#2A3B4E")])])


# ================================================================ 天气
def build_weather() -> None:
    G = "天气"
    # 1 晴
    save("wx_sun", G, "晴", "封面 / 天气看板",
         [[rgrad("#3A2408", "#0A0A12", 240, 180, 320)],
          ly([pat("ray_burst", count=24, cx=240, cy=180, inner=64, length=1.0,
                  color="#F2C14E", width=6.0, jitter=0.0, seed=5, core=False)]),
          ly([rg(240, 180, 104, 92, "#F7D774"), d(240, 180, 92, "#F2C14E"),
              d(240, 180, 74, "#FFE9AF")])])

    # 2 多云
    save("wx_cloud", G, "多云", "天气看板",
         [[lgrad("#0E1A2A", "#26405C", 118)],
          ly([d(360, 118, 52, "#E8B33CAA")]),
          ly(cloud_discs(216, 190, 1.0, "#DCE6F2F2")),
          ly(cloud_discs(320, 232, 0.72, "#B9C9DCEE"))])

    # 3 雨
    rain = [cap(120 + (i % 9) * 34, 210 + (i // 9) * 26, 132 + (i % 9) * 34,
                268 + (i // 9) * 26, 2.0,
                f"#6FB7E8{90 + (i % 4) * 40:02X}") for i in range(36)]
    save("wx_rain", G, "雨", "天气看板",
         [[lgrad("#0A1420", "#1B2E44", 118)], ly(cloud_discs(240, 138, 0.9, "#3E5570EE")),
          ly(rain)])

    # 4 雪
    flakes = []
    for i in range(9):
        fx, fy = 70 + (i % 5) * 86, 90 + (i // 5) * 96 + (i % 3) * 26
        s = 0.7 + (i % 3) * 0.22
        flakes.append(arc(fx, fy, 26 * s, 22 * s, 0, 6.283185, "#DCEEFFDD"))
        for k in range(3):
            a = math.radians(k * 60)
            flakes.append(cap(fx - math.cos(a) * 26 * s, fy - math.sin(a) * 26 * s,
                              fx + math.cos(a) * 26 * s, fy + math.sin(a) * 26 * s,
                              1.6 * s, "#8FC8F0DD"))
    save("wx_snow", G, "雪", "天气看板",
         [[lgrad("#0C1626", "#22405E", 118)],
          ly([pat("dots", bg="#00000000", dot="#DCEEFF", cell=52, radius=1.6)]),
          ly(flakes)])

    # 5 雷
    bolt = poly([(232, 60), (300, 60), (258, 166), (312, 166), (200, 316),
                 (238, 196), (186, 196)], "#F2C14E")
    save("wx_storm", G, "雷", "天气看板 / 告警",
         [[lgrad("#160E2C", "#2A1B44", 118)], ly(cloud_discs(240, 110, 1.0, "#2E2450F0")),
          ly([bolt]), ly([rg(240, 190, 150, 146, "#F2C14E55")], blend="screen", opacity=0.8)])

    # 6 雾
    bands = [cap(40, 96 + i * 34, 440, 96 + i * 34, 9 - i * 0.6,
                 f"#C9D6E4{40 + i * 12:02X}") for i in range(7)]
    save("wx_fog", G, "雾", "天气看板",
         [[lgrad("#141C26", "#39485A", 118)], ly([d(356, 96, 44, "#E8B33C33")]), ly(bands)])


# ================================================================ 节气 / 四季
def build_seasons() -> None:
    G = "节气"
    # 立春：嫩芽
    leaf = [cap(240, 250, 240, 130, 4.0, "#5FA33A"),
            el(212, 148, 40, 18, "#8FD05A", -32), el(268, 148, 40, 18, "#8FD05A", 32),
            el(240, 118, 14, 22, "#C8E6A0")]
    save("jr_lichun", G, "立春", "节气页 / 季节装饰",
         [[lgrad("#12300E", "#1E4A16", 118)], ly([d(240, 300, 150, "#2E6B22")]),
          ly([arc(240, 300, 150, 142, 3.14159, 6.283185, "#8FD05A")]), ly(leaf)])

    # 立夏：太阳 + 荷叶
    save("jr_lixia", G, "立夏", "节气页 / 季节装饰",
         [[lgrad("#0B2A2A", "#14544A", 118)],
          ly([d(300, 118, 54, "#F2C14E"), rg(300, 118, 78, 70, "#F2C14E88")]),
          ly([el(206, 250, 96, 42, "#2BB3A3"), el(206, 244, 74, 30, "#5AD0BC"),
              cap(150, 250, 262, 250, 1.6, "#0B2A2A")])])

    # 秋分：落叶
    leaves = []
    for i in range(6):
        lx, ly_ = 110 + (i % 3) * 130, 130 + (i // 3) * 110
        leaves.append(el(lx, ly_, 40, 18, "#E8B33C" if i % 2 else "#E2571E", 24 + i * 14))
        leaves.append(cap(lx - 34, ly_ + 10, lx + 26, ly_ - 6, 1.6, "#8A5A10"))
    save("jr_qiufen", G, "秋分", "节气页 / 季节装饰",
         [[lgrad("#2A1A08", "#5A3A10", 118)],
          ly([pat("dots", bg="#00000000", dot="#F2C14E", cell=64, radius=2.0,
                  stagger=True)]), ly(leaves)])

    # 冬至：雪花 + 月
    flake = [arc(240, 160, 88, 80, 0, 6.283185, "#DCEEFFEE")]
    for k in range(6):
        a = math.radians(k * 60)
        flake.append(cap(240 - math.cos(a) * 84, 160 - math.sin(a) * 84,
                         240 + math.cos(a) * 84, 160 + math.sin(a) * 84, 3.0, "#BFE0FF"))
    for k in range(3):
        a = math.radians(k * 60 + 30)
        flake.append(cap(240 - math.cos(a) * 40, 160 - math.sin(a) * 40,
                         240 + math.cos(a) * 40, 160 + math.sin(a) * 40, 2.0, "#8FC8F0"))
    save("jr_dongzhi", G, "冬至", "节气页 / 季节装饰",
         [[lgrad("#0A1424", "#1E3550", 118)],
          ly([d(378, 84, 34, "#E8EEF5"), d(364, 74, 30, "#0E1A2C")]),
          ly(flake), ly([pat("dots", bg="#00000000", dot="#DCEEFF", cell=48, radius=1.4)])])


# ================================================================ IT 元素
def build_it() -> None:
    G = "IT 元素"
    # 1 数据库
    db = [el(240, 96, 86, 26, "#4C8FD0"), rc(154, 96, 172, 160, "#2F6EAE"),
          arc(240, 256, 86, 0, 0, 3.14159, "#2F6EAE"),
          arc(240, 256, 86, 78, 0, 3.14159, "#4C8FD0"),
          arc(240, 176, 86, 78, 0, 3.14159, "#4C8FD0"),
          arc(240, 216, 86, 78, 0, 3.14159, "#4C8FD0")]
    save("it_db", G, "数据库", "图示 / 数据模块",
         [[lgrad("#0B1220", "#16283E", 118)], ly([d(240, 300, 150, "#12243A")]), ly(db),
          ly([d(300, 88, 8, "#DCEEFF")])])

    # 2 服务器机架
    units = []
    for i in range(4):
        y = 70 + i * 62
        units += [rc(140, y, 200, 48, "#1E2A38", radius=6),
                  rc(150, y + 8, 120, 10, "#2E4258"),
                  rc(150, y + 24, 86, 10, "#2E4258"),
                  d(320, y + 16, 7, "#39FF88" if i % 2 == 0 else "#F2C14E"),
                  d(320, y + 34, 7, "#F2C14E" if i % 2 == 0 else "#39FF88")]
    save("it_server", G, "服务器机架", "图示 / 基础设施",
         [[lgrad("#0A0F18", "#131C28", 118)], ly(units),
          ly([pat("scanlines", bg="#00000000", line="#39FF88", gap=6, alpha=0.18,
                  width=1.2)], blend="screen", opacity=0.7)])

    # 3 网络拓扑
    nodes = [(240, 180, 30, "#E8B33C")]
    links = []
    for i in range(5):
        a = math.radians(-90 + i * 72)
        nx, ny = 240 + math.cos(a) * 128, 180 + math.sin(a) * 106
        links.append(ln([(240, 180), (nx, ny)], 2.4, "#3E88C7"))
        nodes.append((nx, ny, 18, "#4C8FD0"))
    save("it_network", G, "网络拓扑", "图示 / 系统架构",
         [[rgrad("#0C1A2A", "#05070F", 240, 180, 300)], ly(links),
          ly([d(x, y, r, c) for x, y, r, c in nodes]),
          ly([rg(240, 180, 46, 38, "#E8B33C88")])])

    # 4 终端窗口
    lines = []
    for i, w in enumerate((150, 210, 120, 240, 90, 180)):
        lines.append(rc(96, 128 + i * 30, w, 10, "#39FF88" if i % 2 else "#4C8FD0"))
    save("it_terminal", G, "终端窗口", "图示 / 代码与脚本",
         [[lgrad("#0B1220", "#101A28", 118)],
          ly([rc(72, 60, 336, 240, "#0E141C", radius=12),
              rc(72, 60, 336, 40, "#1A2432", radius=12), rc(72, 88, 336, 12, "#1A2432"),
              d(94, 80, 7, "#E2571E"), d(116, 80, 7, "#F2C14E"), d(138, 80, 7, "#39FF88")]),
          ly(lines)])

    # 5 机器人头（几何风格的"小动物"替代品，见文档里的能力说明）
    save("it_robot", G, "机器人头", "图示 / 智能体",
         [[rgrad("#152238", "#05070F", 240, 180, 300)],
          ly([cap(240, 62, 240, 30, 4, "#85B7EB"), d(240, 26, 9, "#E8B33C"),
              rc(150, 72, 180, 150, "#1E2A38", radius=22),
              rc(166, 88, 148, 118, "#0E141C", radius=16)]),
          ly([d(206, 136, 18, "#39FF88"), d(274, 136, 18, "#39FF88"),
              d(206, 136, 8, "#0E141C"), d(274, 136, 8, "#0E141C"),
              rc(206, 178, 68, 10, "#39FF88", radius=5),
              rc(150, 100, 16, 30, "#2E4258", radius=6),
              rc(314, 100, 16, 30, "#2E4258", radius=6)])])


def main() -> int:
    WORKS.mkdir(parents=True, exist_ok=True)
    RECIPES.mkdir(parents=True, exist_ok=True)
    build_electronics()
    build_weather()
    build_seasons()
    build_it()
    (WORKS / "themes.json").write_text(
        json.dumps(MANIFEST, ensure_ascii=False, indent=2), encoding="utf-8")
    n_svg = sum(1 for m in MANIFEST if m["svg"])
    print(f"共产出 {len(MANIFEST)} 个主题图标（其中 {n_svg} 个同时有矢量版）：")
    for g in dict.fromkeys(m["group"] for m in MANIFEST):
        items = [m for m in MANIFEST if m["group"] == g]
        print(f"  [{g}] " + "、".join(f"{m['title']}{'' if m['svg'] else '(仅位图)'}"
                                      for m in items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
