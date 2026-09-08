"""核心 CLI 表面测试：收敛为四灵魂命令（init / update / status / tree）。"""

import contextlib
import io
import unittest

from aimake.__main__ import main


class TestCliSurface(unittest.TestCase):
    def test_core_help_lists_exactly_soul_commands(self):
        """核心 --help 只列 init/update/status/tree；实验命令不在核心入口。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        out = buf.getvalue()
        for name in ("init", "update", "status", "tree"):
            self.assertIn(name, out, f"帮助应列出核心命令：{name}")
        for name in ("scan", "ask", "scaffold", "maintain", "ignore"):
            self.assertNotIn(name, out, f"实验命令不应出现在核心帮助：{name}")

    def test_update_feedback_rejected(self):
        """核心 update 不再接受 --feedback（实验入口专属），argparse 以 2 退出。"""
        with self.assertRaises(SystemExit) as cm:
            main(["update", "--feedback"])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
