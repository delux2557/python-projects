# pixsmith

> **不找素材，用代码画。** 程序化生成背景 / 底纹 / 装饰件 PNG —— 同参数必然同输出。

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-166%20passed-brightgreen.svg)](tests/)

---

## 为什么会有这个东西

做汇报材料、海报、界面图的人，八成经历过这个循环：

> 需要一张"深蓝到中国红的渐变底图" → 打开图库找 → 找到的要么比例不对、要么颜色差一点 →
> 下载下来用 PS 调色 → 调完发现另一张图跟它不是一个风格了 → 重复十遍。

`pixsmith` 把这件事变成一行命令：

```bash
pixsmith render gradient --size 1920x1080 --set begin=#0A1730 --set end=#C8102E --set angle=118 -o bg.png
```

**它解决的不是"没有图"，而是"图的风格对不齐、改不动、也没法复现"。**

| 你现在的做法 | 换成 pixsmith |
|---|---|
| 图库里挑，风格靠运气 | 一套参数产出一个系列，风格必然一致 |
| 颜色差一点要开 PS | 改一个 hex 值，重跑 |
| 三个月后想再要一张同款底图 | 配方 JSON 在 git 里，一字不改地复现 |
| 图片版权来源不清 | 全部由代码生成，无第三方素材 |
| 每张图手动导出 | `pixsmith gallery` 一次出几十张 |

---

## 它**不**做什么（请先看这一段）

这一节比能力表更重要 —— 免得你装了之后发现不是想要的东西。

| | 它擅长 | 它做不到，也不该硬做 |
|---|---|---|
| 类别 | 渐变 / 条纹 / 点阵 / 网格 / 噪点 / 星空 / 半调网点 / 扫描线 / 光芒 / 齿轮 / 透视地板 / 星形 | 真实照片、人物、复杂插画 |
| 关键优势 | **确定性**（同 seed 同字节）、**参数化**（改 JSON 不改代码）、**无版权风险**、**无素材依赖** | — |
| 典型用途 | 界面/海报底图、图表装饰、版式占位件、图示化符号 | "帮我找一张好看的照片" |
| 该用什么替代 | — | 图库（Unsplash / Pexels）、AI 生图、图标库（iconfont / FontAwesome） |

还有三条技术约束，提前说清楚：

- **输出是位图，不是矢量** —— 没有贝塞尔曲线，没有文字排版。要那两者请用 `drawsvg` / `pycairo`。
- **有一个依赖**：`numpy`。它买来的是 **6–42×** 的提速（实测见下文），但确实不是"零依赖"。
  如果你要绝对零依赖，`benchmarks/pure_python_reference.py` 是一份等价的纯 Python 实现。
- **不是绘图库**：`Canvas` 只有 8 个图元（圆 / 环 / 椭圆 / 矩形 / 线段 / 弧 / 多边形 / 抠洞）。
  能被它画出来的东西，本质上都是"这些图元叠出来的"。

---

## 安装

```bash
pip install numpy          # 唯一运行依赖
pip install -e .           # 从源码安装（含 pixsmith 命令）
# 或只跑源码：
export PYTHONPATH=src && python -m pixsmith --help
```

开发：

```bash
pip install -e ".[dev]"
pytest                     # 166 个用例
python benchmarks/bench.py # 性能基准
```

---

## 30 秒上手

```bash
pixsmith list                                  # 看有哪些图案（23 个）
pixsmith show gradient                         # 看某个图案的全部参数与默认值
pixsmith spec                                  # 能力清单（给 AI agent 的自述文件）
pixsmith render gradient --size 1920x1080 \
    --set begin=#0A1730 --set end=#C8102E -o bg.png
pixsmith render gradient --size 1920x1080 -o bg.svg   # 同一份参数 → 矢量输出
pixsmith render cover.scene.json --report       # 渲染 + 自检报告
pixsmith gallery --out gallery --svg           # 全部图案 + HTML 索引（附矢量版）
```

Python：

