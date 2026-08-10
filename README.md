# aimake（AI make）

> 基于 `codex exec` / `opencode run` 的分层 AI 知识库生成器——为任意项目在知识根（运行目录 `.aimake/`）递归生成镜像式的 agents.md 分层知识树与知识链路。

**状态：全部里程碑完成（M1-M5 ✅，9 命令已实现）**（详见 [plan.md](plan.md) / [task.md](task.md)）

## 它解决什么问题

AI 每次进入一个项目，都要重新读代码、重新理解结构。aimake 一次性为项目生成一棵**分层知识树**：

- 知识根 `.aimake/` 按目录结构**镜像**知识树——每个目录一个知识节点（agents.md），回答「这个目录里有什么、去哪找答案」；目标项目**零侵入**（不在项目里放任何 .aimake）
- 知识边界严格：父级只看子级摘要，细节按需下钻——**上下文严格线性，不随项目规模爆炸**
- 产物是**导航图**不是答案本：承诺「可达」，不承诺「已知」——链路末端永远指向真实源码

## 快速开始

```bash
# 安装（Python 3 标准库，零第三方依赖）
pip install nuitka                                  # 仅编译需要

# 在父目录初始化（知识根 = 当前目录 .aimake/，目标 = project-a）
aimake init project-a                              # 全树生成（自底向上，分层并行）

# 消费（初始化后一切照旧，AI 工具读知识树）
aimake tree project-a                              # 知识树总览（全局索引）
aimake ask "driver 怎么配置" project-a              # QA 问答，命中即答（带来源）

# 维护
aimake status project-a                            # 过期清单 / 反馈队列 / 符号自检
aimake update project-a                            # 指纹驱动重生成受影响子图
aimake update --feedback project-a                 # 反馈驱动处理消费侧纠错队列
```

> 注意：运行目录 `.aimake/` 是知识根（在父目录运行即父级知识工作区，可共管多项目）；目标项目由参数显式指定，**绝不扫描整个运行目录**。

## 核心设计

### 知识模型

- **知识根模型**：知识根 = 运行目录的 `.aimake/`；目标项目按目录路径镜像（`.aimake/<项目名>/<目录>/agents.md`）；目标项目零 `.aimake`（可选 `.aimake-link` 指针文件）
- **三类边**：树边（目录层级，管"有什么"）、依赖边（跨目录契约，只存指针+摘要，管"需要知道什么"）、捷径边（问题→节点语义路由，管"模糊问题直达哪里"）
- **owner 语义**：每个目录的知识节点是权威管理者——知识所有权、边界守卫、委托授权；它是导航员不是围墙
- **统一 schema**：OVERVIEW / SUB-KNOWLEDGE / DEPENDS / FILES / WHERE TO LOOK / QA / KEY SYMBOLS / COMMANDS / ANTI-PATTERNS / EXTERNAL（子级可被父级机器解析聚合；内容中文、.md 后缀）

### 更新机制（三通道，全部显式触发）

| 通道 | 触发 | 手段 |
|------|------|------|
| ① 指纹更新 | 文件变了 | `.meta` 指纹对比，只重生成受影响子图（本目录 + 祖先链 + DEPENDS 消费者） |
| ② 反馈更新 | 知识错了 | 事实性错误报告 → 四方确认（≥2 票/任一事实错误/自检失败）→ 父目录仲裁 → 注入重生成 |
| ③ 符号自检 | 零 token 免费跑 | KEY SYMBOLS / QA 证据指针 vs 源码比对，失效即过期（status 自动带出） |

### 防风暴四道闸

1. `.aimake` 双向排除（被写入永不算输入变化）
2. symlink 防环（followlinks=False，不跟随环）
3. 指纹幂等（跑两次 = 跑一次；仅 mtime 变化不触发）
4. 依赖图 + 拓扑排序（分层波浪，子级失败不阻塞父级；两阶段收敛）

## CLI 用法（已实现）

