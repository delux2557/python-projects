# 贡献指南

> 这个项目的目标是**成为一份可被抄改的参考物**：能力稳、素材开放、示例能直接跑。
> 所以贡献门槛分两档 —— **素材层欢迎天天加，能力层请先开 issue 对齐**。

---

## 快速上手（30 秒）

```bash
git clone git@github.com:delux2557/python-projects.git
cd python-projects/pixsmith
pip install -e ".[dev]"

pytest                       # 283 个用例，应当全绿
pixsmith gallery --out gallery --svg   # 生成画廊，肉眼过一遍
```

---

## 一、加一个图案（最常见的贡献）

```bash
pixsmith new my_texture --category texture -o /tmp/s.py   # 1. 生成骨架
#                                                          2. 贴进对应模块
pip install -e .                                          # 3. 重装
pytest                                                    # 4. 自动纳入测试
pixsmith gallery --out gallery --svg                      # 5. 看效果
```

**放哪个模块**：按类别选，别新开文件（除非是新的一类）

| 类别 | 模块 | 放什么 |
|---|---|---|
| `background` | `patterns/backgrounds.py` | 渐变、条纹、网格、噪点这类"铺满画布"的底 |
| `texture` | `patterns/textures.py` | 星空、半调、扫描线这类"有细节的纹理" |
| `natural` | `patterns/natural.py` | 大理石、云、裂纹、拉丝这类噪声派生的自然材质 |
| `shape` | `patterns/geometry.py` | 光芒、齿轮、透视网格、星形这类"一个符号" |
| `festive` | `patterns/festive.py` | 文化符号（现有：旗帜 / 烟花 / 月亮） |

## 二、⭐ 收录标准（三问 + 三条硬规则）

### 三问 —— 写进 docstring，答不上就别提交

1. **演示什么能力组合**：用了哪几个图元 / 算子，写具体名字
2. **改哪个参数会怎样**：一句话给使用者指路
3. **什么场景该用它**：海报底图？图示装饰？占位件？

> 这三问存在的理由：**参考物最大的风险是变成示例大杂烩** ——
> 一堆没人知道该在什么时候用的代码。答不上三问的图案，别人抄不走，也就没有价值。

### 三条硬规则

| 规则 | 原因 |
|---|---|
| **查重**：先 `pixsmith list` + 翻画廊，确认没有近似图案 | 参数差异 < 20% 的图案应当合并成一个（加参数），而不是并列两个 |
| **命名**：`lower_snake_case`，名词性、描述"是什么"不描述"怎么做" | `marble` ✅ / `generate_noise_marble` ❌ |
| **参数必须声明**：不许把参数藏进函数默认值 | `Param` 声明同时喂给 CLI 校验、帮助文本、能力清单三处；漏声明就会三处不同步 |

### 顺带：使用种子

任何随机都要有 `seed` 参数并走 `numpy.random.default_rng`。

> **这是本项目的核心承诺**：同 seed 同参数必然同字节。底图因此能进 git、能 diff、
> 能当测试基线。用 `random.random()` 或 `np.random.rand()` 会破坏这条承诺。

---

## 三、双后端：贡献者最容易踩的坑

图案**只应调用 `backend.py` 里列出的协议方法**。一旦直接操作 `numpy` 数组，
这个图案就被锁死在位图后端上了。

```python
# ✅ 两个后端都能跑
c.fill("#0A1730")
c.disc(100.0, 50.0, 20.0, "#F2C14E")
c.linear_gradient("#0A1730", "#C8102E", angle=118)
c.blur(8)

# ❌ 只有位图后端能跑 —— 必须声明
field = some_numpy_array                     # 逐像素场
c.paint(field)                               # 协议外扩展
```

确需逐像素时，**显式声明**（`tests/test_dual_backend.py` 会强制这件事）：

```python
@pattern("my_texture", "...", [...], category="texture",
         requires=("paint",))                # 恒定需要
def my_texture(c, *, ...): ...
```

**依赖只在某个参数启用时才出现时，用 `requires_fn`** —— 别一律声明成"需要"，
那会把本来可用的组合也挡在门外：

```python
@pattern("starfield", "...", [
    Param("milky", "float", 0.0, "银河带强度"),
], category="texture",
   requires_fn=lambda p: ("paint",) if float(p.get("milky") or 0) > 0 else ())
```

**不做静默降级**：后端缺能力就报错。理由 —— **agent 看不见图**，
静默降级会产出"看着对但缺了效果"的结果，它只会以为自己做对了。

---

## 四、改能力层（先开 issue 对齐）

`backend.py` / `canvas.py` / `svg.py` / `ops.py` / `filters.py` / `blend.py` / `noise.py`
属于**能力层**，它一变，所有素材都可能跟着变样。动之前请先开 issue 说明动机。

三条额外要求：

1. **新动词要同时给两个后端的实现，或明确它只属于位图后端**（并入 `RASTER_ONLY_METHODS`）
2. **加后端不用改任何图案** —— 如果你发现必须改图案，说明协议设计有问题，请提出来
3. **几何算在 `geometry.py`**（只算顶点，不碰像素），两个后端共用同一份 ——
   否则会出现"位图的圆角和矢量的圆角对不上"

---

## 五、提交前自检

```bash
pytest                                    # 全绿
python benchmarks/bench.py                # 性能没退化
grep -rn "厂商名" . --include=*.py --include=*.md   # 见下一节
```

- [ ] `pytest` 全绿（新图案会自动被契约测试纳入）
- [ ] 新图案的 docstring 回答了**收录三问**
- [ ] 有随机的都带 `seed`，且同 seed 两次渲染字节一致
- [ ] 用了协议外方法的话，`requires` / `requires_fn` 已声明
- [ ] `pixsmith gallery --out gallery --svg` 重跑过（画廊是作品，要跟着更新）
- [ ] 提交信息说明**为什么**，不只是**改了什么**

---

## 六、文字与命名禁忌（硬性）

本项目是**独立的通用图形工具**，面向各类平面设计、对 AI agent 友好。
**仓库内任何地方（代码、注释、docstring、文档、JSON 的 note 字段、提交信息）
都不得出现指向特定厂商 / 产品的字样或描述。** 包括但不限于：

- 具体商业产品的名称、缩写、文件后缀、环境变量
- `看板` / `大屏` / `报表` / `设计器` 这类指向特定软件品类、容易引起联想的术语
  → 请改用 **界面稿 / 汇报材料 / 海报 / 大幅面画面 / 排版软件** 等设计中性的说法
- "从某内部项目抽出"这类来源叙事 —— 本项目**不带来源叙事**，
  它自带实现、自带参考物、自带测试，请按独立项目描述它

提交前自己扫一遍：

```bash
grep -rniE "看板|大屏|报表|设计器" . \
  --include=*.py --include=*.md --include=*.json --include=*.toml \
  | grep -v node_modules
```

> ⚠️ **本节自身会命中这条检查** —— 禁用词清单如果不写出禁用词就没法用。
> 这是**预期例外**：扫描时请把 `CONTRIBUTING.md` 的「文字与命名禁忌」一节排除，
> 只看其余命中。

> 这一节为什么放在贡献指南里：**它是最容易被无意破坏的约定** ——
> 一句顺手写的类比、一个从别处复制的注释就可能带进来。所以它得是可执行的检查项，
> 而不是一句口头要求。

---

## 七、License

提交即表示你同意以 [MIT](../LICENSE) 许可发布你的贡献。