```python
from pixsmith import Canvas, Scene, SvgBackend

Canvas(1920, 1080, "#0A1730").save("plain.png")

# 场景（可序列化、可分层、可混合）
scene = Scene.from_dict({
    "dsl": 1, "size": [1920, 1080], "background": "#0A1730",
    "ops": [{"op": "linear_gradient", "begin": "#0A1730", "end": "#C8102E"},
            {"op": "pattern", "pattern": "marble", "params": {"seed": 7}},
            {"op": "blur", "radius": 8}],
})
scene.render().save("cover.png")                       # 位图
scene.render(SvgBackend(1920, 1080)).save("cover.svg")  # 矢量
scene.report()                                          # 自检报告
```

---

## 两条通道：JSON 快捷通道 ｜ Python 创作通道

同一个能力层，两个入口。**不是"高级 / 初级"的关系，是两种不同的取舍**：

| | **JSON 快捷通道** | **Python 创作通道** |
|---|---|---|
| 形式 | 声明式场景（`Scene.from_dict` / `pixsmith render x.json`） | 命令式 API（`Canvas` / `Scene` / 算子） |
| 长处 | **token 最省**、可 schema 校验、可 diff、非程序员能改、远程调用安全 | **表达力不受限** |
| 短处 | 表达力受限于预设的 op 集合 | 冗长；写错一处就跑不起来 |
| 适合 | 常见需求、需要人来改参数的场景、AI agent 的默认路径 | 循环参数化、数学几何、条件逻辑 —— JSON 装不下的那些 |

```python
import math
from pixsmith import Canvas, Scene

# 快捷通道：几十个 token 说清一张图
Scene.from_dict({"dsl": 1, "size": [1920, 1080], "background": "#0A1730",
                 "ops": [{"op": "linear_gradient", "begin": "#0A1730", "end": "#C8102E"}]})

# 创作通道：表达力没有天花板
c = Canvas(1920, 1080, "#0A1730")
for i in range(72):                       # 循环？参数化？数学？都可以
    a = i * math.pi / 36
    c.capsule(960, 540, 960 + math.cos(a) * 700, 540 + math.sin(a) * 700,
              3.0, f"#F2C14E{40 + i * 3:02X}")
```

> 两条通道都**共享同一个能力层**，没有重复实现 —— 所以不存在"某个效果只有一边能做"。
> 判断用哪条：**先试快捷通道，装不下再走创作通道。** 反过来也成立（能把 Python 逻辑
> 降到 JSON 的，就降下来，那样更省、更稳、可分享）。

---

## 架构：为什么加一个后端不用改任何图案

```
backend.py        协议：能力有哪些（谁实现谁就是后端）
     ↓
ops.py            动词表：场景里能写什么
geometry.py       几何：只算顶点，不碰像素   ← 两个后端共用同一份顶点
filters/blend/noise/field/color/codec   算子与底层工具
     ↓
canvas.py  Canvas      位图后端（NumPy 逐像素）
svg.py     SvgBackend   矢量后端（写 XML）
     ↓
patterns/         素材：**只调协议方法**，所以能跑在任意后端上
     ↓
scene.py          Scene：尺寸 + 底色 + 图层 + 混合（唯一的编排者）
```

**四条把"双后端"变成硬约束的设计：**

1. **几何与渲染分离。** 星形/齿轮的顶点算在 `geometry.py`，两个后端各自渲染同一份顶点 ——
   不会出现"位图的圆角和矢量的圆角对不上"。
2. **图案只调协议方法。** 图案里出现 `numpy` 操作，它就被锁死在位图后端了；
   确需如此时**必须**用 `requires=(...)` 声明 —— 有一条契约测试强制这件事。
3. **能力校验只在渲染前做，且不静默降级。** 后端缺能力就报错并给出替代方案。
   理由：静默降级会产出"看着对但缺了效果"的图，而 **agent 看不见图**。
4. **参数相关的依赖也声明。** `starfield` 默认参数双后端通用，但开了银河带就需要位图能力 ——
   用 `requires_fn` 表达，而不是一律声明成"需要"（那会把本来可用的组合也挡在门外）。

### 双后端能力对照

