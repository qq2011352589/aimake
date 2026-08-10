"""生成提示词模板（T6）。

统一 schema 十小节（全量档）+ SUMMARY 级（轻量档），内容一律中文。
模板可注入：目录文件清单 / 子级摘要 / 依赖候选名单（纯目录名）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# 内容分级阈值：低复杂度目录（<10 文件且无子目录）→ 轻量档
LIGHT_TIER_MAX_FILES = 10

TIER_LIGHT = "light"
TIER_FULL = "full"

SCHEMA_SECTIONS: tuple[str, ...] = (
    "OVERVIEW", "SUB-KNOWLEDGE", "DEPENDS", "FILES", "WHERE TO LOOK",
    "QA", "KEY SYMBOLS", "COMMANDS", "ANTI-PATTERNS", "EXTERNAL",
)


@dataclass
class NodeContext:
    """单节点生成上下文（供模板注入）。"""

    rel: str  # 相对知识根的路径（"" 为根）
    files: list[str] = field(default_factory=list)
    file_contents: list[tuple[str, str]] = field(default_factory=list)  # (文件名, 内容截断)
    child_summaries: list[tuple[str, str]] = field(default_factory=list)  # (子目录名, 一句话)
    dep_candidates: list[str] = field(default_factory=list)  # 纯目录名


def decide_tier(file_count: int, child_count: int) -> str:
    """内容分级：低复杂度（<10 文件且无子目录）→ 轻量档，否则全量档。"""
    if file_count < LIGHT_TIER_MAX_FILES and child_count == 0:
        return TIER_LIGHT
    return TIER_FULL


def _bullet(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- （无）"


def extract_overview(agents_md_text: str) -> str:
    """从 agents.md 提取 OVERVIEW 一句话摘要（父级聚合用）。"""
    section = False
    for line in agents_md_text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip().upper() == "OVERVIEW"
            continue
        if section and line.strip():
            return line.strip()
    return ""


def build_prompt(ctx: NodeContext, tier: str = "", is_root: bool = False) -> str:
    """构造生成提示词。tier 缺省时按内容分级自动判定；is_root 加全局增强要求。"""
    if not tier:
        tier = decide_tier(len(ctx.files), len(ctx.child_summaries))
    if tier == TIER_LIGHT:
        return _build_light(ctx)
    return _build_full(ctx, is_root=is_root)


def estimate_chars(text: str) -> int:
    """提示词大小估算（字符数，确定性——预算单位）。"""
    return len(text)


def build_prompt_budgeted(
    ctx: NodeContext,
    tier: str,
    is_root: bool,
    budget: int | None,
) -> tuple[str, bool]:
    """带预算的提示词构造：超预算按策略降级。

    降级阶梯：① 子级摘要只留名字 → ② 文件清单截断 → ③ 降为轻量档。
    返回 (prompt, 是否降级)。budget ≤ 0 表示不限制。
    """
    if budget is None or budget <= 0:
        return build_prompt(ctx, tier, is_root), False

    prompt = build_prompt(ctx, tier, is_root)
    if estimate_chars(prompt) <= budget:
        return prompt, False

    # ① 丢弃文件内容（保留文件名清单）——内容注入是理解深度的增益，超预算先牺牲
    ctx0 = replace(ctx, file_contents=[])
    p0 = build_prompt(ctx0, tier, is_root)
    if estimate_chars(p0) <= budget:
        return p0, True

    # ② 子级摘要只留名字（保留依赖候选）
    ctx1 = replace(
        ctx0, child_summaries=[(name, "") for name, _ in ctx0.child_summaries]
    )
    p1 = build_prompt(ctx1, tier, is_root)
    if estimate_chars(p1) <= budget:
        return p1, True

    # ③ 文件清单截断（保留前 50）
    max_files = 50
    if len(ctx1.files) > max_files:
        ctx2 = replace(ctx1, files=ctx1.files[:max_files])
        p2 = build_prompt(ctx2, tier, is_root)
        if estimate_chars(p2) <= budget:
            return p2, True

    # ④ 降为轻量档（SUMMARY 级，文件清单也截断）
    ctx3 = replace(ctx1, files=ctx1.files[:max_files])
    p3 = _build_light(ctx3)
    return p3, True


def _build_full(ctx: NodeContext, is_root: bool = False) -> str:
    child_lines = _bullet(
        [f"{name}：{summary}" for name, summary in ctx.child_summaries]
    )
    deps_lines = _bullet(ctx.dep_candidates)
    content_lines = "\n".join(
        f"### {name}\n{body}" for name, body in ctx.file_contents
    )
    content_block = (
        f"\n# 本目录文件内容（供深入理解——必须基于真实代码撰写，禁止臆测）\n{content_lines}\n"
        if ctx.file_contents else ""
    )
    root_extra = ""
    if is_root:
        root_extra = """
