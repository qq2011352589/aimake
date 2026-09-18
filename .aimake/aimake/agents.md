# agents.md — aimake 的知识边界
## OVERVIEW
aimake 是分层 AI 知识库生成器核心包：递归遍历目标项目、按目录镜像生成 `.aimake/agents.md` 知识树（`__init__.py:1`）。职责边界为四灵魂命令 `init / update / status / tree`（`__main__.py:1`），其余非核心命令冻结在子目录 `experimental/`；本包依赖 Python 标准库与可插拔 AI 引擎（codex exec / opencode run / openai 兼容 HTTP / mock）。

## SUB-KNOWLEDGE
- experimental：本目录是 aimake 的**冻结实验入口**（FROZEN，非演进区）：以单文件收纳非核心命令 `scan / update --feedback / ask / scaffold / maintain / ignore`，函数体全部从 `aimake/__main__.py` 逐字迁移，不新增也不删除功能；核心命令（init / update 指纹 / status / tree）不在此处、由 `aimake` 提供。运行方式 `python -m aimake.experimental <命令> [参数]`。

## DEPENDS
- 项目内：无（本目录是包根，不消费其他目录模块；设计规则引用仓库根 `AGENTS.md`——不在本目录内）。
- 项目外：Python 3 标准库（`tempfile`/`hashlib`/`json`/`concurrent.futures`/`urllib` 等，见各文件 import 区）；外部 AI CLI 由用户配置决定，非本目录承诺（见 engine.py:3 接口抽象说明）。

