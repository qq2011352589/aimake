"""aimake CLI 入口（T12：scan / init / update 可验收，其余规划中）。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import DEFAULT_IGNORES, IGNORE_FILE, load_ignore_patterns
from .engine import load_budget, load_engine_config, write_default_config
from .feedback import list_feedback
from .graph import build_knowledge_graph
from .meta import is_stale, write_meta
from .prompt import TIER_LIGHT, NodeContext, build_prompt, build_prompt_budgeted, build_proposal_prompt, build_source_prompt, decide_tier, extract_overview
from .runner import GenResult, run_engine, run_nodes
from .skeleton import create_skeleton, mirror_prefix, resolve_knowledge_root
from .walk import walk_project


def cmd_scan(args: argparse.Namespace) -> int:
    """扫描可见目录树；--deps 时输出依赖候选名单与生成拓扑序。"""
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"错误：不是目录：{root}", file=sys.stderr)
        return 1
    result = walk_project(root)
    print(result.tree_text())
    if args.deps:
        graph = build_knowledge_graph(result)
        print("\n== 依赖候选名单（纯目录名）==")
        for node in graph.topo_order():
            label = node.rel or "."
            print(f"{label}: {', '.join(node.dep_candidates) or '-'}")
        print("\n== 生成拓扑序（子先父后）==")
        print(" -> ".join(n.rel or "." for n in graph.topo_order()))
    return 0


def _compute_heights(topo_order: list) -> dict[str, int]:
    """全量计算"距叶子高度"（后序：子级高度已算好）。"""
    height: dict[str, int] = {}
    for node in topo_order:
        if not node.children:
            height[node.rel] = 0
        else:
            height[node.rel] = max(height[c.rel] + 1 for c in node.children)
    return height


def _collect_waves(topo_order: list, height: dict[str, int]) -> list[list]:
    """按"距叶子高度"分组波浪：叶子（0）→ 根；同层节点互相独立可并行。

    高度表须预先全量计算（子集调用时不会引用缺失的兄弟节点）。
    """
    waves: dict[int, list] = {}
    for node in topo_order:
        waves.setdefault(height[node.rel], []).append(node)
    return [waves[h] for h in sorted(waves)]  # 叶子高度 0 先生成


def _collect_child_summaries(node, prefix: Path) -> list[tuple[str, str]]:
    """父级聚合：读子级已生成的 agents.md 提取 OVERVIEW 一句话。"""
    summaries: list[tuple[str, str]] = []
    for child in node.children:
        md = prefix / child.rel / "agents.md"
        if md.is_file():
            ov = extract_overview(md.read_text(encoding="utf-8"))
            summaries.append((child.path.name, ov or "（无摘要）"))
        else:
            summaries.append((child.path.name, "（未生成）"))
    return summaries


# 内容注入：预算内优先核心文件（按大小升序），保证 codex 基于真实代码撰写
_CONTENT_BUDGET_RATIO = 0.5  # 文件内容占预算比例上限
_PER_FILE_MAX_CHARS = 4000   # 单文件注入截断
_SKIP_FILE_BYTES = 200_000   # 跳过超大文件


def _load_file_contents(node_path: Path, files: list[str], budget: int | None) -> list[tuple[str, str]]:
    """预算内注入文件内容：按大小升序优先（README/入口/小文件），累计 ≤ 预算一半。"""
    max_chars = int(budget * _CONTENT_BUDGET_RATIO) if budget and budget > 0 else 8000
    entries: list[tuple[str, str]] = []
    total = 0
    for fname in sorted(files, key=lambda f: (node_path / f).stat().st_size):
        p = node_path / fname
        try:
            if p.stat().st_size > _SKIP_FILE_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if len(text) > _PER_FILE_MAX_CHARS:
            text = text[:_PER_FILE_MAX_CHARS] + "\n…（截断）"
        if total + len(text) > max_chars:
            break  # 小文件优先，超出预算停止
        entries.append((fname, text))
        total += len(text)
    return entries


def _build_node_plan(
    graph, result, prefix: Path, budget: int | None = None,
) -> tuple[dict, int]:
    """构造全部节点计划：rel → (prompt, 源目录, 镜像目录)。

    budget（字符数）>0 时启用上下文预算：超预算节点按策略降级。
    返回 (node_plan, 降级节点数)。
    """
    node_plan: dict[str, tuple[str, Path, Path]] = {}
    degraded = 0
    for node in graph.topo_order():
        mirror = prefix / node.rel if node.rel else prefix
        files = result.files.get(node.path, [])
        child_summaries = _collect_child_summaries(node, prefix)
        tier = decide_tier(len(files), len(node.children))
        file_contents = (
            _load_file_contents(node.path, files, budget)
            if tier == TIER_FULL else []
        )
        ctx = NodeContext(
            rel=node.rel or ".",
            files=files,
            file_contents=file_contents,
            child_summaries=child_summaries,
            dep_candidates=node.dep_candidates,
        )
        # T9：根节点（rel=""）加全局增强要求
        prompt, was_degraded = build_prompt_budgeted(
            ctx, tier, is_root=node.rel == "", budget=budget
        )
        if was_degraded:
            degraded += 1
        node_plan[node.rel] = (prompt, node.path, mirror)
    return node_plan, degraded


def _generate_waves(waves: list, node_plan: dict, engine, args) -> tuple[list, list]:
    """执行波浪生成并写产物。返回 (成功列表, 失败列表)。"""
    ok: list = []
    failed: list = []
    total_waves = len(waves)
    for wi, wave in enumerate(waves, 1):
        print(f"  层 {wi}/{total_waves}：{len(wave)} 个节点并行…", flush=True)
        plan = [(n.rel, node_plan[n.rel][0], node_plan[n.rel][1]) for n in wave]
        gen = run_nodes(
            [(rel, p, c) for rel, p, c in plan],
            engine,
            concurrency=args.concurrency,
            retries=args.retries,
        )
        for r in gen:
            if r.ok:
                (node_plan[r.rel][2] / "agents.md").write_text(
                    r.output, encoding="utf-8"
                )
                ok.append(r)
            else:
                failed.append(r)
        print(f"  层 {wi}: 成功 {sum(1 for r in gen if r.ok)}/{len(gen)}")
    return ok, failed


def _ancestors(rel: str) -> list[str]:
    """沿树边向上的祖先链（含根 ""）。"""
    chain: list[str] = []
    while rel:
        rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
        chain.append(rel)
    return chain


def _depends_consumers(graph, rel: str) -> set[str]:
    """DEPENDS 消费者：依赖候选名单含过期目录的节点（反向索引，确定性）。

    直接读图的 dep_candidates（import 静态扫描结果），不依赖生成的
    agents.md 文本——叶子走轻量档（无 DEPENDS 小节）也能正确检出。
    """
    if not rel:
        return set()
    name = rel.rsplit("/", 1)[-1]
    consumers: set[str] = set()
    for node_rel, node in graph.nodes.items():
        if node_rel != rel and name in node.dep_candidates:
            consumers.add(node_rel)
    return consumers


def cmd_init(args: argparse.Namespace) -> int:
    """init：骨架 + .meta + 两阶段生成（波浪 + 失败快照补一轮）。"""
    cwd = Path.cwd()
    target = Path(args.target).resolve() if args.target else cwd
    if not target.is_dir():
        print(f"错误：不是目录：{target}", file=sys.stderr)
        return 1

    knowledge_root = resolve_knowledge_root(cwd)
    engine = load_engine_config(knowledge_root, args.engine)
    write_default_config(knowledge_root)
    budget = getattr(args, "budget", None)
    if budget is None:
        budget = load_budget(knowledge_root)
    prefix = mirror_prefix(knowledge_root, target, cwd)
    # T9：.aimake-link 消费发现指针须在 walk/.meta 之前写入（否则根指纹把链接算作变化）
    if target != cwd:
        link = target / ".aimake-link"
        link.write_text(f"知识路径: {os.path.relpath(prefix, target)}\n", encoding="utf-8")
    result = walk_project(target)
    graph = build_knowledge_graph(result)
    create_skeleton(knowledge_root, target, cwd, result)

    print(f"知识根：{knowledge_root}")
    print(f"扫描目标：{target}")
    print(f"引擎：{engine.name}（command={engine.command or '内置'}）")
    print(f"节点总数：{len(graph.nodes)}")

    # 节点计划：prompt 一次构造，两阶段复用（引用快照、不等待）
    node_plan, degraded = _build_node_plan(graph, result, prefix, budget=budget)
    if degraded:
        print(f"上下文预算：{degraded} 个节点超预算已降级（预算 {budget} 字符）")

    if args.dry_run:
        print("\n== 生成计划（dry-run）==")
        for node in graph.topo_order():
            mirror = node_plan[node.rel][2]
            tier = decide_tier(
                len(result.files.get(node.path, [])), len(node.children)
            )
            tag = "轻量" if tier == TIER_LIGHT else "全量"
            print(f"  [{tag}] {mirror.relative_to(cwd)}/agents.md")
        return 0

    heights = _compute_heights(graph.topo_order())
    # 阶段一：分层波浪生成
    waves1 = _collect_waves(graph.topo_order(), heights)
    print(f"\n== 阶段一：分层生成（{len(waves1)} 层，并发 {args.concurrency}）==")
    ok_list, failed = _generate_waves(waves1, node_plan, engine, args)
    print(f"阶段一：成功 {len(ok_list)}/{len(graph.nodes)} ｜ 失败 {len(failed)}")

    # 阶段二：失败节点用快照补一轮；修复后刷新祖先链（最坏两轮收敛）
    if failed:
        print("\n== 阶段二：快照补一轮（失败重试 + 祖先链刷新）==")
        retry = run_nodes(
            [(rel, node_plan[rel][0], node_plan[rel][1]) for rel in
             {r.rel for r in failed}],
            engine,
            concurrency=args.concurrency,
            retries=args.retries,
        )
        newly_ok: list = []
        still_failed: list = []
        for r in retry:
            if r.ok:
                (node_plan[r.rel][2] / "agents.md").write_text(
                    r.output, encoding="utf-8"
                )
                newly_ok.append(r)
            else:
                still_failed.append(r)
        print(f"  重试：修复 {len(newly_ok)} ｜ 仍失败 {len(still_failed)}")

        # 受影响祖先链（沿树边向上，含根）——用修复后的快照重生成
        affected: set[str] = set()
        for r in newly_ok:
            rel = r.rel
            while rel:
                rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
                if rel in node_plan:
                    affected.add(rel)
        if affected:
            order = [n for n in graph.topo_order() if n.rel in affected]
            waves2 = _collect_waves(order, heights)
            print(f"  祖先链刷新：{len(affected)} 个节点（{'、'.join(sorted(r or '根' for r in affected))}）")
            _ok2, fail2 = _generate_waves(waves2, node_plan, engine, args)
            failed = [r for r in still_failed] + fail2
        else:
            failed = still_failed

    # 最终统计：以镜像目录实际落盘为准
    present = sum(
        1 for n in graph.nodes.values()
        if (node_plan[n.rel][2] / "agents.md").is_file()
    )
    print(f"\n产物落盘：{present}/{len(graph.nodes)} ｜ 失败：{len(failed)}")
    for r in failed:
        print(f"  [失败] {r.rel}：{r.error}")

    return 0 if not failed else 1


def cmd_update(args: argparse.Namespace) -> int:
    """update：指纹驱动（--feedback 走反馈队列）。"""
    if getattr(args, "feedback", False):
        return cmd_update_feedback(args)
    return _cmd_update_fingerprint(args)


def _cmd_update_fingerprint(args: argparse.Namespace) -> int:
    """update（指纹）：受影响子图（本目录 + 祖先链 + DEPENDS 消费者）→ 重生成。"""
    cwd = Path.cwd()
    target = Path(args.target).resolve() if args.target else cwd
    if not target.is_dir():
        print(f"错误：不是目录：{target}", file=sys.stderr)
        return 1

    knowledge_root = resolve_knowledge_root(cwd)
    engine = load_engine_config(knowledge_root, args.engine)
    budget = getattr(args, "budget", None)
    if budget is None:
        budget = load_budget(knowledge_root)
    result = walk_project(target)
    graph = build_knowledge_graph(result)
    prefix = mirror_prefix(knowledge_root, target, cwd)
    node_plan, degraded = _build_node_plan(graph, result, prefix, budget=budget)
    if degraded:
        print(f"上下文预算：{degraded} 个节点超预算已降级（预算 {budget} 字符）")

    # 指纹比对 → 过期节点
    stale: list[str] = []
    for rel, node in graph.nodes.items():
        meta = prefix / rel / ".meta" if rel else prefix / ".meta"
        files = result.files.get(node.path, [])
        if is_stale(node.path, files, meta):
            stale.append(rel)
    stale = sorted(set(stale))

    if not stale:
        print(f"全部最新（{len(graph.nodes)} 个节点，无需重生成）")
        return 0

    # 受影响子图：过期节点 + 祖先链 + DEPENDS 消费者
    affected: set[str] = set(stale)
    for rel in stale:
        affected.update(_ancestors(rel))
    for rel in stale:
        affected.update(_depends_consumers(graph, rel))
    affected = sorted(affected)

    print(f"过期：{len(stale)} 个（{'、'.join(r or '根' for r in stale)}）")
    print(f"受影响子图：{len(affected)} 个（含祖先链与 DEPENDS 消费者）"
          f"：{'、'.join(r or '根' for r in affected)}")

    order = [n for n in graph.topo_order() if n.rel in affected]
    heights = _compute_heights(graph.topo_order())
    waves = _collect_waves(order, heights)
    print(f"\n== 重生成（{len(waves)} 层，并发 {args.concurrency}）==")
    ok_list, failed = _generate_waves(waves, node_plan, engine, args)

    # 重生成成功 → 刷新指纹（未重生成的节点指纹不变，保持"最新"判定）
    for r in ok_list:
        node = graph.nodes[r.rel]
        meta = prefix / node.rel / ".meta" if node.rel else prefix / ".meta"
        write_meta(node.path, result.files.get(node.path, []), meta)

    print(f"\n重生成：{len(ok_list)}/{len(affected)} ｜ 失败：{len(failed)}")
    for r in failed:
        print(f"  [失败] {r.rel}：{r.error}")
    return 0 if not failed else 1


def cmd_status(args: argparse.Namespace) -> int:
    """status：过期清单 + 待处理反馈计数（只读，幂等）。"""
    cwd = Path.cwd()
    target = Path(args.target).resolve() if args.target else cwd
    if not target.is_dir():
        print(f"错误：不是目录：{target}", file=sys.stderr)
        return 1

    knowledge_root = resolve_knowledge_root(cwd)
    prefix = mirror_prefix(knowledge_root, target, cwd)

    # 未初始化提示
    if not (prefix / "agents.md").is_file():
        print(f"知识根尚未初始化：{prefix}")
        print(f"提示：先运行 `aimake init {args.target or ''}`")
        return 0

    result = walk_project(target)
    graph = build_knowledge_graph(result)

    # 通道 1：指纹过期清单（只读判定，不写）
    stale: list[str] = []
    for rel, node in graph.nodes.items():
        meta = prefix / rel / ".meta" if rel else prefix / ".meta"
        files = result.files.get(node.path, [])
        if is_stale(node.path, files, meta):
            stale.append(rel)
    stale.sort(key=lambda r: (r.count("/"), r))

    # 通道 2：待处理反馈队列（解析细节）
    feedback_list = list_feedback(knowledge_root)
    print(f"扫描目标：{target}")
    print(f"节点总数：{len(graph.nodes)} ｜ 过期：{len(stale)} ｜ 待处理反馈：{len(feedback_list)}")
    if stale:
        print("\n== 过期清单（文件变化未重生成）==")
        for rel in stale:
            print(f"  {rel or '根'}  → 建议: aimake update")
    else:
        print("全部最新（无过期节点）")
    if feedback_list:
        print("\n== 待处理反馈 ==")
        for fb in feedback_list:
            srcs = "、".join(fb.sources()[:3])
            more = f" 等 {len(fb.entries)} 条" if len(fb.entries) > 3 else ""
            reporter = f"（{fb.reporter}）" if fb.reporter else ""
            print(f"  [{fb.target or '根'}] {fb.path.name}{reporter} → 来源: {srcs}{more}")
        print("  处理建议: aimake update --feedback")

    # 通道 3：符号自检（零 token，免费自动跑）
    issues = _symbol_selfcheck(graph, result, prefix)
    if issues:
        print("\n== 符号自检（通道 3，零 token）==")
        for rel, kind, item in issues:
            print(f"  [{rel or '根'}] {kind} 失效: {item}")
    return 0


def _section_text(text: str, header: str) -> list[str]:
    """取 agents.md 某 ## 小节内容行。"""
    out: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = line[3:].strip().upper() == header.upper()
            continue
        if in_section and line.strip():
            out.append(line.strip())
    return out


