# python-projects

Python 机器学习 / 深度学习项目集：聚合收纳各学习项目，目录即索引。

一个仓库收纳所有小练习，每个项目一个子目录，目录即索引。
（大型项目如 rl-games 有完整 Docker 部署流程，也以子目录形式托管在这里，保持独立可运行。）

## 目录

| 子目录 | 项目 | 说明 |
|---|---|---|
| [rl-games/](./rl-games/) | RL 强化学习平台 | 黑白棋 / 贪吃蛇 DQN 训练 + Web 对战驾驶舱 |
| [pixsmith/](./pixsmith/) | 程序化图形生成器 | 用代码画背景 / 底纹 / 装饰件，输出 **PNG 或 SVG**：23 个图案 · 场景 DSL · CLI · 283 个测试 |

## 使用约定

- 每个子项目**相互独立**：各自有 `requirements.txt` / venv，互不共享依赖。
- 新增项目：拷贝进一个新子目录 → `git add . && git commit -m "add: <项目名>" && git push`。
- 大文件（模型权重、训练产物）按各项目 `.gitignore` / `.dockerignore` 规则处理。

## 快速开始（rl-games）

```bash
cd rl-games
# 本地直接跑测试
python -m pytest tests/ -q
# Docker 一键起全套（web 8001/8002 + 训练 worker）
docker compose up -d --build
```

部署细节、运维命令、常见问题见 [rl-games/OPS.md](./rl-games/OPS.md)；
架构设计与评估见 [rl-games/ARCHITECTURE_REVIEW.md](./rl-games/ARCHITECTURE_REVIEW.md)。

## 快速开始（pixsmith）

```bash
cd pixsmith
pip install -e ".[dev]"

pytest                              # 166 个用例
pixsmith list                       # 23 个图案
pixsmith gallery --out gallery      # 一次出全部图案 + HTML 画廊
pixsmith render gradient --size 1920x1080 --set end=#C8102E -o bg.png
```

用法、图案清单、性能基准与**能力边界**（它做不了什么）见 [pixsmith/README.md](./pixsmith/README.md)
与 [pixsmith/docs/能力边界.md](./pixsmith/docs/能力边界.md)。

## 环境要求

- Python 3.12+（本地运行）
- Docker + Docker Compose（容器部署）