# 全局增强要求（根节点特有）：
- 将 WHERE TO LOOK 升级为【全局捷径表】：5-15 条「问题模式 → 目标节点」语义路由（如「性能问题 → 相关目录」「配置格式 → config/」「API 差异 → 项目外 EXTERNAL」），供模糊问题一跳直达。
- 捕获【跨目录契约】：全局横切知识（全局配置、认证、数据流协议、跨模块调用链如 api/caller/hacker 三层）——不依赖任何单目录的 import。
- SUB-KNOWLEDGE 对子目录给出差异化一句话摘要；职责重复的指出差异点。
"""
    return f"""你正在为一个代码目录生成 AI 知识文档（agents.md）。这是知识导航仪不是答案本——承诺「可达」，不承诺「已知」：细节一律指向源码位置，不复制实现。

# 目标目录
{ctx.rel}

# 本目录可见文件
{_bullet(ctx.files)}
{content_block}
# 子目录摘要（子级 agents.md 的 OVERVIEW，供 SUB-KNOWLEDGE 引用）
{child_lines}

# 依赖候选名单（纯目录名，供确认，不是全部都要写）
{deps_lines}

# 输出要求：严格按以下 schema 生成，内容一律中文，小节标题保持英文协议键
# agents.md — {ctx.rel} 的知识边界
## OVERVIEW            ← 职责 + 边界 + 与谁协作（1-3 句，不是只写"是什么"）
## SUB-KNOWLEDGE       ← 每个子目录一行（一句摘要 + 相对路径；同级差异化）
## DEPENDS             ← 依赖知识（使用方视角：「我用了 xxx 的 xxx 能力」；项目内指针 + 项目外标注）
## FILES               ← 每个文件：职责 + 关键接口/导出（基于注入的文件内容，不要只列名字）
## WHERE TO LOOK       ← 任务→位置 路由表（3-8 条高频任务：增删改查/配置/调试/构建）
## QA                  ← 高频问答 3-5 条（问题 + 摘要答案 + 证据指针）
## KEY SYMBOLS         ← 核心导出 + 被引用最多的符号（符号名 + 位置 + 一句作用；不是罗列全部）
## COMMANDS            ← 构建/测试命令
## ANTI-PATTERNS       ← 本目录特有禁忌
## EXTERNAL            ← 外部参考链接 + 知识时效性标注
{root_extra}
规则：
1. 只写目标目录边界内的知识；子目录细节只写摘要，不展开。
2. DEPENDS 用使用方视角；候选名单用于确认，只列真实依赖。
3. 答案必须可溯源：QA / KEY SYMBOLS 都给源码路径或行号。
4. 同级目录差异化：若与前序目录职责重复，指出差异点即可。
5. **先通读注入的文件内容再写**——OVERVIEW/FILES/KEY SYMBOLS 必须基于真实代码，禁止仅凭文件名臆测。
6. 只输出 agents.md 文件内容本身，不要任何解释。"""


def _build_light(ctx: NodeContext) -> str:
    return f"""你正在为一个代码目录生成轻量 AI 知识文档（agents.md）。只需要 SUMMARY 级内容。

# 目标目录
{ctx.rel}

# 本目录可见文件
{_bullet(ctx.files)}

# 输出（中文，SUMMARY 级；小节标题保持英文协议键）
# agents.md — {ctx.rel} 的知识边界
## OVERVIEW    ← 这个目录是干嘛的（1-2 句）
## FILES       ← 每文件一句话职责

规则：内容中文；只输出 agents.md 文件内容本身，不要任何解释。"""


def build_proposal_prompt(description: str) -> str:
    """scaffold 提案提示词：一句话 → 结构化项目提案（T26）。

    提案 = 目录结构 + 技术栈 + 功能清单 + 里程碑，供用户确认后生成源码。
    """
    return f"""你是项目架构师。根据用户的一句话需求，产出一份**项目提案**（不写代码）。

# 用户需求
{description}

# 输出要求（中文，Markdown）：
# 项目提案 — <项目名>
## 一句话定位      ← 1 句
## 技术栈          ← 语言/框架/依赖（可替换，标注理由）
## 目录结构        ← 缩进列表（每行一个目录，缩进=层级，目录名英文，禁止树形符号 ──）
## 功能清单        ← 3-8 个核心功能（每个一句）
## 里程碑          ← 3 个阶段（每阶段：目标 + 交付物）
## 风险            ← 2-3 条（影响 + 对策）

规则：
1. 目录结构是生成代码的依据——目录名用英文，用途用中文注释。
2. 若需求模糊，取合理默认并标注「（假设）」。
3. 只输出提案 Markdown 本身，不要解释。"""


def build_source_prompt(rel_dir: str, proposal: str) -> str:
    """scaffold 源码生成提示词：按提案生成 <rel_dir> 目录的文件清单（T28）。

    输出格式：每文件一个 fenced 块，块首行 = 相对 <rel_dir> 的文件名。
    """
    return f"""# 源码生成任务
根据项目提案，生成目录 <{rel_dir}> 的源码文件。

# 项目提案
{proposal[:2000]}

# 输出要求（清单格式，直接输出文件块序列，不要解释）：
- 每个文件一个 fenced 代码块，代码块首行 = 相对 <{rel_dir}> 的文件名：
```main.py
文件内容
```
- 只生成属于 <{rel_dir}> 的文件；子目录文件由各自的生成任务负责。"""
