"""aimake CLI 入口（T12：scan / init / update 可验收，其余规划中）。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .engine import load_engine_config, write_default_config
from .graph import build_knowledge_graph
from .meta import is_stale, write_meta
from .prompt import TIER_LIGHT, NodeContext, build_prompt, decide_tier, extract_overview
from .runner import GenResult, run_nodes
from .skeleton import create_skeleton, mirror_prefix, resolve_knowledge_root
from .walk import walk_project

_PLANNED: tuple[tuple[str, str], ...] = (
    ("tree", "知识树总览（规划中）"),
    ("ask", "QA 问答（规划中）"),
    ("scaffold", "从描述生成项目（规划中）"),
)


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


def _build_node_plan(graph, result, prefix: Path) -> dict[str, tuple[str, Path, Path]]:
    """构造全部节点计划：rel → (prompt, 源目录, 镜像目录)。prompt 一次构造供复用。"""
    node_plan: dict[str, tuple[str, Path, Path]] = {}
    for node in graph.topo_order():
        mirror = prefix / node.rel if node.rel else prefix
        files = result.files.get(node.path, [])
        child_summaries = _collect_child_summaries(node, prefix)
        tier = decide_tier(len(files), len(node.children))
        ctx = NodeContext(
            rel=node.rel or ".",
            files=files,
            child_summaries=child_summaries,
            dep_candidates=node.dep_candidates,
        )
        # T9：根节点（rel=""）加全局增强要求
        prompt = build_prompt(ctx, tier, is_root=node.rel == "")
        node_plan[node.rel] = (prompt, node.path, mirror)
    return node_plan


def _generate_waves(waves: list, node_plan: dict, engine, args) -> tuple[list, list]:
    """执行波浪生成并写产物。返回 (成功列表, 失败列表)。"""
    ok: list = []
    failed: list = []
    for wi, wave in enumerate(waves, 1):
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
    node_plan = _build_node_plan(graph, result, prefix)

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
    """update：指纹对比 → 受影响子图（本目录 + 祖先链 + DEPENDS 消费者）→ 重生成。"""
    cwd = Path.cwd()
    target = Path(args.target).resolve() if args.target else cwd
    if not target.is_dir():
        print(f"错误：不是目录：{target}", file=sys.stderr)
        return 1

    knowledge_root = resolve_knowledge_root(cwd)
    engine = load_engine_config(knowledge_root, args.engine)
    result = walk_project(target)
    graph = build_knowledge_graph(result)
    prefix = mirror_prefix(knowledge_root, target, cwd)
    node_plan = _build_node_plan(graph, result, prefix)

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

    # 通道 2：待处理反馈队列（.aimake/feedback/ 下文件）
    fb_dir = knowledge_root / "feedback"
    feedback_files = (
        sorted(f.name for f in fb_dir.iterdir() if f.is_file())
        if fb_dir.is_dir() else []
    )

    print(f"扫描目标：{target}")
    print(f"节点总数：{len(graph.nodes)} ｜ 过期：{len(stale)} ｜ 待处理反馈：{len(feedback_files)}")
    if stale:
        print("\n== 过期清单（文件变化未重生成）==")
        for rel in stale:
            print(f"  {rel or '根'}  → 建议: aimake update")
    else:
        print("全部最新（无过期节点）")
    if feedback_files:
        print("\n== 待处理反馈 ==")
        for f in feedback_files:
            print(f"  {f}  → 建议: aimake update --feedback")
    return 0


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
    p_init.add_argument("--dry-run", action="store_true", help="只打印计划不执行")
    p_init.set_defaults(func=cmd_init)

    p_update = sub.add_parser("update", help="指纹驱动重生成受影响目录链")
    p_update.add_argument("target", nargs="?", default=None, help="扫描目标项目（默认当前目录）")
    p_update.add_argument("--engine", default=None, help="生成引擎（默认读配置）")
    p_update.add_argument("--concurrency", type=int, default=4, help="并发上限（默认 4）")
    p_update.add_argument("--retries", type=int, default=2, help="失败重试次数（默认 2）")
    p_update.set_defaults(func=cmd_update)

    p_status = sub.add_parser("status", help="过期清单 / 待处理反馈（只读）")
    p_status.add_argument("target", nargs="?", default=None, help="扫描目标项目（默认当前目录）")
    p_status.set_defaults(func=cmd_status)

    for name, help_text in _PLANNED:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=lambda a, _n=name: cmd_not_implemented(_n))

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
