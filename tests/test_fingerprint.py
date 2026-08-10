"""闸 3：指纹幂等（跑两次 = 跑一次；只有真实文件变化才触发）。"""

import tempfile
import unittest
from pathlib import Path

from aimake.meta import is_stale, read_meta, write_meta


class TestFingerprintIdempotent(unittest.TestCase):
    def test_meta_roundtrip(self):
        """写入 → 最新；改内容 → 过期；重写 → 最新（幂等）。"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.py").write_text("v1", encoding="utf-8")
            meta = d / ".meta"
            write_meta(d, ["a.py"], meta)
            self.assertFalse(is_stale(d, ["a.py"], meta), "写入后应最新")
            (d / "a.py").write_text("v2", encoding="utf-8")
            self.assertTrue(is_stale(d, ["a.py"], meta), "内容变化应过期")
            write_meta(d, ["a.py"], meta)
            self.assertFalse(is_stale(d, ["a.py"], meta), "重写后应最新（幂等）")

    def test_file_added_and_removed(self):
        """文件增删也触发过期。"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.py").write_text("a", encoding="utf-8")
            meta = d / ".meta"
            write_meta(d, ["a.py"], meta)
            self.assertFalse(is_stale(d, ["a.py"], meta))
            # 新增文件
            self.assertTrue(is_stale(d, ["a.py", "b.py"], meta))
            # 删除文件
            (d / "a.py").unlink()
            self.assertTrue(is_stale(d, [], meta))

    def test_mtime_only_change_not_stale(self):
        """仅 mtime 变化（内容 hash 不变）不算输入变化。"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = d / "a.py"
            p.write_text("a", encoding="utf-8")
            meta = d / ".meta"
            write_meta(d, ["a.py"], meta)
            import os
            import time
            old = p.stat().st_mtime
            time.sleep(0.05)
            os.utime(p, (old + 10, old + 10))  # 只改 mtime
            self.assertFalse(is_stale(d, ["a.py"], meta))

    def test_read_meta_format(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.py").write_text("a", encoding="utf-8")
            meta = d / ".meta"
            write_meta(d, ["a.py"], meta)
            data = read_meta(meta)
            self.assertIn("a.py", data)
            self.assertEqual(len(data["a.py"]), 12)


if __name__ == "__main__":
    unittest.main()
