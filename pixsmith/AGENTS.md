# AGENTS.md — 给 AI agent 的操作手册

> 对应版本：v0.8.0
> 给人读的文档在 [`README.md`](README.md) 与 [`docs/能力边界.md`](docs/能力边界.md)；
> 这一份只讲**该怎么做**，不讲背景。权威能力清单以 `pixsmith spec --json` 为准（它从代码生成，不会过期）。

## 这是什么

用代码生成背景 / 底纹 / 装饰件，输出 **PNG（位图）或 SVG（矢量）**。
不找素材、不联网、**同 seed 必然同字节** —— 所以产物能进 git、能 diff、能回滚。

---

## 标准工作循环（照这个顺序走，能省掉一半往返）

```bash
pixsmith spec --json --only marble     # ① 先查能力与参数名，**不要猜**
                                       #   （全量 29KB，用 --only 压到 ~3KB）
# ② 写场景 JSON
pixsmith validate scene.json --backend svg   # ③ 只校验不渲染 —— 提前知道能不能出矢量
pixsmith render scene.json --report          # ④ 渲染 + 拿自检报告
# ⑤ 看报告判断画对没画对；不对就改，回到 ③
```

### 做图标 / 标识时：用 `export` 一次出齐，别手工循环

```bash
pixsmith export scene.json -o out/ --sizes 512,64,32,16 --svg \
        --mono '#0A1730' --mono-light '#FFFFFF'
```

一轮出齐「尺寸阶梯 × 单色墨 × 矢量」。手工循环的典型漏项是**只做了深墨单色版** ——
单色标识的标准用法是浅底深墨、深底白墨，只做深墨等于漏了一半（深墨压在深底上就是没画）。

- `--sizes` 省略时只用场景自己的尺寸（此时等价于 `render` + 矢量 + 单色版）
- 单色改写按 `Param` 声明的类型动手，**保留各自透明度**（丢了会让抗锯齿边缘变硬边）；
  覆盖不到的多色参数（如色阶列表）会在渲染后自检发现并**报警**，
  不会静默交出一张"看着是单色、其实混了原色"的图

### 交付用 `export`，**自检用 `sheet`**

`export` 出的是**一堆文件**，你自己看不过来。要判断"16px 那档还认不认得出"，
用联络表把同一份设计的多档尺寸按**真实像素大小**摆进一张图：

```bash
pixsmith sheet scene.json --sizes 512,64,32,16 -o sheet.png --json
```

- **不缩放、不重采样**：每个格子是按目标尺寸**单独渲染**的原始像素。
  把 512 采样到 16 会把抗锯齿边缘糊成灰，而真按 16px 渲染可能是干净的 3 个像素 ——
  两者看着"差不多"，判断结论却可能相反。**所以别用外部工具拼这张表。**
- 512 与 16 的格子边长比就是 **32:1** —— 哪一档开始糊，一眼的事。
- **格子画不了标签**（本项目不碰字体光栅化），行列含义走机器可读的输出：
  `--json` 给 `tiles`（`row` / `col` / `recipe` / `size` / `at`）。不带 `--json` 时
  每个格子也会在 stdout 上打一行 `[行,列] 配方 尺寸 → (x, y)`。
- 多个配方就多给几个输入：`pixsmith sheet a.json b.json --size 256`
  （**行 = 配方，列 = 尺寸档**，横向比档位、纵向比设计）。
- 底色默认棋盘格 —— 刻意不用纯色，好让**透空**显形（`report()` 里的
  `transparent_ratio` 只能给你数字，这里给你看）。要查深底白墨就
  `--background '#0A1730'`，要透空就 `--background none`。

### 要旋转 / 镜像 / 取景整张图时：用 `transform`，别自己算矩阵

```jsonc
{"dsl": 1, "size": [1920, 1080],
 "ops": [ /* … */ ],
 "transform": {"rotate": 15}}          // 场景级：作用在**最终合成结果**上
```