## FILES
- `__init__.py`：包声明与版本号（`__version__ = "0.1.0"`，第 6 行）；无其他导出。
- `__main__.py`：CLI 入口与全部核心命令编排。`main()`（638 行）建 argparse 子命令：`init`（骨架 + 需集生成，支持断点续跑/时间/节点预算，233 行 `cmd_init`）、`update`（指纹驱动重生成，366 行 `cmd_update`，指纹通道在 371 行 `_cmd_update_fingerprint`）、`status`（只读过期清单 + 反馈计数，423 行）、`tree`（知识树总览/全局索引物化，493 行）。内部流水线：`_build_node_plan`（85）、`_generate_waves`（121，按距叶子高度分层并行）、`_stale_nodes`（192）、`_affected_subgraph`（214，种子 + 祖先链 + DEPENDS 消费者）、`_refresh_meta`（223）、`_symbol_selfcheck`（579）。命令细节见 `__main__.py:638-670` 的参数定义。
- `atomic.py`：原子文本写入。`atomic_write_text(path, text, encoding="utf-8")`（10 行）：同目录 `mkstemp` → 写入 → `os.replace`，`BaseException` 时清理临时文件；供 meta/骨架/生成产物落盘使用。
- `config.py`：ignore 规则集中管理（T3）。`DEFAULT_IGNORES`（第 12 行）含 `.git/.omo/node_modules/__pycache__/dist/build/.aimake`；`load_ignore_patterns(project_root, extra=())`（27 行）合并默认 + `.aimakeignore` + 附加规则；`is_ignored(relative_posix, patterns)`（40 行）对任意深度路径段做精确名或 `fnmatch` 匹配。walk 与 openai grep 共用。
- `engine.py`：引擎抽象与配置。`EngineSpec` dataclass（19 行）含 `command/prompt_how("arg"|"stdin")/timeout/base_url/model/api_key_env/max_tokens/max_tool_rounds`；`PRESETS`（35 行）预置 `codex/opencode/mock/openai`；`resolve_engine`（44）合并优先级：预置 < 配置 overrides < `AIMAKE_OPENAI_*` 环境变量；`load_engine_config`（89）读 `.aimake/aimake.json`（含 TRAP-1 修复：配置 name 与 CLI name 不一致时丢弃 command）；`load_budget`（118）与 `write_default_config`（132）。
- `feedback.py`：事实性错误反馈格式 + 解析 + 写入。`FeedbackEntry`（17 行，source/error/evidence）与 `Feedback`（26 行）；队列目录 `knowledge_root/feedback/`（39 行）；`write_feedback`（44）生成 `<日期>-<目录>[-<报告方>].md`；`parse_feedback`（71）解析（目标目录 `"根"` 归一化为 `""`）；`list_feedback`（109）按文件名排序返回。
- `graph.py`：三类边知识图（T4）。`GraphNode`（18 行，rel/path/children/dep_candidates/is_leaf）；`KnowledgeGraph`（32 行）持 root + rel→nodes 映射，`topo_order()`（38 行）后序拓扑序；`build_graph`（55 行）从遍历结果建树边（rel 前缀匹配），空图抛 `ValueError`；`build_knowledge_graph(walk)`（87 行）内部先跑依赖候选扫描（`imports.build_dep_candidates`）。
- `imports.py`：import 静态扫描，只产**依赖候选名单**（纯目录名，不携带知识内容）。`scan_imports(file_text)`（62 行）提取并规范化 import 引用（python/js/c/rust/cs/go/java 模式，第 16-25 行）；`build_dep_candidates(files, dir_names)`（70 行）按目录聚合，token 不在项目目录名中则丢弃、排除自身目录名。
- `meta.py`：目录文件指纹（.meta，T5）。`META_NAME = ".meta"`（13 行）；`file_hash(path, length=12)`（18 行）sha256 截断；`write_meta`（30 行）行格式 `<文件名> <hash>`、失败文件记 `000000000000`；`read_meta`（47 行）回读 dict；`current_fingerprint`（62 行）文件缺失记空串占位；`is_stale`（76 行）比对当前与记录的指纹差异。
- `openai_engine.py`：纯标准库 OpenAI 兼容引擎（仅 grep 工具）。`GREP_TOOL`（27 行）工具 schema；`grep(pattern, cwd, path=".", glob=None, max_matches=200, max_bytes=20000)`（48 行）项目内递归正则搜索，含越界校验（线 59）、symlink/真实路径二次校验（线 82）、长行截断防 ReDoS（线 90）与字节上限；HTTP 重试 `_request_with_retry`（143 行）按 Retry-After / 退避处理 429/5xx；`run_openai_engine(spec, prompt, cwd)`（218 行）跑 `max_tool_rounds` 轮工具循环并返回最终文本；空内容（推理模型耗尽预算）判失败（205 行 `_final_content`）。
- `prompt.py`：提示词模板与两级内容分级（T6）。`NodeContext`（42 行）承载 rel/文件清单/注入文件内容/子级摘要/依赖候选；`SCHEMA_SECTIONS`（17 行）为十小节 + 根节点专属 `HOW TO CONSUME`；`decide_tier`（52 行）低复杂度（<10 文件且无子目录）走轻量档；`build_prompt`（75 行）与带预算降级的 `build_prompt_budgeted`（89 行，降级阶梯：丢文件内容 → 子摘要只留名字 → 文件清单截 50 → 轻量档）；`extract_overview`（63 行）供父级聚合；根节点全局增强要求注入点见 147-156 行；另有 `build_proposal_prompt`（217 行）/`build_source_prompt`（242 行）供 scaffold 用。
- `runner.py`：生成执行器（T7）。`GenResult`（19 行）；`run_engine`（29 行）分发 mock / openai / 子进程引擎（prompt 可作为末位参数或 stdin）；`run_nodes`（60 行）线程池并行（并发上限 + 超时 + 重试 + 子级失败不阻塞父级），结果按 rel 排序；`_run_with_retry`（89 行）打印进度并汇报耗时。mock 引擎：`_mock_output`（115 行）按提示词内标记确定性回显占位（源码生成块/提案/普通节点），用于无认证测试与演示。
- `skeleton.py`：知识根镜像骨架 + 镜像路径解析（T5）。`resolve_knowledge_root(cwd)`（16 行）= `cwd/.aimake`；`mirror_prefix`（21 行）target 为运行目录时前缀即知识根，否则 `knowledge_root/target.name`；`create_skeleton`（28 行）对每个可见目录建镜像目录并写不存在的 `.meta`，返回（镜像目录列表, meta 路径列表）。
- `walk.py`：可见性遍历（T3）。`WalkResult`（17 行）含 `directories/files/tree_text()`；`walk_project(root, extra_patterns=())`（36 行）`os.walk(followlinks=False)` + 原地剪枝被忽略子目录（`dirnames[:]`），目录与文件均排序，返回 ignore 规则生效后的可见目录树。
- `config.py` / `feedback.py` / `openai_engine.py` 为被多处引用的支撑模块：ignore 规则同时服务遍历与 grep 工具；feedback 文件同时服务 status、update --feedback 与符号自检。

## WHERE TO LOOK
- 查/改 CLI 命令与参数 → `__main__.py:638` `main()` 及各 `add_parser`（init 645 行起、update 656 行起、status 664 行起、tree 668 行起）；非核心命令扩展一律不进这里（见 ANTI-PATTERNS）。
- 换/配生成引擎（codex / opencode / mock / openai 兼容端点）→ `engine.py:35` `PRESETS` / `engine.py:89` `load_engine_config`；真正调用在 `runner.py:29` `run_engine`。
- 调整忽略规则 / `.aimakeignore` → `config.py:27` `load_ignore_patterns`；命令行管理见 `experimental/__main__.py:540` `cmd_ignore`。
- 理解某节点为何过期 / update 影响范围 → `meta.py:76` `is_stale` + `__main__.py:192` `_stale_nodes` + `__main__.py:214` `_affected_subgraph`。
- 想看知识树/过期/反馈总览 → `__main__.py:423` `cmd_status` / `__main__.py:493` `cmd_tree`。
- 改提示词模板/内容分级/预算降级 → `prompt.py:75` `build_prompt` / `prompt.py:89` `build_prompt_budgeted` / `prompt.py:42` `NodeContext`。
- 改 openai 引擎的 grep 工具安全性/容量 → `openai_engine.py:48` `grep` 与 `GREP_TOOL`（27 行）。

