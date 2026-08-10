"""aimake CLI 入口（T3：scan 子命令可验收，其余规划中）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .walk import walk_project

_PLANNED: tuple[tuple[str, str], ...] = (
    ("init", "全树生成 .aimake 知识树（规划中）"),
    ("update", "指纹驱动更新（规划中）"),
    ("status", "过期清单/反馈队列/符号自检（规划中）"),
    ("tree", "知识树总览（规划中）"),
    ("ask", "QA 问答（规划中）"),
    ("scaffold", "从描述生成项目（规划中）"),
)


def cmd_scan(args: argparse.Namespace) -> int:
    """扫描可见目录树，验证 ignore 规则生效。"""
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"错误：不是目录：{root}", file=sys.stderr)
        return 1
    result = walk_project(root)
    print(result.tree_text())
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
    p_scan.set_defaults(func=cmd_scan)

    for name, help_text in _PLANNED:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=lambda a, _n=name: cmd_not_implemented(_n))

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
