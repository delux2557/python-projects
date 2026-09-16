"""AI Agent 标识候选：5 个方案，参数化尺寸 + 单色版 + 尺寸阶梯。

    python examples/showcase/make_logos.py

三条刻意的设计约束（都是为了"当 logo 用"而不是"当图用"）：
1. **只用协议图元** → 每个方案都能出矢量（SVG），放大不糊、可再编辑。
2. **所有形状互不重叠**（靠透明间隙分隔）→ 单色版（一个颜色印在任意底上）成立。
   重叠图形在单色下会糊成一团，这是很多"好看但不可用"的 logo 的通病。
3. **几何全部按尺寸比例算** → 同一份代码能出 512 / 64 / 32 / 16 px，
   这样"16px 还认不认得出"就是测出来的，不是猜出来的。

产出：output/showcase/logo/<key>.svg + <key>_{512,64,32,16}.png
      + <key>_mono_512.png（深墨，印浅底）+ <key>_mono_light_512.png（白墨，压深底）
      （写在 output/ 是仓库约定；挑中的方案再复制进 gallery/ 提交。）
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from pixsmith import Scene, SvgBackend          # noqa: E402

OUT = ROOT / "output/showcase/logo"
SIZES = (512, 64, 32, 16)
MONO = "#0A1730"        # 单色·深墨：印在浅底上
MONO_LIGHT = "#FFFFFF"  # 单色·白墨：压在深底上（深墨压在深底上等于没有）
MANIFEST: list[dict] = []


# ---------------------------------------------------------------- 图元简写（坐标全部按 0–1 比例）
def d(s, cx, cy, r, color, feather=1.0):
    return {"op": "disc", "cx": cx * s, "cy": cy * s, "r": r * s, "color": color,
            "feather": max(0.8, feather)}


def rg(s, cx, cy, r_out, r_in, color):
    return {"op": "ring", "cx": cx * s, "cy": cy * s, "r_out": r_out * s,
            "r_in": r_in * s, "color": color}


def rc(s, x, y, w, h, color, radius=0.0):
    return {"op": "rect", "x": x * s, "y": y * s, "w": w * s, "h": h * s,
            "color": color, "radius": radius * s}


def cap(s, x0, y0, x1, y1, r, color):
    return {"op": "capsule", "x0": x0 * s, "y0": y0 * s, "x1": x1 * s, "y1": y1 * s,
            "r": r * s, "color": color}


def arc(s, cx, cy, r_out, r_in, a0, a1, color):
    return {"op": "arc", "cx": cx * s, "cy": cy * s, "r_out": r_out * s,
            "r_in": r_in * s, "a0": a0, "a1": a1, "color": color}


def poly(s, pts, color, ss=3):
    return {"op": "polygon", "points": [[x * s, y * s] for x, y in pts],
            "color": color, "ss": ss}


def ln(s, pts, width, color):
    return {"op": "line", "points": [[x * s, y * s] for x, y in pts],
            "width": width * s, "color": color}


def erase(s, cx, cy, r):
    return {"op": "erase_disc", "cx": cx * s, "cy": cy * s, "r": r * s, "feather": 0.8}


def lay(ops):
    return [ops]


def small(s: int) -> bool:
    """小尺寸档位：亚像素图元会被栅格化吃掉，这里主动降级。

    16px 下 0.014 宽的线 = 0.22px，渲染出来是一条几乎透明的灰线 ——
    与其让它糊在那儿，不如按尺寸换成"少而粗"的版本（专业 logo 的标准做法：
    小尺寸用简化变体，而不是把大尺寸直接缩下去）。
    """
    return s <= 64


# ---------------------------------------------------------------- 配色
def pal(mono=False, light=False) -> dict:
    if mono:
        ink = MONO_LIGHT if light else MONO
        return {k: ink for k in ("main", "accent", "link", "sub")}
    return {"main": "#2BB3A3", "accent": "#F2C14E", "link": "#4C8FD0CC",
            "sub": "#0A1730"}


# ================================================================ 方案 A · 智能节点柱
def logo_a(s: int, mono=False, light=False):
    """下方四根递升的柱子（图表），上方一个"智能节点"用连线指向每根柱子。

    读法：「agent 在生成这张图表」—— 最直白，不需要解释。
    """
    c = pal(mono, light)
    n, w, gap = 4, 0.105, 0.052
    x0 = (1 - (n * w + (n - 1) * gap)) / 2
    base, heights = 0.855, (0.20, 0.32, 0.44, 0.58)
    bars = []
    for i, h in enumerate(heights):
        x = x0 + i * (w + gap)
        bars.append(rc(s, x, base - h, w, h, c["accent"] if i == n - 1 else c["main"],
                       radius=w * 0.34))
    # 节点（环 + 内核，靠透明间隙分隔 —— 单色下也分得开）
    node = (0.5, 0.145)
    links = []
    for i in range(n):
        x = x0 + i * (w + gap) + w / 2
        top = base - heights[i] - 0.045
        links.append(cap(s, node[0], node[1] + 0.115, x, top, 0.011, c["link"]))
    ring_ = [rg(s, *node, 0.088, 0.070, c["main"]), d(s, *node, 0.040, c["accent"])]
    return lay(links) + lay(bars) + lay(ring_)


# ================================================================ 方案 B · 六角核心
def logo_b(s: int, mono=False, light=False):
    """六边形核心（Agent 本体）+ 三个环绕节点与连线（协作 / 调度）。

    读法：多智能体协同、或"核心调度多个数据源"。偏技术、稳重。
    小尺寸：去掉内层细六边形与三根连线，外圈节点由"环"降级为"实心点"。
    """
    c = pal(mono, light)
    cx, cy, r = 0.5, 0.5, 0.315
    simp = small(s)
    verts = [(cx + math.cos(math.radians(-90 + i * 60)) * r,
              cy + math.sin(math.radians(-90 + i * 60)) * r) for i in range(6)]
    if simp:
        # 16px 下 0.014 宽的线只有 0.22px，等于没有。六边形改用 6 根胶囊拼边：
        # 线宽可控到 1px 以上，中间的空腔还能保住（这是"环心"的辨识点）。
        edges = [cap(s, verts[i][0], verts[i][1], verts[(i + 1) % 6][0],
                     verts[(i + 1) % 6][1], 0.058, c["main"]) for i in range(6)]
        dots = [d(s, cx, cy, 0.070, c["accent"])]
        for i in range(3):
            a = math.radians(-90 + i * 120)
            dots.append(d(s, cx + math.cos(a) * 0.455, cy + math.sin(a) * 0.455,
                          0.062, c["accent"]))
        return lay(edges) + lay(dots)
    hexline = ln(s, verts + [verts[0]], 0.030, c["main"])
    spokes, dots = [], [d(s, cx, cy, 0.052, c["accent"])]
    for i in range(3):
        a = math.radians(-90 + i * 120)
        ex, ey = cx + math.cos(a) * 0.62 * r, cy + math.sin(a) * 0.62 * r
        spokes.append(cap(s, cx, cy, ex, ey, 0.017, c["link"]))
        dots.append(d(s, ex, ey, 0.040, c["main"]))
        ox, oy = cx + math.cos(a) * 0.455, cy + math.sin(a) * 0.455
        dots.append(rg(s, ox, oy, 0.062, 0.046, c["accent"]))
    inner = ln(s, [(cx + (vx - cx) * 0.62, cy + (vy - cy) * 0.62) for vx, vy in verts]
               + [(cx + (verts[0][0] - cx) * 0.62, cy + (verts[0][1] - cy) * 0.62)],
               0.014, c["link"])
    return lay([hexline, inner]) + lay(spokes) + lay(dots)


# ================================================================ 方案 C · 齿轮 + 数据
def logo_c(s: int, mono=False, light=False):
    """齿轮轮廓（制造 / 工程）+ 中心镂空处一段上升折线与数据点。

    读法：制造业 + 数据洞察的双关。齿轮本身就是"设备/产线"的通用符号。
    """
    c = pal(mono, light)
    cx, cy = 0.5, 0.5
    teeth, r_in, r_out = 14, 0.335, 0.425
    step = 2 * math.pi / teeth
    pts = []
    for i in range(teeth):
        a0 = i * step
        for da, rr in ((0.00, r_in), (0.17, r_out), (0.33, r_out), (0.50, r_in)):
            ang = a0 + da * step
            pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
    hole = erase(s, cx, cy, 0.225)
    # 折线必须和柱子**分层不重叠**：彩色版靠颜色区分得开，压成单色就粘成一团。
    # 所以折线整体抬到柱子上方，读成"折线在上、柱在下"。坐标受镂空半径约束。
    bars = [rc(s, 0.335 + i * 0.075, 0.615 - h, 0.048, h, c["main"], radius=0.016)
            for i, h in enumerate((0.075, 0.125, 0.185))]
    trend = ln(s, [(0.345, 0.395), (0.428, 0.345), (0.500, 0.378), (0.578, 0.330)],
               0.026, c["accent"])
    dot = d(s, 0.578, 0.330, 0.032, c["accent"])
    return lay([poly(s, pts, c["main"]), hole]) + lay(bars) + lay([trend, dot])


# ================================================================ 方案 D · 环轨 + 数据点
def logo_d(s: int, mono=False, light=False):
    """两段断开的环形轨道 + 轨道上的数据点 + 中心三根小柱。

    读法：持续监测 / 闭环 / 循环调度。抽象，适合作为"平台级"标识。
    小尺寸：内圈细弧线加粗、数据点放大，保证 16px 下"断口 + 点"的关系还在。
    """
    c = pal(mono, light)
    cx, cy = 0.5, 0.5
    simp = small(s)
    # 注意参数顺序是 (r_out, r_in)：加粗 = r_in 变小。写反会得到退化的空环。
    w_out = (0.440, 0.355) if simp else (0.440, 0.385)
    w_in = (0.300, 0.215) if simp else (0.300, 0.255)
    rings = [arc(s, cx, cy, w_out[0], w_out[1], math.radians(-58), math.radians(196),
                 c["main"]),
             arc(s, cx, cy, w_in[0], w_in[1], math.radians(122), math.radians(376),
                 c["link"])]
    if simp:
        rings = [rings[0]]
    rad = 0.4125
    pts = [(cx + math.cos(math.radians(a)) * rad,
            cy + math.sin(math.radians(a)) * rad) for a in (-30, 70, 168)]
    dots = [d(s, x, y, 0.080 if simp else 0.052, c["accent"]) for x, y in pts]
    bars = [rc(s, 0.452 + i * 0.038, 0.545 - h, 0.030 if simp else 0.026, h,
               c["main"], radius=0.010)
            for i, h in enumerate((0.075, 0.110, 0.150) if simp
                                  else (0.055, 0.090, 0.130))]
    return lay(rings) + lay(bars) + lay(dots)


# ================================================================ 方案 E · 抽象字母 A
def logo_e(s: int, mono=False, light=False):
    """几何化的字母 A（Agent 首字母）+ 内部空腔里的三根数据柱。

    读法：有品牌感、能和系统名并排；字母本身具备记忆点。

    约束是硬的：A 的空腔是个**三角形**（顶点 y=0.430，底边被横杠封在 y=0.640），
    柱子必须整个待在三角形里。第一版把柱子放在 x 0.532–0.658 —— 那块地方已经
    是 A 的右腿肉身上了，彩色版靠金色勉强看出来，压成单色就等于没画。
    现在按空腔半宽 w(y) = 0.216·(y−0.430)/0.450 反推：柱底 0.628、柱宽 0.020、
    最高的那根取 0.105，右侧边缘刚好留在 w 之内。
    配色上柱子用深墨而不是金色：金色压在白色空腔上对比太弱。
    """
    c = pal(mono, light)
    outer = [(0.500, 0.105), (0.885, 0.880), (0.716, 0.880), (0.500, 0.430),
             (0.284, 0.880), (0.115, 0.880)]
    bars = [rc(s, 0.462 + i * 0.028, 0.628 - h, 0.020, h, c["sub"], radius=0.008)
            for i, h in enumerate((0.055, 0.080, 0.105))]
    cross = rc(s, 0.330, 0.640, 0.340, 0.052, c["accent"], radius=0.026)
    return lay([poly(s, outer, c["main"]), cross]) + lay(bars)


LOGOS = [
    ("agent_graph", "A · 智能节点柱", logo_a,
     "四根递升的柱子 + 上方智能节点用连线指过去",
     "agent 生成图表 —— 最直白，不用解释"),
    ("agent_core", "B · 六角核心", logo_b,
     "六边形核心 + 三个环绕节点与连线",
     "多智能体协同 / 核心调度数据源，偏技术稳重"),
    ("agent_gear", "C · 齿轮 + 数据", logo_c,
     "齿轮轮廓 + 中心镂空处的上升折线",
     "制造业与数据洞察的双关，行业属性最强"),
    ("agent_orbit", "D · 环轨 + 数据点", logo_d,
     "两段断开的环形轨道 + 轨道上的数据点",
     "持续监测 / 闭环，抽象、平台感"),
    ("agent_letter_a", "E · 抽象字母 A", logo_e,
     "几何化字母 A + 内部空腔的三根数据柱",
     "有品牌感，便于与系统名并排组合"),
]


def save(key: str, size: int, layers: list, suffix: str = "") -> list[str]:
    obj = {"dsl": 1, "size": [size, size], "layers": layers}
    name = f"{key}{suffix}"
    Scene.from_dict(obj).render().save(OUT / f"{name}_{size}.png")
    made = [f"{name}_{size}.png"]
    if size == 512:
        Scene.from_dict(obj).render(SvgBackend(size, size)).save(OUT / f"{name}.svg")
        made.append(f"{name}.svg")
    return made


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for key, title, fn, form, read in LOGOS:
        files = []
        for sz in SIZES:
            files += save(key, sz, fn(sz))
        files += save(key, 512, fn(512, mono=True), suffix="_mono")
        files += save(key, 512, fn(512, mono=True, light=True), suffix="_mono_light")
        MANIFEST.append({"key": key, "title": title, "form": form, "read": read})
        print(f"  ✅ {title:<14} {len(files)} 个文件  {', '.join(files[:2])} …")
    (OUT / "logos.json").write_text(
        json.dumps(MANIFEST, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n共 {len(MANIFEST)} 个方案 · 每个含 SVG + 512/64/32/16 PNG + 单色版")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
