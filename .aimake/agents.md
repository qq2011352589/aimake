# agents.md — . 的知识边界

## OVERVIEW
本目录是 **aimake 自身仓库**：aimake 是一个基于 `codex exec` / `opencode run` 的分层 AI 知识库生成器，为任意项目递归生成 `.aimake/agents.md` 知识树。它承诺「可达」而非「已知」——知识树是导航仪，链路末端永远指向真实源码。本仓库包含核心 Python 包 `aimake/`、stdlib-only 测试套件 `tests/`、真实项目验证记录 `validation/`、CI/发布工作流 `.github/workflows/`、Termux 启动器 `bin/`，以及自举知识根 `.aimake/`。边界：不拦截对话、不联网查证项目外知识、不做 GUI/IDE 插件。

## HOW TO CONSUME
1. 会话启动：先读根 agents.md（方向）+ 知识根 tasks.md（任务上下文）
2. 知识发现：项目根有 .aimake-link 按指针去知识根；否则按约定「项目知识在父目录 .aimake/<项目名>/」
3. 消费前：运行 aimake status 核对指纹——过期先 aimake update
4. 消费中：查询经由 owner（读 agents.md，不直接扫目录）；沿树边/依赖边/捷径表跳转；换「读」不换会话
5. 消费后：发现知识错误写事实性反馈到知识根 feedback/；任务完成更新 tasks.md

## SUB-KNOWLEDGE
- `aimake/` — 核心 Python 包：CLI 分发（init/update/status/tree）、目录遍历、ignore、指纹、提示词模板、引擎抽象、并发执行器、反馈解析；实验子命令（ask/scaffold/maintain/ignore/update --feedback）冻结在 `aimake/experimental/`（不进 Nuitka 产物）。细节见 `AGENTS.md` CODE MAP。
- `tests/` — 零第三方依赖 unittest 套件：CLI 表面契约 → 五大防护闸（双向排除/symlink 防环/指纹幂等/超时降级 + TRAP-1/2）→ 引擎与 runner 行为（工具循环/重试/grep 安全）→ CI 工作流结构契约；全在临时目录 + mock 上运行，不触真实网络。
- `validation/` — 在真实项目 `wap` 上的盲测评测场所：记录可达性/精度指标与缺陷（可达性 100%、精确导航 50%、符号自检误报缺陷 F3），是回答「aimake 承诺是否成立、瓶颈与缺陷在哪」的权威入口。
- `bin/` — 仅含 Termux 启动器 `bin/aimake`：为 bionic 链接器预置 `LD_LIBRARY_PATH` 后 exec 同目录 `aimake.bin`；不包含业务代码。
- `.github/workflows/` — GitHub 协作自动化宿主：`aimake-knowledge.yml` 定时/手动增量生成知识树并推送到独立分支；`release.yml` 构建 linux/darwin/windows + Termux 容器交叉编译资产并发布 Release。
- `.aimake/` — aimake 自举知识根（生成产物，git 忽略）；被 `walk_project` 双向排除，不参与自身扫描。

## DEPENDS
- `aimake/__main__.py` 依赖包内各模块：`walk`/`graph`/`meta`/`prompt`/`runner`/`engine`/`feedback`/`atomic`（同包内指针，见 `AGENTS.md` CODE MAP）。
- 生成引擎依赖外部命令 `codex exec` 或 `opencode run`（可替换；抽象与预置见 `aimake/engine.py:44` `resolve_engine`），mock 引擎为测试/无网兜底（`aimake/runner.py:115`）。
- 构建期依赖 Nuitka（仅 `main.py` 编译入口使用，不进入运行时）；Termux 产物还需 bionic libpython（见 `install.sh` 与 `bin/aimake`）。
- `install.sh` 依赖 GitHub Releases/API 资产命名约定，该命名由 `.github/workflows/release.yml` 产出方保证。
- 运行时零第三方 Python 依赖（纯标准库，`tests/__init__.py` 亦强制此约定）。