| | 位图 `Canvas` | 矢量 `SvgBackend` |
|---|---|---|
| 输出 | PNG | SVG（**PPT 自 2016 原生支持**） |
| 强项 | 逐像素纹理、噪点、非线性滤镜、模糊 | 无损缩放、体积小、可编辑 |
| 图案支持 | **23 / 23** | **15 / 23**（其余 8 个显式声明了为什么不能） |
| 一元算子 | 全部（`grain` 也可） | blur / adjust / posterize / solarize / invert / grayscale |
| 逐像素场 `paint` | ✅ | ❌ 矢量域没有对应物 |

不支持的那 8 个是：`stripes` `checker` `noise` `vignette` `starfield`(开银河带时)
`marble` `clouds` `cracks` `brushed` —— 全是**逐像素场**，这是矢量域的真实边界，不是偷懒。

---

## 图案一览（23 个，5 类）

完整效果见 [`gallery/index.html`](gallery/index.html)（由 `pixsmith gallery --svg` 生成，
支持矢量后端的图案另附 `.svg`）。

### background · 背景（最通用，不挑主题）

| 图案 | 说明 | 关键参数 |
|---|---|---|
| `gradient` | 线性渐变（可加中段色标） | `begin` `end` `mid` `mid_at` `angle` |
| `radial` | 径向渐变 | `inner` `outer` `cx` `cy` `radius` |
| `stripes` | 等宽条纹（可羽化） | `c0` `c1` `count` `angle` `ratio` `soft` |
| `checker` | 棋盘格 | `c0` `c1` `cell` `angle` |
| `dots` | 点阵底纹（可错行） | `bg` `dot` `cell` `radius` `stagger` |
| `grid` | 网格 / 蓝图底纹 | `bg` `line` `major` `step` `every` |
| `rings` | 同心圆环 | `bg` `ring` `count` `cx` `cy` `width` |
| `noise` | 颗粒噪点叠加 | `base` `amount` `seed` `mono` |
| `vignette` | 四角压暗（叠在已有内容上） | `color` `strength` `power` |

### texture · 纹理

| 图案 | 说明 | 关键参数 |
|---|---|---|
| `starfield` | 星空（可用 `milky` 加银河带） | `count` `seed` `colors` `glow` `milky` |
| `halftone` | 半调网点（点径随径向/线性场变化） | `bg` `dot` `cell` `mode` `angle` |
| `scanlines` | 扫描线 / 屏幕栅格 | `gap` `alpha` `hot` |

### natural · 自然材质（噪声族，v0.2 新增）

这四个是 `noise.py` 的价值证明 —— 在它之前，库里只有"均匀颗粒噪点"，那是**假噪点**：
只有颗粒感、没有结构感。云、大理石、裂纹、拉丝全部来自**多尺度平滑噪声 + 域扭曲**。

| 图案 | 说明 | 关键参数 |
|---|---|---|
| `marble` | 大理石：域扭曲的 fBm 条纹 | `stone` `vein` `bands` `warp` `detail` |
| `clouds` | 云层：fBm 直接当透明度（透明底可直叠） | `color` `coverage` `softness` `warp` |
| `cracks` | 裂纹 / 龟裂：细胞噪声的边界场 | `freq` `width` `glow` `jitter` |
| `brushed` | 拉丝金属：沿一个方向拉伸的噪声 | `angle` `freq` `jitter` `contrast` |

> `brushed` 的手法值得一提：先生成**一维**噪声剖面，再按"投影到垂直方向"的坐标去查表。
> 这样任意角度下丝纹都严格平行，而且只算一维噪声 —— 比生成二维噪声快得多。

### shape · 几何

| 图案 | 说明 | 关键参数 |
|---|---|---|
| `ray_burst` | 放射光芒阵列 | `count` `inner` `length` `width` `jitter` |
| `gear` | 齿轮（中空外圈 + 齿 + 辐条 + 中心孔） | `teeth` `tooth` `spokes` `hub` `hole` |
| `perspective_grid` | 透视地板（纵深网格） | `vanish` `horizon` `rays` `growth` |
| `star` | N 角星（可旋转、可描边） | `points` `inner` `rotate` `outline` |

