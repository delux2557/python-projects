# 用 MCP 接入（让 agent 直接调用 pixsmith）

> 对应版本：v0.6.0

## 为什么要有这一层

CLI 能让 agent 用，但每调一次都要：装 Python 环境 → 拼一条 shell 命令 → 解析 stdout。
MCP 把这层磨平：**agent 直接把 pixsmith 当工具调用**，不用知道它是个 Python 包。

而且它顺带解决了一个安全问题：

> **这个服务器只暴露「JSON 快捷通道」，不暴露 Python 创作通道。**
> 于是它天然没有代码执行面 —— 这正是"把能力分成两条通道"的架构回报：
> 哪天需要一个给不可信输入的安全沙箱，**声明式那一层就是现成的沙箱**。

## 启动

```bash
pip install -e ".[mcp]"      # 或 pip install -e .   （不需要额外依赖，见下）
pixsmith-mcp                 # 或 python -m pixsmith.mcp_server
```

**没有额外依赖**：MCP 的 stdio 部分就是"换行分隔的 JSON-RPC 2.0 + 四个方法"，
本项目手写实现（约 300 行）。引一个 SDK 会破坏"只用 numpy"的承诺，也会让服务器无法离线单测。

```bash
pixsmith-mcp --selftest      # 打印协议版本、工具清单、输出目录
```

## 客户端配置

```json
{
  "mcpServers": {
    "pixsmith": {
      "command": "pixsmith-mcp",
      "env": { "PIXSMITH_MCP_OUT": "/path/to/output" }
    }
  }
}
```

配置后**不会自动生效**，需要在客户端的连接器页面里信任（Trust）这个服务器。

## 工具（3 个，刻意少而准）

| 工具 | 做什么 | 关键点 |
|---|---|---|
| `spec` | 查能力：图案 / 动词 / 参数名与默认值 / 需要哪个后端 | 用 `only` / `kind` / `category` 收窄；`include_examples` 附带**可抄改的最小场景** |
| `validate` | **只校验不渲染** | 省掉一轮「生成 → 渲染 → 看报错 → 改」；`backend="svg"` 可提前知道能不能出矢量 |
| `render` | 渲染场景并写文件 | 返回路径 + **自检报告** + **默认附一张缩小预览图** |

**为什么不是 6 个工具？** `spec` 用参数收拢了「列清单 / 看单个规格 / 看最小示例」三件事。
工具描述本身也占上下文，重叠的工具只会让 agent 选错。

## 三个 agent 友好的设计决定

### 1. `render` 默认回一张预览图 —— 给它一双眼睛

```jsonc
// 返回的 content 有两个块
[{"type": "text",  "text": "{...path, report...}"},
 {"type": "image", "data": "<base64 PNG>", "mimeType": "image/png"}]
```

agent 看不见图是最大的障碍，给它一双眼睛比给它更多数字有用。
预览会缩到 `preview_max_px`（默认 512）以内 —— 不缩的话一张 1920×1080 可能上 MB。
不想要就 `embed_preview: false`。

### 2. 工具失败用 `isError: true`，不用 JSON-RPC error

这是 MCP 里最容易搞反的一点：

| 失败类型 | 正确做法 | 为什么 |
|---|---|---|
| 场景写错、参数名拼错、后端不支持 | `result.isError = true` + 结构化错误文本 | 内容块会**原样交给模型**，它才能自己改正 |
| 方法名不存在、消息不是 JSON | JSON-RPC `error` | 这是协议/传输层问题，模型帮不上忙 |

### 3. `initialize.instructions` 里直接写操作规程

协议专门给"怎么用我"留了 `instructions` 字段。不用它，就得指望 agent 自己去翻 `AGENTS.md`。
里面放着工作循环和三条关键规程（包括"判断颜色参数生效要用 `channel_range`，
别用 `dominant_colors`"这条血泪教训）。

## 安全边界

- **只吃 JSON，不接代码** —— 没有 `eval` / `exec`，没有动态导入
- **唯一的写入面是输出目录**：输出名只取 basename，路径穿越（`../`、绝对路径、盘符）
  一次性挡掉，扩展名按后端强制纠正
- **stdout 只走协议**：工具执行期间 `sys.stdout` 被重定向到 stderr，
  免得任何一句不经意的 `print` 冲坏 JSON-RPC 流
- 输出目录用 `PIXSMITH_MCP_OUT` 指定，缺省在当前工作目录下开 `pixsmith-out/`

## 自己验证

```bash
python tools/mcp_smoke.py             # 起真实子进程走完整握手 + 三个工具
python tools/mcp_smoke.py --console   # 顺便验证装好的 pixsmith-mcp 入口
```

单元测试（`tests/test_mcp_server.py`）直接喂 JSON 给处理函数，覆盖分支；
冒烟脚本补另一面：**进程真的起得来吗、stdout 真的没被污染吗**。
两者缺一不可 —— 这次就是冒烟抓出了"少了 `__main__` 守卫导致静默退出 0"。

## 协议细节（实现备忘）

- 版本：`initialize` **回显客户端要的版本**（在支持列表内），否则回 `2025-06-18`。
  规范要求版本不匹配时**优雅降级**，而不是报错。
- stdio 是**换行分隔的 JSON**，一条一行，无内嵌换行。
  ⚠️ 不要套用 LSP 的 `Content-Length` 分帧 —— MCP 不走那一套。
- 通知（`notifications/*`）**不能有响应**，回了反而会被客户端当成对不上号的垃圾消息。