def cmd_tree(args: argparse.Namespace) -> int:
    """tree：知识树总览 = 全局索引物化（目录名 + 一句话摘要 + 过期标记）。"""
    cwd = Path.cwd()
    target = Path(args.target).resolve() if args.target else cwd
    if not target.is_dir():
        print(f"错误：不是目录：{target}", file=sys.stderr)
        return 1

    knowledge_root = resolve_knowledge_root(cwd)
    prefix = mirror_prefix(knowledge_root, target, cwd)
    if not (prefix / "agents.md").is_file():
        print(f"知识根尚未初始化：{prefix}")
        print(f"提示：先运行 `aimake init {args.target or ''}`")
        return 0

    result = walk_project(target)
    graph = build_knowledge_graph(result)
    heights = _compute_heights(graph.topo_order())

    print(f"# 知识树总览 — {target.name}（{len(graph.nodes)} 节点）")

    def render(node, indent: int) -> None:
        rel = node.rel
        md = prefix / rel / "agents.md" if rel else prefix / "agents.md"
        ov = extract_overview(md.read_text(encoding="utf-8")) if md.is_file() else "（未生成）"
        name = target.name if not rel else node.path.name
        warnings: list[str] = []
        info: list[str] = []
        if not md.is_file():
            warnings.append("未生成")
        else:
            meta = prefix / rel / ".meta" if rel else prefix / ".meta"
            if is_stale(node.path, result.files.get(node.path, []), meta):
                warnings.append("过期")
        if node.dep_candidates:
            info.append("依赖: " + ",".join(node.dep_candidates))
        warn = f" ⚠️[{'、'.join(warnings)}]" if warnings else ""
        deps = f" [{', '.join(info)}]" if info else ""
        print(f"{'  ' * indent}{name}/ — {ov}{warn}{deps}")
        for child in node.children:
            render(child, indent + 1)

    render(graph.root, 0)

    # 全局捷径表（根 agents.md 的 WHERE TO LOOK = 全局索引物化）
    root_text = (prefix / "agents.md").read_text(encoding="utf-8")
    shortcuts = _section_text(root_text, "WHERE TO LOOK")
    if shortcuts:
        print("\n== 全局捷径表（根 WHERE TO LOOK）==")
        for line in shortcuts:
            print(f"  {line.lstrip('-').strip()}")
    return 0