- **两个位置，语义不同，都别混**：
  - 场景顶层的 `transform` → 「**整张成品**」的姿态，在全部图层合成**之后**套用
  - 图层里的 `{"op": "transform"}` → 「**这一层已绘内容**」，所以能做「画 A → 转 30° → 画 B」
  - 多层场景**没有"最后"这个位置**（每层各画进子画布再合成），所以"整张成品转 15°"
    只能由场景级字段承接 —— 别想着往最后一层里塞。
- 参数：`rotate`（度，正 = 屏幕上顺时针）· `scale`（**等比**，必须 > 0）·
  `translate` `[dx,dy]` · `pivot` `[x,y]`（默认画布中心）·
  `flip` `none|h|v|both` · `crop` `[x,y,w,h]`
- **`crop` 是取景，不是改尺寸**：把那块区域铺满整张画布（取景比例 ≠ 画布比例时
  天然就是非等比拉伸 —— 所以 `scale` 只做等比，非等比走 `crop`）。
- **`transform` 从不改变画布尺寸**。旋转后露出的四角是**透明**的，不会自动扩画布；
  想真的改输出尺寸，改场景的 `size` 或走 `export --sizes`。
- 两个后端都支持它，但保真度不同：矢量端是 `<g transform="matrix(…)">`（无损、精确），
  位图端是**双线性**重采样（放大/旋转后边缘略软）。要无损就输出 SVG。
- 旋转 / 镜像后 `--report` 的 `transparent_ratio` 会变高 —— 那是露出的四角，**正常的**。

---

## 三条操作规程

### 1️⃣ 优先走 JSON 快捷通道；装不下再走 Python 创作通道

两条通道**共享同一个能力层**，不存在"某个效果只有一边能做"。差别只在表达方式：

| | **JSON 快捷通道** | **Python 创作通道** |
|---|---|---|
| 形式 | `pixsmith render scene.json` / `Scene.from_dict({...})` | `Canvas` / 算子 / `Scene` 的 Python API |
| 优势 | **token 最省**、`validate` 可校验、可 diff、可分享 | **表达力不受限** |
| 用它当默认 | ✅ **先试这条** | 装不下时才用 |

```jsonc
// JSON 快捷通道：几十个 token 说清一张图
{"dsl": 1, "size": [1920, 1080], "background": "#0A1730",
 "ops": [{"op": "linear_gradient", "begin": "#0A1730", "end": "#C8102E"},
         {"op": "pattern", "pattern": "marble", "params": {"seed": 7}},
         {"op": "blur", "radius": 8}]}
```

**什么时候必须换创作通道**（JSON 表达不了）：循环参数化、数学几何、条件逻辑、
读取外部数据来决定画什么。

```python
# Python 创作通道
import math
from pixsmith import Canvas
c = Canvas(1200, 630, "#0A1730")
for i in range(72):                       # 循环 + 数学 —— JSON 做不到
    a = i * math.pi / 36
    c.capsule(600, 315, 600 + math.cos(a) * 700, 315 + math.sin(a) * 700,
              3.0, f"#F2C14E{40 + i * 3:02X}")
c.save("rays.png")
```

> 反方向也成立：**能把 Python 逻辑降到 JSON 的，就降下来** —— 更省 token、更可校验、
> 也更容易被别人接手改。

### 2️⃣ 写图案必须声明它需要什么

图案**只应调用后端协议里的方法**（清单见 `src/pixsmith/backend.py`）。
一旦直接碰 `numpy` 数组，它就被锁死在位图后端上 —— 矢量输出时会失败。

确需逐像素时**显式声明**：

```python
@pattern("my_texture", "...", [...], category="texture",
         requires=("paint",))                    # 恒定需要位图能力
def my_texture(c, *, ...): ...

# 只在某个参数启用时才需要 → 用 requires_fn，别一律声明（那会挡掉本来可用的组合）
@pattern("starfield", "...", [Param("milky", "float", 0.0, "...")],
         category="texture",
         requires_fn=lambda p: ("paint",) if float(p.get("milky") or 0) > 0 else ())
```

