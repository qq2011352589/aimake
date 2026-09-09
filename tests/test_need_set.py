"""need-set 助手单元测试：过期 / 缺失 / 受影响子图（init-resume 复用）。"""

import tempfile
import unittest
from pathlib import Path

from aimake.__main__ import _affected_subgraph, _missing_nodes, _stale_nodes
from aimake.graph import build_knowledge_graph
from aimake.meta import write_meta
from aimake.walk import walk_project


def _build_tree(root: Path) -> None:
    """合成项目：src --import lib--> lib，另有 misc（无依赖边）。"""
    (root / "src").mkdir()
    (root / "lib").mkdir()
    (root / "misc").mkdir()
    (root / "readme.txt").write_text("root\n", encoding="utf-8")
    (root / "src" / "app.py").write_text("import lib\n", encoding="utf-8")
    (root / "lib" / "util.py").write_text(
        "def helper():\n    pass\n", encoding="utf-8"
    )
    (root / "misc" / "note.txt").write_text("note\n", encoding="utf-8")


class NeedSetFixture(unittest.TestCase):
    """每个用例：独立临时项目 + 已建好的知识图 + 独立知识根镜像。"""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        base = Path(self._td.name)
        self.root = base / "proj"
        self.root.mkdir()
        _build_tree(self.root)
        self.result = walk_project(self.root)
        self.graph = build_knowledge_graph(self.result)
        self.prefix = base / ".aimake"

    def tearDown(self) -> None:
        self._td.cleanup()

    def _write_all_metas(self) -> None:
        for rel, node in self.graph.nodes.items():
            meta = self.prefix / rel / ".meta" if rel else self.prefix / ".meta"
            write_meta(node.path, self.result.files.get(node.path, []), meta)


class TestMissingNodes(NeedSetFixture):
    def test_lists_only_nodes_without_agents_md(self):
        """Given 根与 src 已生成，When 扫描缺失，Then 仅 lib/misc（排序）。"""
        (self.prefix / "src").mkdir(parents=True)
        (self.prefix / "agents.md").write_text("根\n", encoding="utf-8")
        (self.prefix / "src" / "agents.md").write_text("src\n", encoding="utf-8")

        missing = _missing_nodes(self.graph, self.prefix)

        self.assertEqual(missing, ["lib", "misc"])

    def test_empty_agents_md_counts_as_missing(self):
        """Given src 的 agents.md 为 0 字节，When 扫描缺失，Then src 仍算缺失（需重生成）。"""
        (self.prefix / "src").mkdir(parents=True)
        (self.prefix / "agents.md").write_text("根\n", encoding="utf-8")
        (self.prefix / "src" / "agents.md").write_text("", encoding="utf-8")

        missing = _missing_nodes(self.graph, self.prefix)

        self.assertIn("src", missing)
        self.assertNotIn("", missing)

    def test_all_missing_when_skeleton_empty(self):
        """Given 骨架为空，When 扫描，Then 全部节点（含根 ""）缺失且排序。"""
        missing = _missing_nodes(self.graph, self.prefix)

        self.assertEqual(missing, ["", "lib", "misc", "src"])


class TestAffectedSubgraph(NeedSetFixture):
    def test_includes_ancestors_and_depends_consumers(self):
        """Given src 依赖 lib，When 种子=lib，Then 含 lib+根祖先+src 消费者。"""
        self.assertIn(
            "lib",
            self.graph.nodes["src"].dep_candidates,
            "fixture 应产生 src→lib 依赖候选",
        )

        affected = _affected_subgraph(self.graph, ["lib"])

        self.assertEqual(affected, {"", "lib", "src"})

    def test_seed_only_when_no_edges(self):
        """Given misc 无依赖边，When 种子=misc，Then 仅 misc+根祖先。"""
        self.assertEqual(_affected_subgraph(self.graph, ["misc"]), {"", "misc"})

    def test_root_seed_yields_root_only(self):
        """Given 种子=根，When 计算，Then 仅根（根无祖先、无消费者）。"""
        self.assertEqual(_affected_subgraph(self.graph, [""]), {""})

    def test_empty_seed_yields_empty_set(self):
        """Given 空种子，When 计算，Then 空集。"""
        self.assertEqual(_affected_subgraph(self.graph, []), set())


class TestStaleNodes(NeedSetFixture):
    def test_detects_only_changed_file(self):
        """Given 全部指纹最新，When 改 src/app.py，Then 仅 src 过期。"""
        self._write_all_metas()
        self.assertEqual(_stale_nodes(self.graph, self.result, self.prefix), [])

        (self.root / "src" / "app.py").write_text(
            "import lib  # changed\n", encoding="utf-8"
        )

        self.assertEqual(_stale_nodes(self.graph, self.result, self.prefix), ["src"])

    def test_missing_meta_marks_stale(self):
        """Given 无任何 .meta，When 扫描，Then 含文件的目录全过期且排序。"""
        stale = _stale_nodes(self.graph, self.result, self.prefix)

        self.assertEqual(stale, ["", "lib", "misc", "src"])


if __name__ == "__main__":
    unittest.main()
