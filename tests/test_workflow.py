"""结构测试：GitHub Actions 增量知识工作流。

只校验 `.github/workflows/aimake-knowledge.yml` 的触发/权限/并发/步骤语义，
不执行工作流、不调用 git。缺失文件即失败（RED）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parent.parent
    / ".github"
    / "workflows"
    / "aimake-knowledge.yml"
)

# 工作流必须包含的键/字符串（语义契约，见任务规格）。
REQUIRED_SNIPPETS = (
    "name: aimake knowledge (incremental)",
    "schedule",
    "workflow_dispatch",
    "contents: write",
    "concurrency",
    "cancel-in-progress: true",
    "timeout-minutes",
    "persist-credentials: true",
    "[skip ci]",
    "upload-artifact",
    "knowledge-v",
    "--time-budget",
    "--max-nodes",
    "--engine openai",
)


class TestWorkflowStructure(unittest.TestCase):
    """aimake-knowledge.yml 结构契约。"""

    def _text(self) -> str:
        self.assertTrue(WORKFLOW.is_file(), f"缺少工作流文件：{WORKFLOW}")
        return WORKFLOW.read_text(encoding="utf-8")

    def test_required_snippets_present(self):
        """必需键/字符串全部出现（触发、权限、并发、步骤语义）。"""
        text = self._text()
        missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in text]
        self.assertEqual(missing, [], f"工作流缺少必需字符串：{missing}")

    def test_no_tab_characters(self):
        """YAML 必须用空格缩进，禁止制表符。"""
        self.assertNotIn("\t", self._text(), "YAML 不得包含制表符")

    def test_yaml_parses(self):
        """PyYAML 可用时须能安全解析；不可用则跳过。"""
        try:
            import yaml
        except ImportError:  # pragma: no cover - 环境无 PyYAML 时
            self.skipTest("PyYAML 不可用，跳过 YAML 解析检查")
        data = yaml.safe_load(self._text())
        self.assertIsInstance(data, dict, "工作流顶层应为映射")

    def test_trigger_permissions_and_job(self):
        """解析后的触发输入默认值 / 权限 / generate 作业结构正确。"""
        try:
            import yaml
        except ImportError:  # pragma: no cover - 环境无 PyYAML 时
            self.skipTest("PyYAML 不可用，跳过 YAML 结构检查")
        data = yaml.safe_load(self._text())
        # PyYAML 1.1 把裸 `on` 解析为布尔 True，两种键都兼容。
        trigger = data.get("on", data.get(True))
        self.assertIsInstance(trigger, dict, "on 触发块应为映射")
        self.assertEqual(trigger.get("schedule"), [{"cron": "0 3 * * *"}])
        inputs = trigger.get("workflow_dispatch", {}).get("inputs", {})
        self.assertEqual(inputs.get("time_budget", {}).get("default"), "3000")
        self.assertEqual(inputs.get("max_nodes", {}).get("default"), "50")
        self.assertEqual(data.get("permissions", {}).get("contents"), "write")
        concurrency = data.get("concurrency", {})
        self.assertEqual(concurrency.get("group"), "aimake-knowledge-${{ github.ref }}")
        self.assertTrue(concurrency.get("cancel-in-progress"))
        job = data.get("jobs", {}).get("generate", {})
        self.assertEqual(job.get("runs-on"), "ubuntu-latest")
        self.assertEqual(job.get("timeout-minutes"), 90)
        self.assertGreaterEqual(len(job.get("steps", [])), 8, "至少 8 个步骤")


if __name__ == "__main__":
    unittest.main()
