# aimake（AI make）

> 基于 `codex exec` / `opencode run` 的分层 AI 知识库生成器——为任意项目在知识根（运行目录 `.aimake/`）递归生成镜像式的 agents.md 分层知识树与知识链路。

**状态：全部里程碑完成（M1-M5 ✅，4 核心命令 + 冻结实验入口）**（详见 [plan.md](plan.md) / [task.md](task.md)）

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
python -m aimake.experimental ask "driver 怎么配置" project-a   # QA 问答，命中即答（带来源，冻结实验）

# 维护
aimake status project-a                            # 过期清单 / 反馈队列 / 符号自检
aimake update project-a                            # 指纹驱动重生成受影响子图
python -m aimake.experimental update --feedback project-a       # 反馈驱动处理消费侧纠错队列（冻结实验）
```

> 注意：运行目录 `.aimake/` 是知识根（在父目录运行即父级知识工作区，可共管多项目）；目标项目由参数显式指定，**绝不扫描整个运行目录**。

## 核心设计

### 知识模型

- **知识根模型**：知识根 = 运行目录的 `.aimake/`；目标项目按目录路径镜像（`.aimake/<项目名>/<目录>/agents.md`）；目标项目零 `.aimake`（可选 `.aimake-link` 指针文件）
- **三类边**：树边（目录层级，管"有什么"）、依赖边（跨目录契约，只存指针+摘要，管"需要知道什么"）、捷径边（问题→节点语义路由，管"模糊问题直达哪里"）
- **owner 语义**：每个目录的知识节点是权威管理者——知识所有权、边界守卫、委托授权；它是导航员不是围墙
- **统一 schema**：OVERVIEW / SUB-KNOWLEDGE / DEPENDS / FILES / WHERE TO LOOK / QA / KEY SYMBOLS / COMMANDS / ANTI-PATTERNS / EXTERNAL（子级可被父级机器解析聚合；内容中文、.md 后缀）
- **大项目策略**：内容分级（轻量/全量）；按需子树 `init <子路径>`；深度限制 `--depth`；超大项目符号倒排索引（ctags 式）支撑 ask 毫秒级查询

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
# 核心 4 命令
aimake init [目标] [--engine E] [--concurrency N] [--retries N] [--budget N] [--time-budget 秒] [--max-nodes N] [--dry-run]
aimake update [目标] [--engine E] [--budget N]      # 指纹驱动重生成受影响子图
aimake status [目标]                                 # 过期清单 / 反馈队列 / 符号自检
aimake tree [目标]                                   # 知识树总览（全局索引物化）
```

> `init` 可断点续跑：`--time-budget <秒>` / `--max-nodes <n>` 到点或到限即暂停（退出码 0，打印待续跑数量），再次运行会跳过已生成且未过期的节点继续；产物原子写入，`.meta` 在生成后刷新，全部完成打印「全部最新」。

实验入口（冻结，仅源码树可用，不编入 Nuitka 二进制）：

```bash
python -m aimake.experimental scan [路径] [--deps]
python -m aimake.experimental update --feedback [目标]
python -m aimake.experimental ask "问题" [目标]
python -m aimake.experimental scaffold "一句话" [--out 目录] [--default]
python -m aimake.experimental maintain [目标]
python -m aimake.experimental ignore add .omo/ [--project 项目]
```

> 实验命令处于冻结状态（保留、不删除），仅从源码树可用。

**引擎配置**（`.aimake/aimake.json`，任意 AI CLI 可接入——Makefile 里的 cc）：

```json
{ "engine": { "name": "codex", "command": ["codex", "exec", "--full-auto"], "prompt_how": "arg", "timeout": 300 },
  "concurrency": 4, "retries": 2, "budget": 20000 }
```

预置引擎：`codex` / `opencode` / `mock`（内置确定性生成器，无认证测试用）/ `openai`（纯标准库 OpenAI 兼容 HTTP 引擎，仅内置只读 `grep` 工具，无 CLI/沙箱依赖）。`--engine <自定义名>` + 配置 `command` 即可接入任意 CLI。

