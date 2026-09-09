"""引擎配置：openai 字段 + `--engine` 仍合并 config 字段（TRAP-1 回归）。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from aimake.engine import PRESETS, EngineSpec, load_engine_config


class TestEngineFields(unittest.TestCase):
    def test_openai_preset_and_fields(self):
        """openai 预置存在，且 EngineSpec 具备 HTTP 字段。"""
        spec = PRESETS["openai"]
        self.assertEqual(spec.name, "openai")
        self.assertEqual(spec.command, [])
        self.assertEqual(spec.api_key_env, "AIMAKE_OPENAI_API_KEY")
        self.assertEqual(spec.max_tool_rounds, 8)

    def test_positional_construction_still_works(self):
        """新增字段有默认值，旧的位置构造不破。"""
        spec = EngineSpec("slow", ["x"], "arg", 1)
        self.assertEqual(spec.timeout, 1)
        self.assertEqual(spec.base_url, "")
        self.assertEqual(spec.max_tokens, 4096)


class TestEngineConfigMerge(unittest.TestCase):
    def _write_cfg(self, root: Path, engine: dict) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "aimake.json").write_text(
            json.dumps({"engine": engine}, ensure_ascii=False), encoding="utf-8"
        )

    def test_cli_engine_merges_config_fields(self):
        """TRAP-1：CLI 指定 openai 时，config 的 base_url/model/timeout 仍生效；command 不串。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".aimake"
            self._write_cfg(root, {
                "name": "codex", "base_url": "http://x", "model": "m",
                "timeout": 42, "command": ["codex"],
            })
            spec = load_engine_config(root, "openai")
            self.assertEqual(spec.name, "openai")
            self.assertEqual(spec.base_url, "http://x")
            self.assertEqual(spec.model, "m")
            self.assertEqual(spec.timeout, 42)
            self.assertEqual(spec.command, [])  # 配置 name≠CLI name → command 不套用

    def test_config_name_used_when_no_cli(self):
        """无 CLI name 时，用 config 里的 name 与字段。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".aimake"
            self._write_cfg(root, {"name": "openai", "base_url": "http://y", "model": "m2"})
            spec = load_engine_config(root, None)
            self.assertEqual(spec.name, "openai")
            self.assertEqual(spec.base_url, "http://y")
            self.assertEqual(spec.model, "m2")

    def test_default_codex_unchanged(self):
        """无配置时回退 codex 预置，行为不变。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".aimake"
            spec = load_engine_config(root, None)
            self.assertEqual(spec.name, "codex")
            self.assertEqual(spec.command, ["codex", "exec", "--full-auto"])

    def test_env_overlay_wins(self):
        """环境变量 AIMAKE_OPENAI_* 覆盖 config。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".aimake"
            self._write_cfg(root, {"name": "openai", "base_url": "http://file", "model": "filem"})
            os.environ["AIMAKE_OPENAI_BASE_URL"] = "http://env"
            os.environ["AIMAKE_OPENAI_MODEL"] = "envm"
            try:
                spec = load_engine_config(root, "openai")
            finally:
                os.environ.pop("AIMAKE_OPENAI_BASE_URL", None)
                os.environ.pop("AIMAKE_OPENAI_MODEL", None)
            self.assertEqual(spec.base_url, "http://env")
            self.assertEqual(spec.model, "envm")

    def test_env_max_tokens_overlay(self):
        """AIMAKE_OPENAI_MAX_TOKENS 可覆盖（推理模型需更大预算）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".aimake"
            os.environ["AIMAKE_OPENAI_MAX_TOKENS"] = "16384"
            try:
                spec = load_engine_config(root, "openai")
            finally:
                os.environ.pop("AIMAKE_OPENAI_MAX_TOKENS", None)
            self.assertEqual(spec.max_tokens, 16384)


if __name__ == "__main__":
    unittest.main()
