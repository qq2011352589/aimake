"""闸 1：.aimake 双向排除（被写入永不算输入变化）。"""

import tempfile
import unittest
from pathlib import Path

from aimake.config import DEFAULT_IGNORES
from aimake.walk import walk_project


class TestBidirectionalExclusion(unittest.TestCase):
    def test_default_ignores_excluded(self):
        """默认 6 项排除全部不进入可见目录树。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in DEFAULT_IGNORES:
                (root / name).mkdir()
                (root / name / "x.txt").write_text("x", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("a", encoding="utf-8")
            walk = walk_project(root)
            names = {d.name for d in walk.directories}
            for name in DEFAULT_IGNORES:
                self.assertNotIn(name, names, f"{name} 应被排除")
            self.assertIn("src", names)
            self.assertIn("a.py", walk.files[root / "src"])

    def test_meta_writes_never_reflow(self):
        """写入 .aimake 后再次遍历，可见树不变（自触发风暴被焊死）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("a", encoding="utf-8")
            w1 = walk_project(root)
            # 模拟 aimake 写入产物
            (root / ".aimake").mkdir()
            (root / ".aimake" / "agents.md").write_text("x", encoding="utf-8")
            (root / ".aimake" / "src").mkdir()
            (root / ".aimake" / "src" / "agents.md").write_text("y", encoding="utf-8")
            w2 = walk_project(root)
            self.assertEqual(
                [d.name for d in w1.directories],
                [d.name for d in w2.directories],
                ".aimake 写入不应回流为输入变化",
            )


if __name__ == "__main__":
    unittest.main()