```bash
aimake scan [路径] [--deps]                    # 扫描可见目录树（ignore 规则生效）
aimake init [目标] [--engine E] [--concurrency N] [--retries N] [--budget N] [--dry-run]
                                               # 全树生成：骨架+指纹+分层波浪+两阶段
aimake update [目标] [--engine E] [--budget N]  # 指纹驱动重生成受影响子图
aimake update --feedback [目标] [--engine E]    # 反馈驱动：四方确认→注入重生成→连锁
aimake status [目标]                            # 过期清单 / 反馈队列详情 / 符号自检
aimake tree [目标]                              # 知识树总览（全局索引物化 + 捷径表）
aimake ask "问题" [目标]                         # QA 命中即答（带来源）/ 捷径导航 / 系统性否定
aimake scaffold "一句话" [--out 目录] [--default]  # 从描述生成项目：提案→确认→源码→骨架→自动 init
```

**引擎配置**（`.aimake/aimake.json`，任意 AI CLI 可接入——Makefile 里的 cc）：

```json
{ "engine": { "name": "codex", "command": ["codex", "exec", "--full-auto"], "prompt_how": "arg", "timeout": 300 },
  "concurrency": 4, "retries": 2, "budget": 20000 }
```

预置引擎：`codex` / `opencode` / `mock`（内置确定性生成器，无认证测试用）。`--engine <自定义名>` + 配置 `command` 即可接入任意 CLI。

## 消费协议（AI 工具读取约定）

- **会话启动**：先读根 `agents.md`（方向）+ 知识根 `tasks.md`（任务上下文）
- **知识发现**：项目根有 `.aimake-link` 按指针去知识根；否则按约定"项目知识在父目录 `.aimake/<项目名>/`"
- **消费前**：`aimake status` 核对指纹——过期先 `aimake update`
- **消费中**：查询经由 owner（读 agents.md，不直接扫目录）；下钻/依赖边/捷径表跳转；换"读"不换会话
- **消费后**：发现知识错误 → 写事实性反馈到知识根 `feedback/`（格式：来源/错误/证据）；任务完成 → 更新 `tasks.md`

## 技术栈

- **Python 3** ＋ 标准库（零第三方依赖；测试用 unittest）
- **Nuitka** 编译为独立可执行文件（支持 Termux，产物 `bin/aimake`）
- **生成引擎**：`codex exec`（备选 `opencode run`）——Makefile 里的 cc，可插拔可替换

## 目录结构

```
aimake/
├── aimake/           # Python 包（CLI 入口 + 11 个模块）
│   ├── __main__.py   # CLI：scan/init/update/status/tree/ask 已实现
│   ├── config.py     # ignore 规则（默认 6 项 + .aimakeignore + fnmatch）
│   ├── walk.py       # 目录遍历（followlinks=False + 剪枝）
│   ├── imports.py    # import 静态扫描（7 语言依赖候选名单）
│   ├── graph.py      # 三类边知识图 + 后序拓扑序
│   ├── meta.py       # .meta 指纹（sha256 + is_stale 过期判定）
│   ├── skeleton.py   # 知识根镜像骨架
│   ├── prompt.py     # 提示词模板（全量/轻量 + 内容分级 + 预算降级）
│   ├── engine.py     # 引擎抽象（codex/opencode 预置 + aimake.json 配置）
│   ├── runner.py     # 执行器（并发/超时/重试/失败标记/mock）
│   └── feedback.py   # 反馈文件（格式/解析/写入/四方确认）
├── tests/            # unittest 防风暴测试（12 用例）
├── bin/              # Nuitka 编译产物（aimake 启动器 + aimake.bin）
├── main.py           # Nuitka 编译入口
├── AGENTS.md         # 项目知识库（核心设计沉淀）
├── plan.md           # 项目计划（里程碑/阶段/风险）
├── task.md           # 任务清单
└── README.md         # 本文档
```

## 测试

```bash
python3 -m unittest discover tests   # 12 用例：四道闸全覆盖
```

## 许可证

[MIT](LICENSE) © 2026 qq2011352589
