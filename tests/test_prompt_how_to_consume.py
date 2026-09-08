"""HOW TO CONSUME：根节点消费协议小节（根特有，全量/轻量档均须注入）。

期望步骤逐字独立于实现书写（spec 契约），防止测试自证。
"""

import unittest
from pathlib import Path

from aimake.engine import EngineSpec
from aimake.prompt import (
    SCHEMA_SECTIONS,
    TIER_FULL,
    TIER_LIGHT,
    NodeContext,
    build_prompt,
    build_prompt_budgeted,
    decide_tier,
)
from aimake.runner import run_engine

EXPECTED_STEPS: tuple[str, ...] = (
    "会话启动：先读根 agents.md（方向）+ 知识根 tasks.md（任务上下文）",
    "知识发现：项目根有 .aimake-link 按指针去知识根；否则按约定「项目知识在父目录 .aimake/<项目名>/」",
    "消费前：运行 aimake status 核对指纹——过期先 aimake update",
    "消费中：查询经由 owner（读 agents.md，不直接扫目录）；沿树边/依赖边/捷径表跳转；换「读」不换会话",
    "消费后：发现知识错误写事实性反馈到知识根 feedback/；任务完成更新 tasks.md",
)


def _root_ctx() -> NodeContext:
    """根节点上下文：带子目录（走全量档）。"""
    return NodeContext(
        rel=".", files=["main.py"], child_summaries=[("src", "源码目录")]
    )


class TestHowToConsumePrompt(unittest.TestCase):
    def test_schema_includes_how_to_consume(self):
        """SCHEMA_SECTIONS 收录 HOW TO CONSUME 协议键。"""
        self.assertIn("HOW TO CONSUME", SCHEMA_SECTIONS)

    def test_root_full_prompt_contains_section_and_steps(self):
        """根节点全量档：包含小节标题 + 5 步逐字步骤。"""
        prompt = build_prompt(_root_ctx(), TIER_FULL, is_root=True)
        self.assertIn("## HOW TO CONSUME", prompt)
        for step in EXPECTED_STEPS:
            self.assertIn(step, prompt)

    def test_root_light_prompt_contains_section_and_steps(self):
        """回归守卫：扁平项目根走轻量档（真实 init 路径），消费协议不得丢失。"""
        ctx = NodeContext(rel=".", files=["only.py"])
        self.assertEqual(
            decide_tier(len(ctx.files), len(ctx.child_summaries)), TIER_LIGHT
        )
        prompt = build_prompt(ctx, is_root=True)
        self.assertIn("## HOW TO CONSUME", prompt)
        for step in EXPECTED_STEPS:
            self.assertIn(step, prompt)
        # 预算降级到轻量档（step ④）同样必须保留根消费协议
        light, degraded = build_prompt_budgeted(ctx, TIER_FULL, is_root=True, budget=1)
        self.assertTrue(degraded)
        self.assertIn("## HOW TO CONSUME", light)
        for step in EXPECTED_STEPS:
            self.assertIn(step, light)

    def test_non_root_prompts_omit_section(self):
        """非根节点（全量 + 轻量）不得包含消费协议小节。"""
        full = build_prompt(_root_ctx(), TIER_FULL, is_root=False)
        light = build_prompt(
            NodeContext(rel="src", files=["a.py"]), TIER_LIGHT, is_root=False
        )
        self.assertNotIn("## HOW TO CONSUME", full)
        self.assertNotIn("## HOW TO CONSUME", light)

    def test_mock_root_output_contains_section_and_steps(self):
        """mock 根产物：含小节标题 + 5 步（无认证端到端可验证）。"""
        prompt = build_prompt(_root_ctx(), TIER_FULL, is_root=True)
        out = run_engine(EngineSpec("mock", [], "arg", 10), prompt, Path("."))
        self.assertIn("## HOW TO CONSUME", out)
        for step in EXPECTED_STEPS:
            self.assertIn(step, out)

    def test_mock_non_root_output_omits_section(self):
        """mock 非根产物：不得包含消费协议小节。"""
        prompt = build_prompt(
            NodeContext(rel="src", files=["a.py"]), TIER_LIGHT, is_root=False
        )
        out = run_engine(EngineSpec("mock", [], "arg", 10), prompt, Path("."))
        self.assertNotIn("## HOW TO CONSUME", out)


if __name__ == "__main__":
    unittest.main()
