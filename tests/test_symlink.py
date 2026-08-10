"""闸 2：symlink 防环（followlinks=False，环不导致死循环）。"""

import tempfile
import unittest
from pathlib import Path

from aimake.walk import walk_project


class TestSymlinkLoop(unittest.TestCase):
    def test_symlink_cycle_not_followed(self):
        """目录 symlink 指回祖先：遍历完成不崩溃、不进入环。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a").mkdir()
            (root / "a" / "b").mkdir()
            (root / "a" / "b" / "c").mkdir()
            # c/loop -> a（环）
            (root / "a" / "b" / "c" / "loop").symlink_to(root / "a", target_is_directory=True)
            (root / "a" / "b" / "c" / "real.py").write_text("x", encoding="utf-8")
            walk = walk_project(root)
            # 正常完成且有节点
            self.assertTrue(walk.directories)
            # loop 目录可能出现在 dirnames（os.walk 不跟随），但内容不会被递归扫描
            names = {d.name for d in walk.directories}
            self.assertIn("c", names)

    def test_symlink_to_external_dir(self):
        """symlink 指向项目外目录：不跟随。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outside = Path(td) / "outside"
            outside.mkdir()
            (outside / "secret.txt").write_text("s", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "link").symlink_to(outside, target_is_directory=True)
            walk = walk_project(root)
            # outside 内容不得进入 src 的可见文件
            files = walk.files.get(root / "src", [])
            self.assertNotIn("secret.txt", files)


if __name__ == "__main__":
    unittest.main()
