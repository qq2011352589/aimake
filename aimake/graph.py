"""三类边知识图（T4）。

树边：目录层级（父→子，导航可双向）——图骨架；
依赖边：依赖候选名单（纯目录名，模型生成时确认后才成为 DEPENDS 契约）；
捷径边：根节点 WHERE TO LOOK（由根生成时模型写入，结构上预留给根节点）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .imports import build_dep_candidates
from .walk import WalkResult


@dataclass
class GraphNode:
    """目录知识节点（owner 的图内表示）。"""

    rel: str  # 相对知识根的 POSIX 路径（"" 为根）
    path: Path  # 绝对路径
    children: list["GraphNode"] = field(default_factory=list)  # 树边（子）
    dep_candidates: list[str] = field(default_factory=list)  # 依赖候选（纯目录名）

    @property
    def is_leaf(self) -> bool:
        return not self.children


@dataclass
class KnowledgeGraph:
    """目标项目知识图：树边为骨架，依赖/捷径边承载于节点。"""

    root: GraphNode
    nodes: dict[str, GraphNode] = field(default_factory=dict)  # rel → node

    def topo_order(self) -> list[GraphNode]:
        """后序拓扑序（子级先于父级）——生成顺序依据（两阶段生成用）。"""
        order: list[GraphNode] = []
        visited: set[str] = set()

        def visit(node: GraphNode) -> None:
            if node.rel in visited:
                return
            for child in node.children:
                visit(child)
            visited.add(node.rel)
            order.append(node)

        visit(self.root)
        return order


def build_graph(
    walk: WalkResult, dep_candidates: dict[Path, list[str]]
) -> KnowledgeGraph:
    """从遍历结果构建知识图。"""
    nodes: dict[str, GraphNode] = {}
    for d in walk.directories:
        rel = d.relative_to(walk.root).as_posix()
        if rel == ".":
            rel = ""
        nodes[rel] = GraphNode(
            rel=rel, path=d, dep_candidates=dep_candidates.get(d, [])
        )

    # 树边：rel 前缀匹配建立父子关系
    for node in nodes.values():
        if node.rel == "":
            continue
        parent_rel = node.rel.rsplit("/", 1)[0] if "/" in node.rel else ""
        parent = nodes.get(parent_rel)
        if parent is not None:
            parent.children.append(node)

    # 确定性：子节点按 rel 排序
    for node in nodes.values():
        node.children.sort(key=lambda c: c.rel)

    root = nodes.get("")
    if root is None:
        raise ValueError("知识图为空：没有可见目录")
    return KnowledgeGraph(root=root, nodes=nodes)


def build_knowledge_graph(walk: WalkResult) -> KnowledgeGraph:
    """遍历结果 → 知识图（内部完成 import 候选扫描）。"""
    dir_names = {d.name for d in walk.directories}
    candidates = build_dep_candidates(walk.files, dir_names)
    return build_graph(walk, candidates)