### festive · 节日（主题件的现成符号）

| 图案 | 说明 | 关键参数 |
|---|---|---|
| `flag_cn` | 五星红旗（**按 GB 12982 标准算星位与指向角**） | `bg` `star` `padding` |
| `fireworks` | 烟花（多组爆发 + 拖尾 + 亮头 + 辉光） | `bursts` `seed` `palette` `reach` |
| `moon` | 满月（径向明暗 + 环形山 + 月晕） | `craters` `seed` `glow` `radius` |

> 节日类为什么留在库里：它顺便证明了一件事 —— **同一套图元能画出「有标准答案的图」**，
> 而不只是渐变和条纹。`flag_cn` 是唯一一个有官方标准的图案，
> 所以 `tests/test_flag_cn.py` 用 20 个用例从渲染出的像素**反测**国标：
> 大星中心在 (5, 5)、半径 3u、五个尖角朝向、凹口比值、
> **四颗小星各有一个角尖对准大星中心**、黄星总面积与理论值误差 < 5%。

---

## 配方（recipe）：把参数从代码里搬出来

配方是这块东西**能交给非程序员**的关键 —— 一个能进 git、能 diff、能互相传的 JSON：

```json
{
  "pattern": "gradient",
  "size": [1920, 1080],
  "background": "#00000000",
  "params": { "begin": "#0A1730", "end": "#C8102E", "mid_at": 0.55, "angle": 118 }
}
```

```bash
pixsmith render recipes/bg_deep_to_red.json -o bg.png
```

CLI 调参的结果可以直接沉淀成配方，不用手写：

```bash
pixsmith render star --size 2560x1440 --set points=8 --print-recipe -o star.png
# 会打印等价的最小配方 JSON（只列出与默认值不同的项）
```

已有示例：[`recipes/`](recipes/) 下有渐变底图、星空、五星红旗三份。

---

## 性能：为什么带了一个 `numpy` 依赖

`benchmarks/bench.py` 与纯 Python 参考实现跑**完全相同的参数与工作量**（单线程、透明画布）：

| 工作负载 | NumPy | 纯 Python | 加速比 |
|---|---|---|---|
| 圆 ×300 (512×512) | 17.4 ms | 112.1 ms | **6×** |
| 矩形 ×400 (512×512) | 26.4 ms | 254.5 ms | **10×** |
| 放射线 ×24 / 长 400px (768×768) | 31.9 ms | 455.1 ms | **14×** |
| 全画布线性渐变 1920×1080 | 234.6 ms | 4207.7 ms | **18×** |
| 全画布线性渐变 2560×1440 | 395.9 ms | 7447.1 ms | **19×** |
| 正十边形 ×25 (512×512) | 1036.7 ms | 25683.2 ms | **25×** |
| 放射线 ×46 / 长 1300px (2560×1440) | 144.6 ms | 6120.1 ms | **42×** |

**数字不夸张，我把话说清楚**：

- 加速比与**图元面积**正相关。小图元（半径 9 的圆）只有 **6×** ——
  因为此时 NumPy 的每次调用开销（数组分配）占了大头，向量化的好处被吃掉了。
- 面积越大越划算：**42×** 出现在"2560×1440 画布上的长线段"这类最吃亏的场景。
- 所以"为 6× 提速引入一个硬依赖"是**可以被质疑的**。本项目的判断是：底图动辄 1920×1080 起，
  且批量出图是常态，这个交换划算；但数字摆在这里，你可以自己判断。
- 想要零依赖：`benchmarks/pure_python_reference.py` 是逐像素等价的实现
  （`tests/test_parity_with_reference.py` 证明两者偏差 ≤1/255），只是慢。

---

## 三条设计取舍

1. **输出 PNG，不输出矢量。** 目标是"当底图用"，位图够用，而且省掉字体/路径依赖。
2. **确定性优先于"更好看"。** 所有随机都走 `numpy.random.default_rng(seed)`，同 seed 必然同字节
   —— 所以底图能进 git、能 diff、能当测试基线。AI 生图和图库都做不到这一点。
