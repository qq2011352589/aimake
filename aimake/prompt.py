"""生成提示词模板（T6）。

统一 schema 十小节（全量档）+ SUMMARY 级（轻量档），内容一律中文。
模板可注入：目录文件清单 / 子级摘要 / 依赖候选名单（纯目录名）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


def build_prompt(ctx: NodeContext, tier: str = "") -> str:
    """构造生成提示词。tier 缺省时按内容分级自动判定。"""
    if not tier:
        tier = decide_tier(len(ctx.files), len(ctx.child_summaries))
    if tier == TIER_LIGHT:
        return _build_light(ctx)
    return _build_full(ctx)


def _build_full(ctx: NodeContext) -> str:
    child_lines = _bullet(
        [f"{name}：{summary}" for name, summary in ctx.child_summaries]
    )
    deps_lines = _bullet(ctx.dep_candidates)
    return f"""你正在为一个代码目录生成 AI 知识文档（agents.md）。这是知识导航仪不是答案本——承诺「可达」，不承诺「已知」：细节一律指向源码位置，不复制实现。

# 目标目录
{ctx.rel}

# 本目录可见文件
{_bullet(ctx.files)}

# 子目录摘要（子级 agents.md 的 OVERVIEW，供 SUB-KNOWLEDGE 引用）
{child_lines}

# 依赖候选名单（纯目录名，供确认，不是全部都要写）
{deps_lines}

# 输出要求：严格按以下 schema 生成，内容一律中文，小节标题保持英文协议键
# agents.md — {ctx.rel} 的知识边界
## OVERVIEW            ← 这个目录是干嘛的（1-2 句）
## SUB-KNOWLEDGE       ← 每个子目录一行（一句摘要 + 相对路径）
## DEPENDS             ← 依赖知识（使用方视角：「我用了 xxx 的 xxx 能力」；项目内指针 + 项目外标注）
## FILES               ← 本目录可见文件清单与职责
## WHERE TO LOOK       ← 任务→位置 路由表（3-8 条高频任务）
## QA                  ← 高频问答 3-5 条（问题 + 摘要答案 + 证据指针）
## KEY SYMBOLS         ← 核心符号（符号名 + 位置 + 一句作用）
## COMMANDS            ← 构建/测试命令
## ANTI-PATTERNS       ← 本目录特有禁忌
## EXTERNAL            ← 外部参考链接 + 知识时效性标注

规则：
1. 只写目标目录边界内的知识；子目录细节只写摘要，不展开。
2. DEPENDS 用使用方视角；候选名单用于确认，只列真实依赖。
3. 答案必须可溯源：QA / KEY SYMBOLS 都给源码路径或行号。
4. 同级目录差异化：若与前序目录职责重复，指出差异点即可。
5. 只输出 agents.md 文件内容本身，不要任何解释。"""


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
