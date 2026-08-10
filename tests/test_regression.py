"""回归测试：反馈 round-trip（根归一化）+ 符号自检表格格式。"""

import tempfile
import unittest
from pathlib import Path

from aimake.__main__ import _symbol_selfcheck
from aimake.feedback import FeedbackEntry, parse_feedback, write_feedback
from aimake.graph import build_knowledge_graph
from aimake.walk import walk_project


class TestFeedbackRootRoundTrip(unittest.TestCase):
    def test_root_target_normalized(self):
        """写入端 '根' → 解析端归一化为 ''（与 node_plan 键一致，防 KeyError）。"""
        with tempfile.TemporaryDirectory() as td:
            kr = Path(td)
            p = write_feedback(
                kr, "", "消费者",
                [FeedbackEntry(source="QA", error="错", evidence="证")],
                "2026-08-10",
            )
            fb = parse_feedback(p)
            self.assertEqual(fb.target, "", "根节点反馈 target 应为空串")

    def test_subdir_target_kept(self):
        with tempfile.TemporaryDirectory() as td:
            kr = Path(td)
            p = write_feedback(
                kr, "src/core", "owner",
                [FeedbackEntry(source="KEY SYMBOLS", error="过期", evidence="源码已删")],
                "2026-08-10",
            )
            fb = parse_feedback(p)
            self.assertEqual(fb.target, "src/core")


class TestSymbolSelfcheckTable(unittest.TestCase):
    def test_table_separator_not_flagged(self):
        """KEY SYMBOLS 为 markdown 表格：表头/分隔行不误报，真失效仍检出。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            (root / "src" / "api.py").write_text(
                "def compute():\n    pass\n", encoding="utf-8"
            )
            (root / ".aimake").mkdir()
            (root / ".aimake" / "src").mkdir()
            (root / ".aimake" / "src" / "agents.md").write_text(
                "# agents.md — src\n## KEY SYMBOLS\n"
                "| 符号 | 位置 | 作用 |\n"
                "|------|------|------|\n"
                "| compute | api.py:1 | 计算 |\n"
                "| ghost | api.py:99 | 幽灵 |\n",
                encoding="utf-8",
            )
            walk = walk_project(root)
            graph = build_knowledge_graph(walk)
            issues = _symbol_selfcheck(graph, walk, root / ".aimake")
            flagged = {item for _, _, item in issues}
            self.assertNotIn("compute", flagged, "存在的符号不误报")
            self.assertIn("ghost", flagged, "失效符号仍检出")
            self.assertFalse(
                any("|------" in i for i in flagged), "表格分隔行不误报"
            )


if __name__ == "__main__":
    unittest.main()