_STOPWORDS: frozenset[str] = frozenset(
    "的 了 吗 呢 在 是 怎么 什么 如何 哪 哪里 谁 为什么 请 一下 我 你 它 这 那 有 没 不 要 用".split()
)


def _query_tokens(query: str) -> list[str]:
    """中英混合切词：字母数字整词 + 中文 2 字滑动窗口，去停用词。"""
    import re
    tokens: list[str] = []
    for part in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", query.lower()):
        if part in _STOPWORDS:
            continue
        if re.fullmatch(r"[A-Za-z0-9_]+", part):
            tokens.append(part)
        elif len(part) == 1:
            tokens.append(part)
        else:
            for i in range(len(part) - 1):
                bg = part[i : i + 2]
                if bg not in _STOPWORDS:
                    tokens.append(bg)
    return tokens


def _match_score(tokens: list[str], text: str) -> int:
    """关键词命中计数（确定性匹配，零成本）。"""
    tl = text.lower()
    return sum(1 for t in tokens if t in tl)


def _parse_qa(text: str) -> list[tuple[str, str, str]]:
    """解析 agents.md 的 QA 小节 → [(问题, 答案, 证据)]。"""
    items: list[tuple[str, str, str]] = []
    cur_q, cur_a, cur_ev = "", "", ""
    in_qa = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_qa = line[3:].strip().upper() == "QA"
            continue
        if not in_qa:
            continue
        s = line.strip()
        if not s:
            continue
        if s.startswith(("- Q:", "- Q：")):
            if cur_q:
                items.append((cur_q, cur_a, cur_ev))
            cur_q, cur_a, cur_ev = s[4:].strip(), "", ""
        elif s.startswith(("A:", "A：")):
            cur_a = s[2:].strip()
        elif "证据" in s:
            cur_ev = s.lstrip("-").strip()
            if cur_ev.startswith("证据"):
                cur_ev = cur_ev[2:].strip()
            cur_ev = cur_ev.lstrip(":：").strip()
        elif cur_a:
            cur_a += " " + s
    if cur_q:
        items.append((cur_q, cur_a, cur_ev))
    return items


