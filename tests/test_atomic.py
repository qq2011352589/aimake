"""原子写：同目录 mkstemp → 写 → os.replace；失败无残留、目标不被破坏。"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aimake.atomic import atomic_write_text
from aimake.meta import file_hash, read_meta, write_meta


class TestAtomicWrite(unittest.TestCase):
    def test_replaces_atomically(self):
        """写入 → 内容被原子替换为新值。"""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.txt"
            atomic_write_text(target, "v1")
            self.assertEqual(target.read_text(encoding="utf-8"), "v1")
            atomic_write_text(target, "v2")
            self.assertEqual(target.read_text(encoding="utf-8"), "v2")

    def test_no_partial_on_failure(self):
        """os.replace 失败 → 目标不变、目录无 *.tmp 残留。"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            target = d / "out.txt"
            atomic_write_text(target, "original")
            with mock.patch("aimake.atomic.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "new-value")
            self.assertEqual(target.read_text(encoding="utf-8"), "original")
            self.assertEqual(list(d.glob("*.tmp")), [], "不应残留临时文件")

    def test_write_meta_atomic(self):
        """write_meta 仍产出精确 `<name> <hash>` 行，read_meta 可回读。"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.py").write_text("hello", encoding="utf-8")
            meta = d / ".meta"
            write_meta(d, ["a.py"], meta)
            digest = file_hash(d / "a.py")
            content = meta.read_text(encoding="utf-8")
            self.assertIn(f"a.py {digest}", content)
            self.assertEqual(read_meta(meta), {"a.py": digest})


if __name__ == "__main__":
    unittest.main()