`tests/test_dual_backend.py::test_pattern_is_dual_backend_or_declares_why_not`
会强制这条：**要么能在矢量后端跑，要么显式声明为什么不能**。

### 3️⃣ 渲染后一定用 `--report` 自查（你看不见图）

```bash
pixsmith render scene.json --report
```

```json
{"size": [1920,1080], "opaque_ratio": 1.0, "fully_transparent": false,
 "content_bbox": [0,0,1919,1079], "touches_edge": true,
 "mean_luma": 0.16, "contrast": 0.03,
 "channel_range": {"r": [10,200], "g": [16,23], "b": [46,48]},
 "corner_colors": {"tl": "#67142F", "tr": "#0B1730", "bl": "#C7102E", "br": "#6B132F"},
 "dominant_colors": ["#661122","#771122","#551122","#881122"],
 "dominant_coverage": 0.16,
 "hints": ["主色覆盖率低（最多的颜色只占 16% 像素）：这张图**没有**「主色」…"]}
```

**⭐ 判断"颜色参数生效了没"，要用 `channel_range` 和 `corner_colors`，不要用 `dominant_colors`。**

理由是一个真实的坑：`dominant_colors` 回答的是「**哪种颜色占的面积最多**」，
而你真正想问的是「**我设的颜色参数生效了吗**」—— 这是两个不同的问题。
**对角渐变的颜色分布是梯形的，中间调占面积最多**，所以 top-4 必然全是中间调，
你设的端点色一个都进不去。上面这个例子里 `dominant_colors` 全是中国红渐变的中间调紫，
看着像参数传错了 —— 而渐变完全正确（`bl: #C7102E` 就是端点色，`r` 跨度 10→200）。

| 字段 | 回答什么问题 | 怎么用 |
|---|---|---|
| `channel_range` | **参数生效了吗** | 设了红渐变 → `r` 必须有跨度。跨度接近 0 说明颜色没生效 |
| `corner_colors` | **渐变端点/方向对吗** | 四角取样，直接看到端点色 |
| `dominant_coverage` | 这张图**有没有**主色 | ≥ 25% 才说明有主色，此时 `dominant_colors` 才有参考价值 |
| `dominant_colors` | 面积最多的颜色 | **仅在有主色时可用**（图标 / 纯色 / 条纹这类） |
| `fully_transparent` | 是不是完全没画出来 | `true` → **一定画错了** |
| `opaque_ratio` | 内容占了多少面积 | 过低 → 大概率画到画布外了 |
| `touches_edge` | 内容是否贴边 | 可能是有意的，也可能是尺寸没算对 |
| `contrast` | 整幅有没有明暗层次 | ⚠️ 渐变场景里它天然很低（实测 0.03），**别拿它当"颜色不对"的证据**；`transform` 旋转后也会被拉低（露出的四角是透明区） |

> `hints` 字段会在这些情况**自己说出来**（比如"主色覆盖率低，别用 dominant_colors 判断"）。
> **先看 hints，再看数字。**

---

## 怎么发现能力（不要猜）

```bash
pixsmith spec                              # 总览：后端 / 动词 / 图案 / 混合模式 / 噪声种类
pixsmith spec --json --only blur           # 只拿 blur 的规格（含参数类型与默认值）
pixsmith spec --json --kind verb           # 只要动词
pixsmith spec --json --kind pattern --category natural   # 按分类过滤
pixsmith show marble                        # 单个图案的人话参数说明
pixsmith show blur --json                   # 动词也有 JSON 规格
pixsmith list --json                        # 全部图案（按分类）
```

**错误也可以机器可读**：

```bash
pixsmith --json-errors render nope
# → {"error": {"type": "KeyError", "message": "没有名为 'nope' 的图案。可用：[...]"}}
```

