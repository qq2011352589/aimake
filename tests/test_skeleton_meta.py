"""TRAP-2：create_skeleton 不得覆盖已存在的 .meta（保留过期信号）。"""

import tempfile
import unittest
from pathlib import Path

from aimake.meta import META_NAME, read_meta
from aimake.skeleton import create_skeleton
from aimake.walk import walk_project


class TestSkeletonMetaPreservation(unittest.TestCase):
    def _setup(self, td: str) -> tuple[Path, Path, Path]:
        """建目标项目 + 知识根，返回 (knowledge_root, target, walk)。"""
        cwd = Path(td)
        target = cwd / "proj"
        (target / "src").mkdir(parents=True)
        (target / "src" / "a.py").write_text("a", encoding="utf-8")
        (target / "README.md").write_text("r", encoding="utf-8")
        knowledge_root = cwd / ".aimake"
        return knowledge_root, target, walk_project(target)

    def test_existing_meta_preserved(self):
        """第二次 create_skeleton 不得覆盖已存在的 .meta。"""
        with tempfile.TemporaryDirectory() as td:
            knowledge_root, target, walk = self._setup(td)
            create_skeleton(knowledge_root, target, Path(td), walk)
            meta = knowledge_root / "proj" / "src" / META_NAME
            self.assertTrue(meta.is_file(), "首次应创建 .meta")
            sentinel = "# 哨兵：保留过期信号\n"
            meta.write_text(sentinel, encoding="utf-8")

            create_skeleton(knowledge_root, target, Path(td), walk)

            self.assertEqual(
                meta.read_text(encoding="utf-8"),
                sentinel,
                "已存在的 .meta 不得被覆盖（销毁过期信号）",
            )

    def test_absent_meta_created(self):
        """缺失的 .meta 应被重新创建且内容有效。"""
        with tempfile.TemporaryDirectory() as td:
            knowledge_root, target, walk = self._setup(td)
            create_skeleton(knowledge_root, target, Path(td), walk)
            meta = knowledge_root / "proj" / "src" / META_NAME
            meta.unlink()

            create_skeleton(knowledge_root, target, Path(td), walk)

            self.assertTrue(meta.is_file(), "缺失的 .meta 应被重建")
            data = read_meta(meta)
            self.assertIn("a.py", data)
            self.assertEqual(len(data["a.py"]), 12)


if __name__ == "__main__":
    unittest.main()