def cmd_ask(args: argparse.Namespace) -> int:
    """ask：QA 条目确定性匹配 → 命中即答（带来源）；未命中 → 捷径导航/系统性否定。"""
    cwd = Path.cwd()
    target = Path(args.target).resolve() if args.target else cwd
    if not target.is_dir():
        print(f"错误：不是目录：{target}", file=sys.stderr)
        return 1

    knowledge_root = resolve_knowledge_root(cwd)
    prefix = mirror_prefix(knowledge_root, target, cwd)
    if not (prefix / "agents.md").is_file():
        print(f"知识根尚未初始化：{prefix}，先运行 `aimake init {args.target or ''}`")
        return 1

    tokens = _query_tokens(args.question)
    if not tokens:
        print("问题太短，无法匹配。")
        return 1

    hits: list[tuple[int, str, str, str, str]] = []  # (score, rel, q, a, ev)
    navs: list[tuple[int, str, str]] = []  # (score, rel, entry)
    for rel, text in _iter_nodes(prefix):
        for q, a, ev in _parse_qa(text):
            s = _match_score(tokens, q)
            if s:
                hits.append((s, rel, q, a, ev))
        for line in _section_text(text, "WHERE TO LOOK"):
            s = _match_score(tokens, line)
            if s:
                navs.append((s, rel, line))

    hits.sort(key=lambda x: -x[0])
    navs.sort(key=lambda x: -x[0])

    if hits:
        s, rel, q, a, ev = hits[0]
        print(f"命中（来源：{rel or '根'}/agents.md QA 条目）")
        print(f"  问题：{q}")
        print(f"  答案：{a}")
        if ev:
            print(f"  证据：{ev}")
        return 0

    if navs:
        print("未命中 QA，找到导航建议（WHERE TO LOOK 捷径）：")
        for s, rel, line in navs[:5]:
            print(f"  [{rel or '根'}] {line.lstrip('-').strip()}")
        print("提示：沿导航读目标节点 agents.md 可进一步定位。")
        return 1

    print("知识树覆盖范围内未找到相关条目（系统性否定——核实过的「没有」，非猜测）")
    print("建议：`aimake tree` 浏览全树 / 更换措辞 / 直接读源码。")
    return 1


def _iter_nodes(prefix: Path):
    """遍历知识根镜像下全部 agents.md → (rel, 文本)。"""
    if not prefix.is_dir():
        return
    for md in sorted(prefix.rglob("agents.md")):
        rel = md.parent.relative_to(prefix).as_posix()
        rel = "" if rel == "." else rel
        yield rel, md.read_text(encoding="utf-8")


