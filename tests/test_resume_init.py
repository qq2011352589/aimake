"""init 断点续跑与预算上限（R1/R2/R2b/R3 + 时间预算）。

全部走 in-process `main([...])` + os.chdir（与 test_cli_how_to_consume 同款），
`--engine mock --concurrency 1` 保证确定性。
"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from aimake.__main__ import main

# 合成项目：7 个知识节点（根 + 6 目录），无 import 依赖边
_TREE: dict[str, str] = {
    "README.md": "# proj\n",
    "pkg/__init__.py": "",
    "pkg/core/c.py": "x = 1\n",
    "pkg/util/u.py": "y = 2\n",
    "api/v1/h.py": "z = 3\n",
    "tests/t.py": "t = 4\n",
}
_EXPECTED_NODES: tuple[str, ...] = (
    "", "api", "api/v1", "pkg", "pkg/core", "pkg/util", "tests",
)


class ResumeInitFixture(unittest.TestCase):
    """每个用例：独立临时工作区 + 已铺好的目标项目 proj。"""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.base = Path(self._td.name)
        self.proj = self.base / "proj"
        for rel, body in _TREE.items():
            p = self.proj / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")

    def tearDown(self) -> None:
        self._td.cleanup()

    def _run(self, *argv: str) -> tuple[int, str]:
        """在临时工作区内 in-process 调用 main，返回 (rc, stdout)。"""
        old = os.getcwd()
        buf = io.StringIO()
        try:
            os.chdir(self.base)
            with redirect_stdout(buf):
                try:
                    rc = main(list(argv))
                except SystemExit as exc:  # argparse 未知参数 → 2，转为断言失败
                    rc = int(exc.code or 0)
        finally:
            os.chdir(old)
        return rc, buf.getvalue()

    def _md(self, rel: str) -> Path:
        prefix = self.base / ".aimake" / "proj"
        return prefix / rel / "agents.md" if rel else prefix / "agents.md"

    def _existing_mds(self) -> list[Path]:
        return sorted((self.base / ".aimake").rglob("agents.md"))

    def _all_mtimes(self) -> dict[str, int]:
        return {rel: self._md(rel).stat().st_mtime_ns for rel in _EXPECTED_NODES}


class TestResumeInit(ResumeInitFixture):
    def test_max_nodes_then_resume(self):
        """R1：--max-nodes 2 首跑仅 2 个产物，二跑补全，三跑 no-op。"""
        rc1, _ = self._run(
            "init", "proj", "--engine", "mock", "--max-nodes", "2",
            "--concurrency", "1",
        )
        self.assertEqual(rc1, 0, "预算暂停应干净退出 0")
        first = [rel for rel in _EXPECTED_NODES if self._md(rel).is_file()]
        self.assertEqual(len(first), 2, f"首跑应恰好 2 个产物，实际 {first}")

        rc2, _ = self._run("init", "proj", "--engine", "mock", "--concurrency", "1")
        self.assertEqual(rc2, 0, "续跑应成功")
        for rel in _EXPECTED_NODES:
            self.assertTrue(
                self._md(rel).is_file(), f"{rel or '根'} 的 agents.md 应补全"
            )

        before = self._all_mtimes()
        rc3, out3 = self._run("init", "proj", "--engine", "mock", "--concurrency", "1")
        self.assertEqual(rc3, 0, "已最新时重跑应成功")
        self.assertEqual(before, self._all_mtimes(), "三跑应为 no-op（mtime 不变）")
        self.assertIn("全部最新", out3)

    def test_budget_stop_no_truncation(self):
        """R2：--max-nodes 1 后无 .tmp 残留，产物非空且格式完好。"""
        rc, _ = self._run(
            "init", "proj", "--engine", "mock", "--max-nodes", "1",
            "--concurrency", "1",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(
            list((self.base / ".aimake").rglob("*.tmp")), [], "不得残留临时文件"
        )
        mds = self._existing_mds()
        self.assertEqual(len(mds), 1, f"应恰好 1 个产物，实际 {mds}")
        for md in mds:
            text = md.read_text(encoding="utf-8")
            self.assertTrue(text.strip(), "agents.md 不得为空")
            self.assertTrue(text.startswith("# agents.md"), "agents.md 应格式完好")

    def test_stale_meta_regenerated_on_resume(self):
        """R2b（TRAP-2）：.meta 仍匹配但 agents.md 被删 → 续跑必须重生成。"""
        rc, _ = self._run("init", "proj", "--engine", "mock", "--concurrency", "1")
        self.assertEqual(rc, 0)
        victim = self._md("pkg/core")
        meta = self.base / ".aimake" / "proj" / "pkg" / "core" / ".meta"
        self.assertTrue(victim.is_file())
        self.assertTrue(meta.is_file(), "TRAP-2 前提：.meta 存在且指纹匹配")
        victim.unlink()
        self.assertFalse(victim.exists())

        rc2, _ = self._run("init", "proj", "--engine", "mock", "--concurrency", "1")
        self.assertEqual(rc2, 0)
        self.assertTrue(
            victim.is_file(), "缺失的 agents.md 即使 .meta 匹配也必须重生成"
        )
        self.assertIn("# agents.md", victim.read_text(encoding="utf-8"))

    def test_full_init_unchanged_without_flags(self):
        """R3：无预算参数时全树生成，rc 0（回归保护）。"""
        rc, _ = self._run("init", "proj", "--engine", "mock")
        self.assertEqual(rc, 0)
        for rel in _EXPECTED_NODES:
            self.assertTrue(
                self._md(rel).is_file(), f"{rel or '根'} 的 agents.md 应生成"
            )

    def test_time_budget_stops_cleanly(self):
        """--time-budget 0：立即暂停，rc 0，零产物、零 .tmp、无异常。"""
        rc, _ = self._run(
            "init", "proj", "--engine", "mock", "--time-budget", "0",
            "--concurrency", "1",
        )
        self.assertEqual(rc, 0, "时间预算暂停应干净退出 0")
        self.assertEqual(self._existing_mds(), [], "预算 0 应立即暂停，不生成节点")
        self.assertEqual(
            list((self.base / ".aimake").rglob("*.tmp")), [], "不得残留临时文件"
        )


if __name__ == "__main__":
    unittest.main()