3. **配方是一等公民。** 参数化不是为了自己写得爽，是为了让别人**不改代码**也能用。

### 一处被测试钉住的实现缺陷（`ring` 的内边缘羽化）

`ring()` 的朴素写法有个隐蔽问题：外圈覆盖率**没归一化**就乘 `(1 - ci)`，
结果被外层的截断"救"了回来，代价是**内边缘羽化失效、退化成硬边**（实测差 **156/255**）。

判断依据不是眼睛，是一条回归测试：
`tests/test_parity_with_reference.py::test_ring_divergence_from_original_is_documented`
—— 它同时断言"修正版必须一致（≤1/255）"和"朴素版必须差 >100"，两头都卡住。

> 这个例子说明了 `benchmarks/pure_python_reference.py` 的价值：
> 它是一份**刻意保持朴素**的实现，专门用来把这类"看起来对、其实语义漂了"的地方照出来。

---

## 项目结构

```
src/pixsmith/
├─ backend.py       后端协议 + 能力校验（缺能力就报错，不静默降级）
├─ canvas.py        位图后端：图元 + 覆盖率抗锯齿 + Alpha 合成（NumPy 向量化）
├─ svg.py           矢量后端：图元 → SVG 元素；一元算子 → <g filter>
├─ scene.py         场景：尺寸 + 底色 + 图层 + 混合（唯一的编排者）
├─ ops.py           动词表 + 通用分发
├─ geometry.py      几何：只算顶点，两个后端共用
├─ field.py         参数场（方向 / 径向）
├─ filters.py       一元算子（blur / adjust / posterize / solarize / grain …）
├─ blend.py         二元算子（14 种混合模式，遵循 CSS-PDF 模型）
├─ noise.py         噪声族（Perlin / Value / Cellular / fBm / 域扭曲）
├─ params.py        参数声明（CLI 校验 / 帮助文本 / 能力清单三处共用）
├─ manifest.py      能力清单（给 AI agent 的自述文件）
├─ codec.py         PNG 编码（zlib + struct，无图像库）
├─ color.py         颜色解析 / 插值 / 色标场
├─ recipes.py       配方入口（兼容单图案写法，内部走 Scene）
├─ cli.py           命令行
├─ mcp_server.py    MCP server（手写 JSON-RPC，零依赖）
└─ patterns/        素材：只用协议方法画东西，所以后端可替换
   backgrounds · textures · geometry · festive · natural
tests/              283 个用例
benchmarks/         纯 Python 参考实现 + 性能基准
examples/           可运行的四个示例
tools/mcp_smoke.py  MCP 端到端冒烟（起真实子进程走完整握手）
recipes/            配方 JSON 示例
gallery/            由 CLI 生成的图案画廊（含矢量版）
```

**加一个图案**只要三步：在 `patterns/` 的某个模块里写一个函数 → 加 `@pattern(...)` 声明参数 →
`pip install -e .` 重装。测试会自动把它纳入
（`test_every_pattern_renders_with_defaults` / `test_pattern_is_dual_backend_or_declares_why_not`
等都是对注册表参数化的，不用手写新用例）。

---

## 测试

```bash
pytest          # 328 passed
```

六个层次的验证：

| 层次 | 文件 | 验什么 |
|---|---|---|
| **等价性** | `test_parity_with_reference.py` | 与纯 Python 参考实现**逐像素**一致（容差 ≤1/255） |
| **双后端契约** | `test_dual_backend.py` | 每个图案**要么能在矢量后端跑，要么显式声明为什么不能** |
| **国标符合性** | `test_flag_cn.py` | 从像素反测 GB 12982 的星位、指向角、面积 |
| **算子数学** | `test_operators.py` | 模糊不渗黑边 / O(n) / 混合公式符合 CSS-PDF 规范 |
| **噪声与核心** | `test_noise.py` / `test_core.py` | 空间相关性、分形叠加、颜色解析、PNG 结构（含 CRC） |
| **契约** | `test_patterns.py` / `test_cli.py` | 每个图案可渲染 / 可复现 / 非空；CLI 能跑能报错 |