def _symbol_selfcheck(graph, result, prefix: Path) -> list[tuple[str, str, str]]:
    """通道 3（零 token）：KEY SYMBOLS 缺失 / QA 证据行号越界 vs 源码比对。

    强信号才报：符号在本目录可见文件全文找不到 → 失效；
    证据文件能定位但行号越界 → 失效；路径无法定位则跳过（避免误报）。
    """
    import re
    issues: list[tuple[str, str, str]] = []
    for rel, node in graph.nodes.items():
        md = prefix / rel / "agents.md" if rel else prefix / "agents.md"
        if not md.is_file():
            continue
        text = md.read_text(encoding="utf-8")
        files = result.files.get(node.path, [])
        blob = ""
        for f in files:
            p = node.path / f
            try:
                blob += p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass

        # KEY SYMBOLS：符号不在本目录可见文件 → 失效
        for line in _section_text(text, "KEY SYMBOLS"):
            s = line.lstrip("-").strip()
            if not s:
                continue
            if s.startswith("|"):
                # markdown 表格：取符号列（第 1 列）；表头/分隔行跳过
                cells = [c.strip() for c in s.strip("|").split("|")]
                if len(cells) < 3:
                    continue
                if set(cells[0]) <= set("-| :") or cells[0] in ("符号", "Symbol"):
                    continue  # 分隔行或表头
                head = cells[0]
            else:
                head = re.split(r"[：:\s]", s, maxsplit=1)[0]
                head = head.split("(")[0].strip()
            if head and head not in blob:
                issues.append((rel, "KEY SYMBOLS", head))

        # QA 证据指针：文件能定位但行号越界 → 失效
        for q, a, ev in _parse_qa(text):
            for m in re.finditer(r"([\w./\-]+\.\w+):(\d+)", ev):
                fpath, lineno = m.group(1), int(m.group(2))
                cand = node.path / fpath
                if not cand.is_file():
                    cand = result.root / fpath
                if not cand.is_file():
                    continue  # 无法定位，跳过（不误报）
                try:
                    nlines = len(cand.read_text(encoding="utf-8", errors="ignore").splitlines())
                    if lineno > max(nlines, 1):
                        issues.append((rel, "QA 证据", f"{fpath}:{lineno}"))
                except OSError:
                    pass
    return issues


def _feedback_groups(feedback_list: list) -> dict[str, list]:
    """按目标目录分组反馈。"""
    groups: dict[str, list] = {}
    for fb in feedback_list:
        groups.setdefault(fb.target, []).append(fb)
    return groups


def _feedback_decisions(groups: dict[str, list]) -> list[tuple[str, bool, str]]:
    """四方确认 + 阈值（T18/T19）。

    确认条件（任一）：
      ① 不同报告方（四方票）≥2；
      ② 任一条目带证据（事实性错误——反馈本身即事实报告，证据补强即确认）。
    仲裁方 = 目标节点的父目录（owner 的父目录决策，见 AGENTS.md 更新机制）。
    """
    decisions: list[tuple[str, bool, str]] = []
    for target, fbs in sorted(groups.items()):
        reporters = {fb.reporter for fb in fbs if fb.reporter}
        has_evidence = any(e.evidence for fb in fbs for e in fb.entries)
        confirmed = len(reporters) >= 2 or has_evidence
        parent = target.rsplit("/", 1)[0] if "/" in target else "根"
        reason = f"票数={len(reporters)}({len(fbs)}文件) 证据={'有' if has_evidence else '无'} 仲裁={parent}"
        decisions.append((target, confirmed, reason))
    return decisions


def _format_feedback(fbs: list) -> str:
    """反馈条目渲染为提示词注入上下文。"""
    lines: list[str] = []
    for fb in fbs:
        for e in fb.entries:
            lines.append(f"- [{fb.reporter or '消费方'}][来源 {e.source}] 错误：{e.error}")
            if e.evidence:
                lines.append(f"  证据：{e.evidence}")
    return "\n".join(lines)


