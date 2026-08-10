# aimake（AI make）

> 基于 `codex exec` / `opencode run` 的分层 AI 知识库生成器——为任意项目在知识根（运行目录 `.aimake/`）递归生成镜像式的 agents.md 分层知识树与知识链路。

**状态：M1 实施中（`scan` 已可用）**（详见 [plan.md](plan.md) / [task.md](task.md)）

## 它解决什么问题

AI 每次进入一个项目，都要重新读代码、重新理解结构。aimake 一次性为项目生成一棵**分层知识树**：

- 知识根 `.aimake/` 按目录结构**镜像**知识树——每个目录一个知识节点（agents.md），回答「这个目录里有什么、去哪找答案」；目标项目**零侵入**（不在项目里放任何 .aimake）
- 知识边界严格：父级只看子级摘要，细节按需下钻——**上下文严格线性，不随项目规模爆炸**
- 产物是**导航图**不是答案本：承诺「可达」，不承诺「已知」——链路末端永远指向真实源码

## 核心设计

### 知识模型

- **知识根模型**：知识根 = 运行目录的 `.aimake/`（在父目录运行即父级知识工作区）；目标项目按目录路径镜像（`.aimake/<项目名>/<目录>/agents.md`）；目标项目零 `.aimake`（可选 `.aimake-link` 指针文件）
- **三类边**：树边（目录层级，管"有什么"）、依赖边（跨目录契约，只存指针+摘要，管"需要知道什么"）、捷径边（问题→节点语义路由，管"模糊问题直达哪里"）
- **owner 语义**：每个目录的知识节点是权威管理者——知识所有权、边界守卫、委托授权；它是导航员不是围墙
- **统一 schema**：OVERVIEW / SUB-KNOWLEDGE / DEPENDS / FILES / WHERE TO LOOK / QA / KEY SYMBOLS / COMMANDS / ANTI-PATTERNS / EXTERNAL（子级可被父级机器解析聚合）

### 更新机制（三通道，全部显式触发）

| 通道 | 触发 | 手段 |
|------|------|------|
| ① 指纹更新 | 文件变了 | `.meta` 指纹对比，只重生成受影响子图（本目录 + 祖先链 + 依赖消费者） |
| ② 反馈更新 | 知识错了 | 事实性错误报告 → 四方确认 → 达到阈值 → 父目录决策 + 重生成 |
| ③ 符号自检 | 零 token 免费跑 | KEY SYMBOLS / QA 证据指针 vs 源码 grep 比对，失效即过期 |

### 防风暴四道闸

1. `.aimake` 双向排除（被写入永不算输入变化）
2. symlink 防环（realpath 访问集合）
3. 指纹幂等（跑两次 = 跑一次）
4. 依赖图 + 拓扑排序（父级等子级，子级失败不阻塞父级）

## CLI 预览

```bash
python -m aimake scan [路径]       # 扫描可见目录树（ignore 规则生效）
python -m aimake init [目标]       # 知识根生成目标项目镜像知识树（自底向上）
python -m aimake update [路径]      # 指纹驱动重生成受影响目录链
python -m aimake update --feedback # 反馈驱动处理消费侧纠错队列
python -m aimake status            # 过期清单 / 待处理反馈 / 符号自检
python -m aimake tree              # 知识树总览（全局索引物化）
python -m aimake ask "问题"         # QA 问答，命中即答（答案带来源标注）
python -m aimake scaffold "一句话"  # 从描述生成项目骨架 + 自动 init
```

## 技术栈

- **Python 3** ＋ 标准库（零第三方依赖）
- **Nuitka** 编译为独立可执行文件（支持 Termux）
- **生成引擎**：`codex exec`（备选 `opencode run`）——Makefile 里的 cc，可插拔可替换

## 目录结构

```
aimake/
├── aimake/     # Python 包（CLI 入口：__main__ / config / walk）
├── AGENTS.md   # 项目知识库（核心设计沉淀）
├── plan.md     # 项目计划（里程碑/阶段/风险）
├── task.md     # 任务清单
└── README.md   # 本文档
```

## 许可证

[MIT](LICENSE) © 2026 qq2011352589