退出码：**0 = 成功，2 = 用法/输入错误**（不是崩溃）。任何情况下都不该出现 Traceback。

---

## 常见错误 → 对策

| 报错 | 含义 | 怎么办 |
|---|---|---|
| `unknown verb 'xxx'` | 动词名写错 | `pixsmith spec --json --kind verb` 看可用动词 |
| `没有名为 'xxx' 的图案或动词` | 图案名写错 | `pixsmith list --json` |
| `不认识参数：['xxx']` | 参数名写错 | `pixsmith spec --json --only <key>` |
| `pattern op 不认识键 ['xxx']` | **参数忘了嵌进 `params`**（`pattern` 元 op 的键写在了 op 顶层） | 改成 `{"op":"pattern","pattern":"star","params":{"points":3}}`。报错里会直接给这句 |
| `后端 SvgBackend 不支持：…` | 用了矢量后端表达不了的效果 | 换位图后端（去掉 `-o *.svg`），或改用 `validate` 报出的替代组合 |
| `不支持的 DSL 版本` | `dsl` 字段写错 | 场景必须写 `"dsl": 1` |
| `场景缺少 'size'` | 没给尺寸 | 给 `"size": [w, h]` 或 `"aspect": "16:9"` |
| `--set 只能配单个配方用` | `sheet` 给多份配方却想统一覆盖参数 | 参数写进各自的场景 JSON 再用 `sheet` 拼 |
| `联络表会到 … 超过上限 16 MP` | 档位数 × 配方数把画布撑太大 | 减档位 / 减配方，或调小最大档 —— `sheet` **不会替你缩**（缩了这张表的结论就作废） |
| `'transform' 不认识参数：['xxx']` | `transform` 的键名写错 | `pixsmith show transform` |
| `scale 必须 > 0` | `scale` 传了 0 或负数 | 想做镜像请用 `flip: "h"` / `"v"`，不是负的 scale |
| `仿射矩阵不可逆` | 矩阵退化（几乎总是 `scale: 0`） | 同上 |
| `flip 不认识 'xxx'` | `flip` 写了别的词 | 只用 `none` / `h` / `v` / `both` |

---

## 如果用户是"先手工调、再交给你"

人在**调参台**里（`pixsmith serve`）拖滑块调好效果后，会给你一段**场景 JSON**。
**直接用它**，别自己重写参数 —— 那是他看了图调出来的，比你的猜测准。
调参台、CLI、MCP 产出的是**同一个场景 JSON**，三者互通。

## 如果你是通过 MCP 接入的

直接调用 `spec` / `validate` / `render` 三个工具即可，不用拼命令行。
两条差异要注意：

- `render` **默认回一张缩小预览图**（你可以直接看见结果），
  不需要就传 `embed_preview: false` 省上下文。
- 工具失败返回的是 `isError: true` 的**内容块**（不是协议错误），
  里面是结构化 JSON，照着改就行。

细节见 [`docs/31-MCP接入.md`](docs/31-MCP接入.md)。

## 硬性禁忌

仓库内**任何地方**（代码、注释、文档、JSON 的 `note` 字段）都不得出现
指向特定厂商 / 产品的字样或描述。本项目**不带来源叙事** —— 它自带实现、自带参考物、
自带测试，请按独立项目描述它。详见 [`CONTRIBUTING.md`](CONTRIBUTING.md) 第六节。

## 不要做的事

- ❌ 不要为了"效果更好"引入新依赖 —— 能用 100 行 NumPy 写出来的就自己写
- ❌ 不要在图案里直接操作 `numpy` 而不声明 `requires`
- ❌ 不要用 `random` / `np.random.rand()` —— 必须 `numpy.random.default_rng(seed)`，否则破坏可复现承诺
- ❌ 不要把"静默降级"当优雅 —— 缺能力就报错，静默降级会产出"看着对但缺了效果"的图
