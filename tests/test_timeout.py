"""闸 4：超时降级 + 失败不阻塞（子级失败不阻塞父级/并行）。"""

import tempfile
import unittest
from pathlib import Path

from aimake.engine import EngineSpec
from aimake.runner import run_engine, run_nodes


class TestTimeoutDegrade(unittest.TestCase):
    def test_timeout_raises(self):
        """超时 → 抛异常（被 runner 捕获标记失败）。"""
        engine = EngineSpec("slow", ["bash", "-c", "sleep 3"], "arg", timeout=1)
        with self.assertRaises(Exception):
            run_engine(engine, "p", Path("."))

    def test_failure_not_blocking(self):
        """并行中全部失败也正常返回（失败标记，不阻塞、不抛）。"""
        engine = EngineSpec("slow", ["bash", "-c", "sleep 3"], "arg", timeout=1)
        results = run_nodes(
            [("a", "p", Path(".")), ("b", "p", Path("."))],
            engine, concurrency=2, retries=0,
        )
        self.assertEqual(len(results), 2)
        self.assertTrue(all(not r.ok for r in results))
        self.assertTrue(all("timed out" in r.error for r in results))

    def test_parallel_success(self):
        """mock 引擎并行多节点全部成功（成功互不阻塞）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            results = run_nodes(
                [("a", "p", root), ("b", "p", root)],
                EngineSpec("mock", [], "arg", 10),
                concurrency=2, retries=0,
            )
            self.assertEqual(len(results), 2)
            self.assertTrue(all(r.ok for r in results))

    def test_retry_recovers(self):
        """重试机制：mock 引擎首次也成功（无状态），跑两次都成功。"""
        engine = EngineSpec("mock", [], "arg", 10)
        r1 = run_nodes([("x", "p", Path("."))], engine, concurrency=1, retries=2)
        r2 = run_nodes([("x", "p", Path("."))], engine, concurrency=1, retries=2)
        self.assertTrue(r1[0].ok and r2[0].ok)


if __name__ == "__main__":
    unittest.main()
