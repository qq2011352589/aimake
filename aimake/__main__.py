"""aimake CLI 入口（T5：scan / init 骨架可验收，其余规划中）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine import load_engine_config, write_default_config
from .graph import build_knowledge_graph
from .prompt import TIER_LIGHT, NodeContext, build_prompt, decide_tier
from .runner import run_nodes
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


def cmd_init(args: argparse.Namespace) -> int:
    """init：知识根镜像骨架 + .meta + 叶子并行生成（父级待 T8）。"""
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
    print(f"镜像骨架目录：{len(graph.nodes)}")

    # 生成计划
    plan: list[tuple[str, str, Path, Path]] = []  # (rel, prompt, cwd, mirror)
    for node in graph.topo_order():
        mirror = prefix / node.rel if node.rel else prefix
        files = result.files.get(node.path, [])
        tier = decide_tier(len(files), len(node.children))
        ctx = NodeContext(
            rel=node.rel,
            files=files,
            dep_candidates=node.dep_candidates,
        )
        prompt = build_prompt(ctx, tier)
        plan.append((node.rel, prompt, node.path, mirror))

    if args.dry_run:
        print("\n== 生成计划（dry-run）==")
        for rel, _, _, mirror in plan:
            node = graph.nodes[rel]
            tier = decide_tier(
                len(result.files.get(node.path, [])), len(node.children)
            )
            tag = "轻量" if tier == TIER_LIGHT else "全量"
            print(f"  [{tag}] {mirror.relative_to(cwd)}/agents.md")
        return 0

    # 执行：T7 只跑叶子节点，父级标记待补
    leaves = [p for p in plan if graph.nodes[p[0]].is_leaf]
    print(f"\n== 叶子节点并行生成（{len(leaves)} 个，并发 {args.concurrency}）==")
    gen = run_nodes(
        [(rel, prompt, cwd) for rel, prompt, cwd, _ in leaves],
        engine,
        concurrency=args.concurrency,
        retries=args.retries,
    )

    # 写成功者产物
    mirror_map = {rel: mirror for rel, _, _, mirror in leaves}
    ok_count = 0
    for r in gen:
        if r.ok:
            (mirror_map[r.rel] / "agents.md").write_text(r.output, encoding="utf-8")
            ok_count += 1
    failed = [r for r in gen if not r.ok]

    print(f"成功：{ok_count} ｜ 失败：{len(failed)} ｜ 父级待补：{len(plan) - len(leaves)}")
    for r in failed:
        print(f"  [失败] {r.rel}：{r.error}")
    print("\n提示：父级节点（SUB-KNOWLEDGE 聚合）将在 T8 实现；"
          f"失败节点可用 `aimake update {args.target or '.'}` 重试（T12 前暂未实现）。")
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