## FILES
- `AGENTS.md` — 本项目自身的知识文档与设计规范：OVERVEW/核心设计/统一 schema/STRUCTURE/CODE MAP/CONVENTIONS/COMMANDS/NOTES；是理解 aimake 设计意图与维护约定的第一入口。
- `README.md` — 面向用户的说明：解决的问题、快速开始、核心设计、CLI 用法、消费协议、技术栈、目录结构、测试与许可证。
- `plan.md` — 项目计划：目标/范围/里程碑（M1–M5 全 ✅ 完成）/实施阶段/风险对策；是「为什么这么设计」的历史依据。
- `task.md` — 任务清单：M0–M5 全部置 ✅；含状态图例与已完成记录，是任务上下文的权威来源。
- `main.py` — Nuitka 独立可执行入口（onefile 编译用）：仅 `import sys` + 转调 `aimake.__main__.main` 并以返回值作为进程退出码。关键接口：`main()`。
- `install.sh` — 一键安装脚本：`uname` 检测 OS/架构 → Termux 特判（`$PREFIX/bin` + bionic 专用资产）→ GitHub Release 双路径下载（直连 302 失败则走 API 按 asset_id 取）+ `curl -C -` 断点续传 → 安装到 `$AIMAKE_INSTALL_DIR` 或 `~/.local/bin` → Termux 额外生成带 `LD_LIBRARY_PATH` 的启动器。关键接口：`dl()` 下载函数、`ASSET` 资产命名映射。
- `.aimakeignore` — aimake 自举时的自定义忽略：排除 `.omo/`（opencode 内部会话目录）。
- `.gitignore` — git 忽略清单：编辑器/工具、Python 缓存、构建产物、`.aimake/` 知识生成产物、Nuitka 中间产物与 `bin/aimake.bin`。
- `LICENSE` — MIT License（Copyright © 2026 qq2011352589）。

## WHERE TO LOOK
- 「aimake 承诺什么 / 边界在哪 / 设计取舍」→ `AGENTS.md` 核心设计与 `validation/REPORT.md` 结论
- 「加/改 CLI 命令」→ 核心四命令：`aimake/__main__.py:638` `main()`（子命令注册处）；实验命令：`aimake/experimental/__main__.py:616` `main()`（入口冻结，不留核心）
- 「目录被错误排除/没扫到」→ `aimake/walk.py:36` `walk_project()` + `aimake/config.py:27` `load_ignore_patterns()`
- 「指纹不过期/误报过期」→ `aimake/meta.py:76` `is_stale()`（哈希内容比对，非 mtime）
- 「改 agents.md schema / 内容分级 / 预算」→ `aimake/prompt.py:89` `build_prompt_budgeted()`、`:52` `decide_tier()`
- 「换生成引擎（codex/opencode/openai/mock）/ 调模型参数」→ `aimake/engine.py:44` `resolve_engine()` + 配置加载 `load_engine_config()`
- 「openai 直连引擎的工具循环 / grep 安全」→ `aimake/openai_engine.py:218` `run_openai_engine()`
- 「并发/超时/重试/失败降级」→ `aimake/runner.py:60` `run_nodes()`
- 「反馈怎么写 / 四方确认怎么判」→ `aimake/feedback.py:44` `write_feedback()` + `aimake/experimental/__main__.py:237` `cmd_update_feedback()`
- 「CI 增量生成 / Release 发布的编排」→ `.github/workflows/aimake-knowledge.yml`、`.github/workflows/release.yml`
- 「知识树生成算法（波浪并行/受影响子图）」→ `aimake/__main__.py:121` `_generate_waves()`、`:214` `_affected_subgraph()`
- 「Nuitka 编译 / Termux 运行环境」→ `main.py` 顶部用法 docstring + `.github/workflows/release.yml` + `bin/aimake`
- 「测试怎么写 / 跑哪些」→ `tests/`（模块名即主题：test_exclusion/test_fingerprint/test_timeout/test_resume_init/test_openai_engine…）
- 「已知缺陷与复现步骤」→ `validation/REPORT.md`（F2 轻量档精度瓶颈、F3 符号自检误报、F4 跨目录契约泛化）

## QA
- Q：aimake 是「答案本」吗？
  A：不是——定位是「知识导航仪」，只承诺可达（每个问题都能路由到正确源码文件），不承诺已知（不保证树内直接给精确答案）。证据：`AGENTS.md` 核心设计 + `validation/REPORT.md