> **双后端契约测试**是整个架构最重要的一条不变式。它把"双后端"从口号变成可执行的约束：
> 以后任何人加图案，只要偷偷用了 `paint()` 而不声明，测试立刻失败 ——
> 而不是等用户某天选 SVG 输出时才发现少了一半效果。

---

## 关于那份"慢的"实现

[`benchmarks/pure_python_reference.py`](benchmarks/pure_python_reference.py) 里有一份
**刻意保持朴素**的逐像素实现（`PixelCanvas`）。它有三个用途：

1. **语义基准** —— `Canvas` 是把逐像素公式向量化重写的结果，重写就有改错语义的风险，
   而单元测试只覆盖得到你想到的情况。逐像素对照是唯一能**自动证明"公式没变"**的手段。
2. **性能对照** —— 让"为什么要上 NumPy"有一个可复现的数字，而不是一句口头结论。
3. **当注释读** —— 逐像素写法把公式完整摊开，比任何文字说明都清楚。

它慢（图元代价是 O(包围盒面积)，长斜线会跑到分钟级），**别在正式代码里用它**。

## 贡献

**素材层欢迎天天加，能力层请先开 issue 对齐。** 加一个图案：

```bash
pixsmith new my_texture --category texture    # 生成骨架
# → 贴进 patterns/ 对应模块 → pip install -e . → pytest
```

`pixsmith new` 会把**收录三问**一起写进模板 ——
答不上"它演示什么能力组合 / 改哪个参数会怎样 / 什么场景该用它"的图案，别人抄不走，也就没有价值。

完整规则见 [`CONTRIBUTING.md`](CONTRIBUTING.md)（含双后端贡献注意事项、
提交前自检清单、以及**文字与命名禁忌**）。

## 用 MCP 接入（agent 直接当工具调用）

```bash
pip install -e .
pixsmith-mcp --selftest      # 检查服务器就绪
```

客户端配置：

```json
{"mcpServers": {"pixsmith": {"command": "pixsmith-mcp"}}}
```

暴露 **3 个工具**（刻意少而准）：`spec`（查能力）/ `validate`（只校验不渲染）/ `render`（渲染）。

三个 agent 友好的关键决定：

- **`render` 默认回一张缩小预览图** —— agent 看不见图是最大的障碍，给它一双眼睛比给更多数字有用
- **工具失败用 `isError: true`**（内容块会交给模型，它能自己改），而不是 JSON-RPC error（模型看不见原因）
- **`initialize.instructions` 里直接写操作规程** —— 那是协议给"怎么用我"留的位置

> ⭐ 这个服务器**只暴露 JSON 快捷通道，不暴露 Python 创作通道** —— 于是它天然没有代码执行面。
> 这正是"把能力分成两条通道"的架构回报：需要一个给不可信输入的安全沙箱时，
> **声明式那一层就是现成的沙箱**。

**没有额外依赖**：MCP 的 stdio 部分就是"换行分隔的 JSON-RPC 2.0 + 四个方法"，
本项目手写实现（约 300 行），不引 SDK。详见 [`docs/31-MCP接入.md`](docs/31-MCP接入.md)。

## 用 AI agent 驱动

仓库根目录有一份 **[`AGENTS.md`](AGENTS.md)** —— 给 agent 的操作手册，
把关键规程显式写出来（优先走哪条通道、写图案要声明什么、怎么用 `--report` 自查），
而不是指望 agent 自己从文档里推断。

配套的机器接口：

```bash
pixsmith spec --json --only marble   # 单个图案的规格（含参数类型与默认值）
pixsmith spec --json --kind verb     # 全部动词的规格
pixsmith validate scene.json         # 只校验不渲染（省一轮往返）
pixsmith --json-errors render x.json # 错误也是机器可读的 JSON
pixsmith render x.json --report      # 自检报告：channel_range / corner_colors / hints
```

## License

[MIT](LICENSE)
