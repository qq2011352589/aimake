"""CLI 端到端：mock init 产物含根消费协议（全量根 + 轻量根），status/tree 可用。

期望步骤逐字独立于实现书写（spec 契约），防止测试自证。
"""

import os
import tempfile
import unittest
from pathlib import Path

from aimake.__main__ import main

EXPECTED_STEPS: tuple[str, ...] = (
    "会话启动：先读根 agents.md（方向）+ 知识根 tasks.md（任务上下文）",
    "知识发现：项目根有 .aimake-link 按指针去知识根；否则按约定「项目知识在父目录 .aimake/<项目名>/」",
    "消费前：运行 aimake status 核对指纹——过期先 aimake update",
    "消费中：查询经由 owner（读 agents.md，不直接扫目录）；沿树边/依赖边/捷径表跳转；换「读」不换会话",
    "消费后：发现知识错误写事实性反馈到知识根 feedback/；任务完成更新 tasks.md",
)


class TestCliHowToConsume(unittest.TestCase):
    def _init_root_md(self, files: dict[str, str]) -> str:
        """临时目录内创建 proj 并 mock init，返回根 agents.md 文本。"""
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                os.chdir(td)
                proj = Path(td) / "proj"
                for rel, body in files.items():
                    p = proj / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(body, encoding="utf-8")
                code = main(["init", "proj", "--engine", "mock", "--concurrency", "1"])
                self.assertEqual(code, 0, "mock init 应成功")
                md = Path(td) / ".aimake" / "proj" / "agents.md"
                self.assertTrue(md.is_file(), "根 agents.md 应落盘")
                return md.read_text(encoding="utf-8")
            finally:
                os.chdir(old)

    def test_nested_project_root_agents_md_contains_section(self):
        """嵌套项目（根为全量档）：init 产物根 agents.md 含消费协议 5 步。"""
        text = self._init_root_md(
            {"README.md": "# proj\n", "src/a.py": "x = 1\n"}
        )
        self.assertIn("## HOW TO CONSUME", text)
        for step in EXPECTED_STEPS:
            self.assertIn(step, text)

    def test_flat_project_light_root_contains_section(self):
        """扁平项目（单文件无子目录 → 轻量根）：降级不得丢失消费协议。"""
        text = self._init_root_md({"only.py": "x = 1\n"})
        self.assertIn("## HOW TO CONSUME", text)
        for step in EXPECTED_STEPS:
            self.assertIn(step, text)

    def test_status_and_tree_return_zero_after_init(self):
        """init 后 status/tree 均返回 0（消费命令可读取产物）。"""
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                os.chdir(td)
                proj = Path(td) / "proj"
                (proj / "src").mkdir(parents=True)
                (proj / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
                self.assertEqual(
                    main(["init", "proj", "--engine", "mock", "--concurrency", "1"]),
                    0,
                )
                self.assertEqual(main(["status", "proj"]), 0)
                self.assertEqual(main(["tree", "proj"]), 0)
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