## QA
1. **aimake 生成的知识放哪？目录镜像规则是什么？** 知识根 = 运行目录 `.aimake/`；目标项目按路径镜像：目标为运行目录时直接镜像到知识根，否则前缀 `知识根/<目标名>/`。证据：`skeleton.py:16` / `skeleton.py:21`。
2. **如何接入自己的 AI 引擎？** 编辑 `.aimake/aimake.json` 的 `engine` 字段，或 `--engine` 指定预置/自定义名；预置 `codex/opencode/mock/openai` 定义在 `engine.py:35`；`command/prompt_how/timeout` 等字段合并规则见 `engine.py:44` `resolve_engine`，`AIMAKE_OPENAI_*` 环境变量优先级最高（engine.py:78-86）。
3. **一个目录节点何时算过期？** 目标目录当前可见文件指纹（文件名 + sha256 前 12 位）与镜像目录 `.meta` 不一致即过期；被删文件以空串占位参与比对。证据：`meta.py:62` `current_fingerprint` + `meta.py:76` `is_stale`；过期清单入口 `__main__.py:192`。
4. **为什么非核心命令在 `experimental/` 而不是这里？** 设计上 `__main__.py` 面只保留四灵魂命令；`scan / update --feedback / ask / scaffold / maintain / ignore` 被冻结收纳在 `aimake/experimental/__main__.py`，函数均由主实现迁移、不新增不删除。证据：本目录子目录摘要与 `experimental` 入口 docstring（`experimental/__main__.py:1-3`、619 行）。
5. **openai 引擎的 grep 工具如何保证不越界/不被符号链接骗出项目？** 请求 path 先做 `target.resolve().is_relative_to(root)` 校验（`openai_engine.py:58-60`），遍历时跳过 symlink 并对真实路径二次校验（`openai_engine.py:82-83`）；另有字节上限与长行截断防线（`openai_engine.py:94-104`）。

## KEY SYMBOLS
- `atomic_write_text` — atomic.py:10。原子写文本，产物落盘唯一可靠途径（被 meta/skeleton/__main__ 共用）。
- `walk_project` / `WalkResult` — walk.py:36 / 17。ignore 规则生效的目录遍历与结果容器。
- `build_knowledge_graph` / `topo_order` — graph.py:87 / 38。遍历结果 → 树边知识图；后序拓扑序是两阶段生成顺序依据。
- `write_meta` / `is_stale` — meta.py:30 / 76。.meta 指纹写入与过期判定。
- `load_engine_config` / `PRESETS` — engine.py:89 / 35。引擎解析与预置表。
- `build_prompt_budgeted` / `decide_tier` — prompt.py:89 / 52。带预算降级的提示词构造与内容分级。
- `run_engine` / `run_nodes` — runner.py:29 / 60。引擎调用分发与并发执行。
- `grep` / `run_openai_engine` — openai_engine.py:48 / 218。项目内只读搜索工具与 OpenAI 兼容引擎主体。
- `create_skeleton` / `resolve_knowledge_root` — skeleton.py:28 / 16。镜像骨架创建与知识根解析。
- `cmd_init` / `cmd_update` / `cmd_status` / `cmd_tree` — `__main__.py:233 / 366 / 423 / 493`。四个核心命令入口。
- `build_dep_candidates` — imports.py:70。依赖候选名单构建（纯目录名）。
- `write_feedback` / `parse_feedback` — feedback.py:44 / 71。队列文件写入与解析。

## COMMANDS
本目录无构建/测试命令（纯 Python 标准库包，目录内无测试文件）；运行方式为模块 CLI：
- `python -m aimake init [target] [--engine codex|opencode|mock|openai] [--concurrency N] [--retries N] [--budget N] [--time-budget 秒] [--max-nodes N] [--dry-run]`
- `python -m aimake update [target] [--engine E] [--concurrency N] [--retries N] [--budget N]`
- `python -m aimake status [target]`
- `python -m aimake tree [target]`
- 非核心命令走实验入口：`python -m aimake.experimental scan|ask|scaffold|maintain|ignore ...`

## ANTI-PATTERNS
- **不要往 `__main__.py` 里加非四灵魂命令**：非核心命令已冻结在 `aimake/experimental/__main__.py`（函数逐字迁移、不新增不删除），主入口新增