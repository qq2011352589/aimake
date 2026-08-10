"""aimake CLI 入口（T9：scan / init 可验收，其余规划中）。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .engine import load_engine_config, write_default_config
from .graph import build_knowledge_graph
from .prompt import TIER_LIGHT, NodeContext, build_prompt, decide_tier, extract_overview
from .runner import GenResult, run_nodes
from .skeleton import create_skeleton, mirror_prefix, resolve_knowledge_root
from .walk import walk_project

_PLANNED: tuple[tuple[str, str], ...] = (
    ("update", "指纹驱动更新（规划中）"),
    ("status", "过期清单/反馈队列/符号自检（规划中）"),
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


def _collect_waves(topo_order: list) -> list[list]:
    """按"距叶子高度"分组波浪：叶子（0）→ 根；同层节点互相独立可并行。"""
    height: dict[str, int] = {}
    for node in topo_order:  # 后序：子级高度已算好
        if not node.children:
            height[node.rel] = 0
        else:
            height[node.rel] = max(height[c.rel] + 1 for c in node.children)
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


def cmd_init(args: argparse.Namespace) -> int:
    """init：骨架 + .meta + 分层波浪生成（叶子 → 父级 → 根）。"""
    cwd = Path.cwd()
    target = Path(args.target).resolve() if args.target else cwd
    if not target.is_dir():
        print(f"错误：不是目录：{target}", file=sys.stderr)
        return 1

    knowledge_root = resolve_knowledge_root(cwd)
    engine = load_engine_config(knowledge_root, args.engine)
    write_default_config(knowledge_root)
    result = walk_project(target)
    graph = build_knowledge_graph(result)
    create_skeleton(knowledge_root, target, cwd, result)

    prefix = mirror_prefix(knowledge_root, target, cwd)
    print(f"知识根：{knowledge_root}")
    print(f"扫描目标：{target}")
    print(f"引擎：{engine.name}（command={engine.command or '内置'}）")
    print(f"节点总数：{len(graph.nodes)}")

    if args.dry_run:
        print("\n== 生成计划（dry-run）==")
        for wave in _collect_waves(graph.topo_order()):
            for node in wave:
                mirror = prefix / node.rel if node.rel else prefix
                tier = decide_tier(
                    len(result.files.get(node.path, [])), len(node.children)
                )
                tag = "轻量" if tier == TIER_LIGHT else "全量"
                print(f"  [{tag}] {mirror.relative_to(cwd)}/agents.md")
        return 0

    # 分层波浪生成
    waves = _collect_waves(graph.topo_order())
    total_ok = 0
    failed: list[GenResult] = []
    print(f"\n== 分层生成（{len(waves)} 层，并发 {args.concurrency}）==")
    for wi, wave in enumerate(waves, 1):
        plan: list[tuple[str, str, Path, Path]] = []
        for node in wave:
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
            # T9：根节点（rel=""）加全局增强要求（跨目录契约 + 全局捷径表）
            plan.append(
                (node.rel, build_prompt(ctx, tier, is_root=node.rel == ""),
                 node.path, mirror)
            )

        gen = run_nodes(
            [(rel, prompt, cwd_) for rel, prompt, cwd_, _ in plan],
            engine,
            concurrency=args.concurrency,
            retries=args.retries,
        )
        mirror_map = {rel: mirror for rel, _, _, mirror in plan}
        for r in gen:
            if r.ok:
                (mirror_map[r.rel] / "agents.md").write_text(r.output, encoding="utf-8")
                total_ok += 1
            else:
                failed.append(r)
        print(f"  层 {wi}: 成功 {sum(1 for r in gen if r.ok)}/{len(gen)}")

    print(f"\n成功：{total_ok}/{len(graph.nodes)} ｜ 失败：{len(failed)}")
    for r in failed:
        print(f"  [失败] {r.rel}：{r.error}")

    # T9：.aimake-link 消费发现指针（目标项目 ≠ 运行目录时）
    if target != cwd:
        link = target / ".aimake-link"
        rel = os.path.relpath(prefix, target)
        link.write_text(f"知识路径: {rel}\n", encoding="utf-8")
        print(f".aimake-link：{link.relative_to(cwd)} -> {rel}")

    return 0 if not failed else 1


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

    for name, help_text in _PLANNED:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=lambda a, _n=name: cmd_not_implemented(_n))

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
