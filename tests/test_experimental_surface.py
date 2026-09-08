"""实验入口测试：冻结实验命令的可用面（帮助 / 子进程 / update 引导）。"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aimake.experimental.__main__ import main as experimental_main

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestExperimentalSurface(unittest.TestCase):
    def test_help_lists_six_experimental_commands(self):
        """in-process --help 捕获：scan/update/ask/scaffold/maintain/ignore 全部在列。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                experimental_main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        out = buf.getvalue()
        for name in ("scan", "update", "ask", "scaffold", "maintain", "ignore"):
            self.assertIn(name, out, f"帮助应列出实验命令：{name}")

    def test_module_scan_runs_via_subprocess(self):
        """python -m aimake.experimental scan <tmp> 子进程返回 0。"""
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, "-m", "aimake.experimental", "scan", td],
                env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_update_without_feedback_prints_guidance(self):
        """update 无 --feedback：打印引导（核心指纹更新 / 实验反馈入口）并返回 1。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = experimental_main(["update"])
        self.assertEqual(rc, 1)
        out = buf.getvalue()
        self.assertIn("aimake update", out)
        self.assertIn("python -m aimake.experimental update --feedback", out)


if __name__ == "__main__":
    unittest.main()