def _append_task_report(knowledge_root: Path, removed: list, ok_list: list, failed: list) -> None:
    """T21：update 报告写入 tasks.md（更新历史可跨会话查询）。"""
    import datetime
    tasks_md = knowledge_root / "tasks.md"
    lines = [
        "",
        f"## update --feedback（{datetime.date.today().isoformat()}）",
        f"- 处理反馈：{', '.join(removed) or '无'}",
        f"- 重生成：{len(ok_list)} 个（{'、'.join(r.rel or '根' for r in ok_list) or '无'}）",
    ]
    if failed:
        lines.append(f"- 失败：{'、'.join(r.rel for r in failed)}")
    with open(tasks_md, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def cmd_update_feedback(args: argparse.Namespace) -> int:
    """update --feedback：反馈队列 → 四方确认 → 重生成（反馈注入）→ 连锁 → 报告。"""
    cwd = Path.cwd()
    target = Path(args.target).resolve() if args.target else cwd
    if not target.is_dir():
        print(f"错误：不是目录：{target}", file=sys.stderr)
        return 1

    knowledge_root = resolve_knowledge_root(cwd)
    engine = load_engine_config(knowledge_root, args.engine)
    budget = getattr(args, "budget", None)
    if budget is None:
        budget = load_budget(knowledge_root)
    feedback_list = list_feedback(knowledge_root)
    if not feedback_list:
        print("无待处理反馈（.aimake/feedback/ 为空）")
        return 0

    result = walk_project(target)
    graph = build_knowledge_graph(result)
    prefix = mirror_prefix(knowledge_root, target, cwd)

    groups = _feedback_groups(feedback_list)
    decisions = _feedback_decisions(groups)
    print(f"反馈：{len(feedback_list)} 个文件，涉及 {len(groups)} 个目标")
    for t, ok, reason in decisions:
        print(f"  [{t or '根'}] {'确认' if ok else '未达阈值'}（{reason}）")

    confirmed = [t for t, ok, _ in decisions if ok]
    if not confirmed:
        print("\n无确认的反馈（未达阈值），等待更多票或证据。")
        return 0

    # 受影响：确认目标 + 祖先链（连锁更新父级摘要）
    affected: set[str] = set()
    for t in confirmed:
        affected.add(t)
        affected.update(_ancestors(t))

    # 反馈注入提示词（可精确到条目）
    node_plan, degraded = _build_node_plan(graph, result, prefix, budget=budget)
    feedback_by_target = {t: groups[t] for t in confirmed}
    for t in confirmed:
        prompt, path, mirror = node_plan[t]
        extra = _format_feedback(feedback_by_target[t])
        node_plan[t] = (
            prompt + "\n\n# 消费侧纠错反馈（事实性错误，必须按证据修正后重新生成）\n" + extra,
            path, mirror,
        )

    order = [n for n in graph.topo_order() if n.rel in affected]
    heights = _compute_heights(graph.topo_order())
    waves = _collect_waves(order, heights)
    print(f"\n== 反馈驱动重生成（{len(waves)} 层）==")
    ok_list, failed = _generate_waves(waves, node_plan, engine, args)

    # 成功 → 刷新指纹 + 移除已处理反馈
    for r in ok_list:
        node = graph.nodes[r.rel]
        meta = prefix / node.rel / ".meta" if node.rel else prefix / ".meta"
        write_meta(node.path, result.files.get(node.path, []), meta)
    removed: list[str] = []
    for t in confirmed:
        for fb in feedback_by_target[t]:
            fb.path.unlink(missing_ok=True)
            removed.append(fb.path.name)

    print(f"\n重生成：{len(ok_list)}/{len(affected)} ｜ 失败：{len(failed)}")
    for r in failed:
        print(f"  [失败] {r.rel}：{r.error}")
    print(f"已处理反馈：{len(removed)} 个")

    # T21：更新历史写入 tasks.md
    _append_task_report(knowledge_root, removed, ok_list, failed)
    print(f"更新报告已写入 {knowledge_root / 'tasks.md'}")
    return 0 if not failed else 1


def _parse_proposal_dirs(proposal_text: str) -> list[str]:
    """从提案目录结构（缩进列表）解析目录路径。

    缩进=层级；跳过文件（含扩展名）；深度 0 行若存在更深行则视为项目根包装。
    """
    raw: list[tuple[int, str]] = []
    stack: dict[int, str] = {}
    in_fence = False
    for line in proposal_text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        stripped = line.strip()
        if not stripped or "──" in stripped:
            continue
        name = stripped.split("#")[0].strip().rstrip("/")  # 去注释与尾部斜杠
        if not name or "." in name:
            continue  # 空行或文件
        depth = (len(line) - len(line.lstrip(" "))) // 2
        parent = stack.get(depth - 1, "")
        rel = f"{parent}/{name}" if parent else name
        stack[depth] = rel
        raw.append((depth, rel))
    max_depth = max((d for d, _ in raw), default=0)
    if max_depth > 0:
        raw = [(d, r) for d, r in raw if d > 0]
    return [r for _, r in raw]


def _parse_source_blocks(text: str) -> list[tuple[str, str]]:
    """解析源码清单：fenced 块首行文件名 + 内容。"""
    import re
    blocks: list[tuple[str, str]] = []
    for m in re.finditer(r"```([^\n`]*)\n(.*?)```", text, re.S):
        fname = m.group(1).strip()
        content = m.group(2).rstrip("\n")
        if fname and fname not in ("bash", "python", "text", "markdown", "json", "yaml", "sh"):
            blocks.append((fname, content))
    return blocks


def _write_skeleton(out: Path, proposal_text: str) -> None:
    """T29：生成骨架（README / plan / task；proposal 已存在）。"""
    one_liner = ""
    in_section = False
    for line in proposal_text.splitlines():
        if line.startswith("## 一句话定位"):
            in_section = True
            continue
        if in_section and line.strip():
            one_liner = line.strip()
            break
    (out / "README.md").write_text(
        f"# {out.name}\n\n> {one_liner or '（由 aimake scaffold 生成）'}\n\n详见 [proposal.md](proposal.md)。\n",
        encoding="utf-8",
    )
    (out / "plan.md").write_text(
        "# plan.md — 项目计划\n\n> 由 aimake scaffold 生成（依据 proposal.md）。\n\n## 里程碑\n- 见 proposal.md「里程碑」\n",
        encoding="utf-8",
    )
    (out / "task.md").write_text(
        "# task.md — 任务清单\n\n> 由 aimake scaffold 生成。\n\n## 任务列表\n\n- [ ] 按 proposal.md「功能清单」拆解\n",
        encoding="utf-8",
    )


def _auto_init(out: Path, engine, args) -> int:
    """T30：生成后自动跑 init（知识树与项目同生）。"""
    cwd = Path.cwd()
    knowledge_root = resolve_knowledge_root(cwd)
    prefix = mirror_prefix(knowledge_root, out, cwd)
    # .aimake-link 须在 walk/.meta 之前写入（否则根指纹把链接算作变化）
    if out != cwd:
        link = out / ".aimake-link"
        link.write_text(f"知识路径: {os.path.relpath(prefix, out)}\n", encoding="utf-8")
    result = walk_project(out)
    graph = build_knowledge_graph(result)
    create_skeleton(knowledge_root, out, cwd, result)
    budget = getattr(args, "budget", None)
    if budget is None:
        budget = load_budget(knowledge_root)
    node_plan, _ = _build_node_plan(graph, result, prefix, budget=budget)
    heights = _compute_heights(graph.topo_order())
    waves = _collect_waves(graph.topo_order(), heights)
    print(f"\n== 自动 init：知识树生成（{len(graph.nodes)} 节点）==")
    ok_list, failed = _generate_waves(waves, node_plan, engine, args)
    print(f"知识树：{len(ok_list)}/{len(graph.nodes)} ｜ 失败：{len(failed)}")
    for r in failed:
        print(f"  [失败] {r.rel}：{r.error}")
    return 0 if not failed else 1


def cmd_scaffold(args: argparse.Namespace) -> int:
    """scaffold：一句话 → 提案（T26）→ 确认（T27）→ 源码（T28）→ 骨架（T29）→ init（T30）。"""
    import re
    cwd = Path.cwd()
    if args.out:
        out = Path(args.out).resolve()
    else:
        slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", args.description).strip("-")
        out = cwd / (slug[:30] or "generated")
    out.mkdir(parents=True, exist_ok=True)

    knowledge_root = resolve_knowledge_root(cwd)
    engine = load_engine_config(knowledge_root, args.engine)
    proposal = out / "proposal.md"

    # T26：提案生成
    print(f"需求：{args.description}")
    print(f"输出目录：{out.relative_to(cwd)}")
    print(f"引擎：{engine.name} —— 生成项目提案…")
    try:
        text = run_engine(engine, build_proposal_prompt(args.description), cwd)
    except Exception as exc:
        print(f"[失败] 提案生成：{exc}")
        return 1
    proposal.write_text(text, encoding="utf-8")
    print(f"提案已生成：{proposal.relative_to(cwd)}")

    # T27：确认交互（--default 跳过）
    if not getattr(args, "default", False):
        for _ in range(3):
            print("\n" + text[:500] + ("\n…（截断）" if len(text) > 500 else ""))
            ans = input("确认提案？[y=确认 / n=取消 / 输入修改要求]: ").strip()
            if ans.lower() in ("y", "yes", ""):
                break
            if ans.lower() in ("n", "no"):
                print("已取消。")
                return 0
            try:
                text = run_engine(
                    engine,
                    build_proposal_prompt(args.description + "\n\n补充要求：" + ans),
                    cwd,
                )
            except Exception as exc:
                print(f"[失败] 提案重新生成：{exc}")
                return 1
            proposal.write_text(text, encoding="utf-8")
        else:
            print("确认轮次超限，已中止。")
            return 1

    # T28：按目录粒度生成源码
    dirs = _parse_proposal_dirs(text)
    if not dirs:
        dirs = ["."]
    print(f"\n源码生成（{len(dirs)} 个目录）…")
    plan: list[tuple[str, str, Path]] = []
    for rel in dirs:
        abs_dir = out / rel
        abs_dir.mkdir(parents=True, exist_ok=True)
        plan.append((rel, build_source_prompt(rel, text), abs_dir))
    results = run_nodes(
        [(r, p, c) for r, p, c in plan],
        engine, concurrency=args.concurrency, retries=args.retries,
    )
    for r in results:
        if not r.ok:
            print(f"  [失败] {r.rel}：{r.error}")
            continue
        for fname, content in _parse_source_blocks(r.output):
            target = out / r.rel / fname if r.rel != "." else out / fname
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            print(f"  {r.rel}/{fname}")

    # T29：骨架（README/plan/task）
    _write_skeleton(out, text)
    print("骨架：README.md / plan.md / task.md 已生成")

    # T30：自动 init（知识树与项目同生）
    return _auto_init(out, engine, args)


def cmd_maintain(args: argparse.Namespace) -> int:
    """maintain：一键维护循环 = 状态检查 → 指纹更新 → 反馈处理 → 符号自检报告。"""
    cwd = Path.cwd()
    target = Path(args.target).resolve() if args.target else cwd
    if not target.is_dir():
        print(f"错误：不是目录：{target}", file=sys.stderr)
        return 1

    knowledge_root = resolve_knowledge_root(cwd)
    prefix = mirror_prefix(knowledge_root, target, cwd)
    result = walk_project(target)
    graph = build_knowledge_graph(result)

    # ① 检查（只读）
    stale = sorted(
        rel for rel, node in graph.nodes.items()
        if is_stale(
            node.path,
            result.files.get(node.path, []),
            prefix / rel / ".meta" if rel else prefix / ".meta",
        )
    )
    groups = _feedback_groups(list_feedback(knowledge_root))
    confirmed = [t for t, ok, _ in _feedback_decisions(groups) if ok]
    issues = _symbol_selfcheck(graph, result, prefix)

    print(f"维护检查：节点 {len(graph.nodes)} ｜ 过期 {len(stale)} ｜"
          f" 确认反馈 {len(confirmed)} ｜ 符号失效 {len(issues)}")

    code = 0
    # ② 指纹更新
    if stale:
        print("\n== 指纹更新 ==")
        code = max(code, _cmd_update_fingerprint(args))
    # ③ 反馈处理
    if confirmed:
        print("\n== 反馈处理 ==")
        code = max(code, cmd_update_feedback(args))
    if not stale and not confirmed:
        print("全部最新，无需更新。")
    if issues:
        print(f"\n== 符号自检：{len(issues)} 处失效（可写反馈走 update --feedback 纠错）==")
        for rel, kind, item in issues[:10]:
            print(f"  [{rel or '根'}] {kind} 失效: {item}")
    print("\n维护完成。")
    return code


def cmd_ignore(args: argparse.Namespace) -> int:
    """ignore：CLI 管理 .aimakeignore（add/remove/list/reset）。"""
    cwd = Path.cwd()
    target = Path(args.project).resolve() if args.project else cwd
    if not target.is_dir():
        print(f"错误：不是目录：{target}", file=sys.stderr)
        return 1
    ignore_file = target / IGNORE_FILE

    if args.action == "list":
        print(f"默认忽略（内置）：{'、'.join(DEFAULT_IGNORES)}")
        print(f"自定义（{ignore_file}）：")
        if ignore_file.is_file():
            for raw in ignore_file.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line:
                    print(f"  {line}")
        else:
            print("  （无）")
        return 0

    if args.action == "reset":
        if ignore_file.exists():
            ignore_file.unlink()
            print(f"已清空自定义忽略（{ignore_file}）")
        else:
            print("无自定义忽略文件，无需重置")
        return 0

    pattern = args.pattern
    if not pattern:
        print("错误：add/remove 需要规则参数（如：aimake ignore add .omo/）", file=sys.stderr)
        return 1

    existing: list[str] = []
    if ignore_file.is_file():
        existing = ignore_file.read_text(encoding="utf-8").splitlines()
    cleaned = [ln for ln in existing if ln.strip() and not ln.strip().startswith("#")]
    stripped = {ln.strip() for ln in cleaned}

    if args.action == "add":
        if pattern in stripped:
            print(f"已存在：{pattern}")
            return 0
        ignore_file.parent.mkdir(parents=True, exist_ok=True)
        with open(ignore_file, "a", encoding="utf-8") as f:
            if existing and existing[-1].strip():
                f.write("\n")
            f.write(pattern + "\n")
        print(f"已添加：{pattern}（下次 init/update/scan 生效）")
        return 0

    if args.action == "remove":
        if pattern not in stripped:
            print(f"未找到：{pattern}")
            return 1
        remaining = [ln for ln in existing
                     if ln.strip() and ln.strip() != pattern]
        ignore_file.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        print(f"已移除：{pattern}")
        return 0

    print(f"未知操作：{args.action}", file=sys.stderr)
    return 1


def cmd_not_implemented(name: str) -> int:
    print(f"{name}：尚未实现（规划中，见 plan.md / task.md）")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aimake",
        description="分层 AI 知识库生成器（基于 codex exec / opencode run）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="扫描可见目录树（ignore 规则生效）")
    p_scan.add_argument("path", nargs="?", default=".", help="项目路径（默认当前目录）")
    p_scan.add_argument("--deps", action="store_true", help="输出依赖候选名单与生成拓扑序")
    p_scan.set_defaults(func=cmd_scan)

    p_init = sub.add_parser("init", help="知识根生成目标项目镜像知识树（骨架+生成）")
    p_init.add_argument("target", nargs="?", default=None, help="扫描目标项目（默认当前目录）")
    p_init.add_argument("--engine", default=None, help="生成引擎（codex/opencode/mock/自定义名；默认读配置）")
    p_init.add_argument("--concurrency", type=int, default=4, help="并发上限（默认 4）")
    p_init.add_argument("--retries", type=int, default=2, help="失败重试次数（默认 2）")
    p_init.add_argument("--budget", type=int, default=None, help="每节点提示词预算（字符，超预算降级；0=不限制）")
    p_init.add_argument("--dry-run", action="store_true", help="只打印计划不执行")
    p_init.set_defaults(func=cmd_init)

    p_update = sub.add_parser("update", help="指纹驱动重生成受影响目录链（--feedback 走反馈队列）")
    p_update.add_argument("target", nargs="?", default=None, help="扫描目标项目（默认当前目录）")
    p_update.add_argument("--engine", default=None, help="生成引擎（默认读配置）")
    p_update.add_argument("--concurrency", type=int, default=4, help="并发上限（默认 4）")
    p_update.add_argument("--retries", type=int, default=2, help="失败重试次数（默认 2）")
    p_update.add_argument("--budget", type=int, default=None, help="每节点提示词预算（字符，超预算降级；0=不限制）")
    p_update.add_argument("--feedback", action="store_true", help="反馈驱动：四方确认 → 重生成纠错队列")
    p_update.set_defaults(func=cmd_update)

    p_status = sub.add_parser("status", help="过期清单 / 待处理反馈（只读）")
    p_status.add_argument("target", nargs="?", default=None, help="扫描目标项目（默认当前目录）")
    p_status.set_defaults(func=cmd_status)

    p_tree = sub.add_parser("tree", help="知识树总览（全局索引物化）")
    p_tree.add_argument("target", nargs="?", default=None, help="扫描目标项目（默认当前目录）")
    p_tree.set_defaults(func=cmd_tree)

    p_ask = sub.add_parser("ask", help="QA 问答：命中即答（带来源），未命中给导航")
    p_ask.add_argument("question", help="问题（如：driver 怎么配置）")
    p_ask.add_argument("target", nargs="?", default=None, help="扫描目标项目（默认当前目录）")
    p_ask.set_defaults(func=cmd_ask)

    p_scaffold = sub.add_parser("scaffold", help="从描述生成项目（一句话 → 提案 → 源码 → init）")
    p_scaffold.add_argument("description", help="项目描述（如：创建数学大厦）")
    p_scaffold.add_argument("--out", default=None, help="生成目录（默认按描述自动命名）")
    p_scaffold.add_argument("--engine", default=None, help="生成引擎（默认读配置）")
    p_scaffold.add_argument("--default", action="store_true", help="跳过提案确认（快速模式）")
    p_scaffold.add_argument("--concurrency", type=int, default=4, help="并发上限（默认 4）")
    p_scaffold.add_argument("--retries", type=int, default=2, help="失败重试次数（默认 2）")
    p_scaffold.set_defaults(func=cmd_scaffold)

    p_maintain = sub.add_parser("maintain", help="一键维护：状态检查 → 指纹更新 → 反馈处理 → 报告")
    p_maintain.add_argument("target", nargs="?", default=None, help="扫描目标项目（默认当前目录）")
    p_maintain.add_argument("--engine", default=None, help="生成引擎（默认读配置）")
    p_maintain.add_argument("--concurrency", type=int, default=4, help="并发上限（默认 4）")
    p_maintain.add_argument("--retries", type=int, default=2, help="失败重试次数（默认 2）")
    p_maintain.add_argument("--budget", type=int, default=None, help="每节点提示词预算（字符，超预算降级；0=不限制）")
    p_maintain.set_defaults(func=cmd_maintain)

    p_ignore = sub.add_parser("ignore", help="CLI 管理忽略规则（.aimakeignore）")
    p_ignore.add_argument("action", choices=["add", "remove", "list", "reset"],
                          help="add=添加规则 / remove=移除 / list=查看 / reset=清空自定义")
    p_ignore.add_argument("pattern", nargs="?", default=None,
                          help="规则（add/remove 用，如 .omo/ 或 *.log）")
    p_ignore.add_argument("--project", default=None, help="目标项目（默认当前目录）")
    p_ignore.set_defaults(func=cmd_ignore)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