`openai` 引擎走 OpenAI 兼容 `/chat/completions`，唯一工具是只读 `grep`（纯 Python 正则、限定目标项目内、无 shell），只需一个 API key，适合 CI 等无 CLI/沙箱环境：

```json
{ "engine": { "name": "openai", "base_url": "https://api.deepseek.com/v1",
              "model": "deepseek-chat", "api_key_env": "AIMAKE_OPENAI_API_KEY",
              "max_tokens": 4096, "max_tool_rounds": 8 } }
```

环境变量（优先级高于配置文件，便于 CI 注入、不落盘）：`AIMAKE_OPENAI_BASE_URL` / `AIMAKE_OPENAI_MODEL` / `AIMAKE_OPENAI_API_KEY` / `AIMAKE_OPENAI_MAX_TOKENS`（推理模型需调大）（`api_key_env` 默认即指向它）。引擎解析优先级：CLI `--engine <名>` > 配置 `engine.name` > `codex`；用 `--engine <名>` 时配置字段仍合并，但 `command` 与引擎名绑定——配置名与 CLI 名不一致时丢弃 `command`，避免用 codex 的命令去跑 openai。

**codex 引擎的模型/认证/沙箱全部继承 `~/.codex/config.toml`**（aimake 只管 `command`，不碰 codex 配置）：`codex login` 认证、`model`/`model_provider` 选模型、第三方 provider 配 `base_url`、Termux 用 `sandbox_mode = "danger-full-access"`（Android 无 bubblewrap）。

### GitHub Actions 增量生成

`.github/workflows/aimake-knowledge.yml` 定时 + 手动触发增量生成：用 `openai` 引擎跑 `init`/`update`，把 `.aimake` 提交到 `aimake-knowledge` 分支（提交信息带 `[skip ci]` 防止回环触发；`.aimake` 被 gitignore，用 `git add -f` 强制加入），上传 `status` 作为 artifact，覆盖率到 100% 时打 `knowledge-vN` 标签。需配置仓库 secret `AIMAKE_OPENAI_API_KEY`，未设置时跳过并给出提示。

## 消费协议（AI 工具读取约定）

- **会话启动**：先读根 `agents.md`（方向）+ 知识根 `tasks.md`（任务上下文）
- **就地协议**：根 `agents.md` 现含 `## HOW TO CONSUME` 小节（5 步消费协议）——知识树自身教会 AI 如何消费它
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
├── aimake/           # Python 包（CLI 入口）
│   ├── __main__.py   # CLI：核心 4 命令分发（init/update/status/tree）
│   ├── config.py     # ignore 规则（默认 7 项 + .aimakeignore + fnmatch）
│   ├── walk.py       # 目录遍历（followlinks=False + 剪枝）
│   ├── imports.py    # import 静态扫描（7 语言依赖候选名单）
│   ├── graph.py      # 三类边知识图 + 后序拓扑序
│   ├── meta.py       # .meta 指纹（sha256 + is_stale 过期判定）
│   ├── skeleton.py   # 知识根镜像骨架
│   ├── prompt.py     # 提示词模板（全量/轻量 + 内容分级 + 预算降级）
│   ├── engine.py     # 引擎抽象（codex/opencode/openai/mock 预置 + aimake.json 配置）
│   ├── openai_engine.py # openai 引擎（纯标准库 /chat/completions + 只读 grep 工具）
│   ├── runner.py     # 执行器（并发/超时/重试/失败标记/mock）
│   ├── experimental/ # 冻结实验入口（scan/ask/scaffold/maintain/ignore/update --feedback）
│   └── feedback.py   # 反馈文件（格式/解析/写入/四方确认）
├── tests/            # unittest 防风暴测试（全部用例）
├── bin/              # Nuitka 编译产物（aimake 启动器 + aimake.bin）
├── main.py           # Nuitka 编译入口
├── AGENTS.md         # 项目知识库（核心设计沉淀）
├── plan.md           # 项目计划（里程碑/阶段/风险）
├── task.md           # 任务清单
└── README.md         # 本文档
```

## 测试

```bash
python3 -m unittest discover tests   # 全部用例通过：四道闸全覆盖
```

## 许可证

[MIT](LICENSE) © 2026 qq2011352589
