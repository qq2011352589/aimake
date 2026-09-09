"""aimake CLI 入口：四灵魂命令 init / update / status / tree。"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .atomic import atomic_write_text
from .engine import load_budget, load_engine_config, write_default_config
from .feedback import list_feedback
from .graph import KnowledgeGraph, build_knowledge_graph
from .meta import is_stale, write_meta
from .prompt import TIER_FULL, TIER_LIGHT, NodeContext, build_prompt_budgeted, decide_tier, extract_overview
from .runner import run_nodes
from .skeleton import create_skeleton, mirror_prefix, resolve_knowledge_root
from .walk import WalkResult, walk_project


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


def _generate_waves(
    waves: list, node_plan: dict, engine, args,
    *, deadline: float | None = None, max_nodes: int | None = None,
    state: dict | None = None,
) -> tuple[list, list]:
    """执行波浪生成并写产物。返回 (成功列表, 失败列表)。

    deadline/max_nodes 为预算闸：到点/到限即停并写入 state（done/stopped），
    供调用方决定续跑；两者均 None 时行为与无预算完全一致。
    """
    if state is None:
        state = {}
    ok: list = []
    failed: list = []
    total_waves = len(waves)
    for wi, wave in enumerate(waves, 1):
        if deadline is not None and time.monotonic() >= deadline:
            state["stopped"] = "time"
            print(f"  ⏸ 时间预算耗尽，暂停于层 {wi}/{total_waves}")
            break
        if max_nodes is not None:
            remaining = max_nodes - state.get("done", 0)
            if remaining <= 0:
                state["stopped"] = "max_nodes"
                print(f"  ⏸ 已达节点上限 {max_nodes}，暂停于层 {wi}/{total_waves}")
                break
            wave = wave[:remaining]
        print(f"  层 {wi}/{total_waves}：{len(wave)} 个节点并行…", flush=True)
        plan = [(n.rel, node_plan[n.rel][0], node_plan[n.rel][1]) for n in wave]
        gen = run_nodes(
            [(rel, p, c) for rel, p, c in plan],
            engine,
            concurrency=args.concurrency,
            retries=args.retries,
        )
        state["done"] = state.get("done", 0) + len(gen)
        for r in gen:
            if r.ok:
                atomic_write_text(node_plan[r.rel][2] / "agents.md", r.output)
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


def _stale_nodes(graph: KnowledgeGraph, result: WalkResult, prefix: Path) -> list[str]:
    """指纹比对：返回过期节点 rel 列表（去重排序，确定性）。"""
    stale: list[str] = []
    for rel, node in graph.nodes.items():
        meta = prefix / rel / ".meta" if rel else prefix / ".meta"
        files = result.files.get(node.path, [])
        if is_stale(node.path, files, meta):
            stale.append(rel)
    return sorted(set(stale))


def _missing_nodes(graph: KnowledgeGraph, prefix: Path) -> list[str]:
    """返回尚未落盘 agents.md 的节点 rel 列表（init 断点续跑复用）。"""
    missing: list[str] = []
    for rel in graph.nodes:
        md = prefix / rel / "agents.md" if rel else prefix / "agents.md"
        # 0 字节产物视为缺失：引擎返回空内容（如推理模型耗尽 token 预算）时需重生成
        if not md.is_file() or md.stat().st_size == 0:
            missing.append(rel)
    return sorted(missing)


def _affected_subgraph(graph: KnowledgeGraph, seed: list[str]) -> set[str]:
    """受影响子图：种子节点 + 祖先链 + DEPENDS 消费者（与 update 同语义）。"""
    return (
        set(seed)
        | {a for rel in seed for a in _ancestors(rel)}
        | {c for rel in seed for c in _depends_consumers(graph, rel)}
    )


def _refresh_meta(
    ok_list: list, graph: KnowledgeGraph, result: WalkResult, prefix: Path,
) -> None:
    """生成成功 → 刷新 .meta 指纹（未重生成节点指纹不变，保持"最新"判定）。"""
    for r in ok_list:
        node = graph.nodes[r.rel]
        meta = prefix / node.rel / ".meta" if node.rel else prefix / ".meta"
        write_meta(node.path, result.files.get(node.path, []), meta)


def cmd_init(args: argparse.Namespace) -> int:
    """init：骨架 + 需要集生成（断点续跑 + 时间/节点预算，两阶段收敛）。"""
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
        atomic_write_text(link, f"知识路径: {os.path.relpath(prefix, target)}\n")
    result = walk_project(target)
    graph = build_knowledge_graph(result)
    create_skeleton(knowledge_root, target, cwd, result)

    print(f"知识根：{knowledge_root}")
    print(f"扫描目标：{target}")
    print(f"引擎：{engine.name}（command={engine.command or '内置'}）")
    print(f"节点总数：{len(graph.nodes)}")

    # 断点续跑：缺失（.meta 匹配也算）∪ 过期 → 受影响子图（本节点+祖先+消费者）
    seed = set(_missing_nodes(graph, prefix)) | set(_stale_nodes(graph, result, prefix))
    need = _affected_subgraph(graph, seed)
    if not need:
        print(f"全部最新（{len(graph.nodes)} 个节点，无需重生成）")
        return 0

    # 节点计划：prompt 一次构造，两阶段复用（引用快照、不等待）；覆盖全图供聚合
    node_plan, degraded = _build_node_plan(graph, result, prefix, budget=budget)
    if degraded:
        print(f"上下文预算：{degraded} 个节点超预算已降级（预算 {budget} 字符）")

    if args.dry_run:
        print("\n== 生成计划（dry-run）==")
        for node in graph.topo_order():
            if node.rel not in need:
                continue
            mirror = node_plan[node.rel][2]
            tier = decide_tier(
                len(result.files.get(node.path, [])), len(node.children)
            )
            tag = "轻量" if tier == TIER_LIGHT else "全量"
            print(f"  [{tag}] {mirror.relative_to(cwd)}/agents.md")
        return 0

    heights = _compute_heights(graph.topo_order())
    order = [n for n in graph.topo_order() if n.rel in need]
    waves1 = _collect_waves(order, heights)
    time_budget = getattr(args, "time_budget", None)
    max_nodes = getattr(args, "max_nodes", None)
    deadline = time.monotonic() + time_budget if time_budget is not None else None
    state: dict = {"done": 0, "stopped": ""}

    # 阶段一：分层波浪生成
    print(f"\n== 阶段一：分层生成（{len(waves1)} 层，并发 {args.concurrency}）==")
    ok_list, failed = _generate_waves(
        waves1, node_plan, engine, args,
        deadline=deadline, max_nodes=max_nodes, state=state,
    )
    _refresh_meta(ok_list, graph, result, prefix)
    print(f"阶段一：成功 {len(ok_list)}/{len(need)} ｜ 失败 {len(failed)}")

    if state.get("stopped"):
        reason = {"time": "时间预算耗尽", "max_nodes": "节点数上限"}[state["stopped"]]
        deferred = sum(
            1 for rel in need if not (node_plan[rel][2] / "agents.md").is_file()
        )
        print(f"\n已暂停：{reason}（本次生成 {state['done']} 个，待续跑 {deferred} 个）")
        print("续跑：再次运行 `aimake init <目标>`（已完成节点自动跳过）")
        return 0 if not failed else 1

    # 阶段二：失败节点用快照补一轮；修复后刷新祖先链（最坏两轮收敛）
    if failed and not state.get("stopped"):
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
                atomic_write_text(node_plan[r.rel][2] / "agents.md", r.output)
                newly_ok.append(r)
            else:
                still_failed.append(r)
        _refresh_meta(newly_ok, graph, result, prefix)
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
            order2 = [n for n in graph.topo_order() if n.rel in affected]
            waves2 = _collect_waves(order2, heights)
            print(f"  祖先链刷新：{len(affected)} 个节点（{'、'.join(sorted(r or '根' for r in affected))}）")
            _ok2, fail2 = _generate_waves(
                waves2, node_plan, engine, args,
                deadline=deadline, max_nodes=max_nodes, state=state,
            )
            _refresh_meta(_ok2, graph, result, prefix)
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
    """update：指纹驱动重生成受影响目录链。"""
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
    stale = _stale_nodes(graph, result, prefix)

    if not stale:
        print(f"全部最新（{len(graph.nodes)} 个节点，无需重生成）")
        return 0

    # 受影响子图：过期节点 + 祖先链 + DEPENDS 消费者
    affected = sorted(_affected_subgraph(graph, stale))

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
        print("  处理建议: python -m aimake.experimental update --feedback")

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aimake",
        description="分层 AI 知识库生成器（基于 codex exec / opencode run）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="知识根生成目标项目镜像知识树（骨架+生成）")
    p_init.add_argument("target", nargs="?", default=None, help="扫描目标项目（默认当前目录）")
    p_init.add_argument("--engine", default=None, help="生成引擎（codex/opencode/mock/自定义名；默认读配置）")
    p_init.add_argument("--concurrency", type=int, default=4, help="并发上限（默认 4）")
    p_init.add_argument("--retries", type=int, default=2, help="失败重试次数（默认 2）")
    p_init.add_argument("--budget", type=int, default=None, help="每节点提示词预算（字符，超预算降级；0=不限制）")
    p_init.add_argument("--time-budget", type=int, default=None, help="生成时间预算（秒）；到点暂停并保留已完成节点，重跑续传（0=立即暂停）")
    p_init.add_argument("--max-nodes", type=int, default=None, help="单次最多生成的节点数；到限暂停，重跑续传")
    p_init.add_argument("--dry-run", action="store_true", help="只打印计划不执行")
    p_init.set_defaults(func=cmd_init)

    p_update = sub.add_parser("update", help="指纹驱动重生成受影响目录链")
    p_update.add_argument("target", nargs="?", default=None, help="扫描目标项目（默认当前目录）")
    p_update.add_argument("--engine", default=None, help="生成引擎（默认读配置）")
    p_update.add_argument("--concurrency", type=int, default=4, help="并发上限（默认 4）")
    p_update.add_argument("--retries", type=int, default=2, help="失败重试次数（默认 2）")
    p_update.add_argument("--budget", type=int, default=None, help="每节点提示词预算（字符，超预算降级；0=不限制）")
    p_update.set_defaults(func=cmd_update)

    p_status = sub.add_parser("status", help="过期清单 / 待处理反馈（只读）")
    p_status.add_argument("target", nargs="?", default=None, help="扫描目标项目（默认当前目录）")
    p_status.set_defaults(func=cmd_status)

    p_tree = sub.add_parser("tree", help="知识树总览（全局索引物化）")
    p_tree.add_argument("target", nargs="?", default=None, help="扫描目标项目（默认当前目录）")
    p_tree.set_defaults(func=cmd_tree)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
