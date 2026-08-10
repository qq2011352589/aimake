"""生成引擎抽象（T7）。

aimake 的引擎接口**通用**——任意 AI CLI 工具都可经配置接入（cc 类比：
Makefile 里的 cc 可换成任意编译器）。codex exec / opencode run 只是预置项，
配置由用户决定（`.aimake/aimake.json`）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ENGINE_CONFIG_NAME = "aimake.json"  # 位于知识根 .aimake/aimake.json


@dataclass
class EngineSpec:
    """一个生成引擎的规格（完全由用户配置）。"""

    name: str
    command: list[str] = field(default_factory=list)  # 可执行 + 固定参数
    prompt_how: str = "arg"  # "arg"（提示词作末位参数）| "stdin"（标准输入）
    timeout: int = 300  # 单次调用超时（秒）


# 预置引擎（可扩展；任意 AI CLI 均可通过配置自定义）
PRESETS: dict[str, EngineSpec] = {
    "codex": EngineSpec("codex", ["codex", "exec", "--full-auto"], "arg", 300),
    "opencode": EngineSpec("opencode", ["opencode", "run"], "arg", 300),
    "mock": EngineSpec("mock", [], "arg", 30),  # 内置确定性生成器（测试/演示）
}


def resolve_engine(name: str, overrides: dict | None = None) -> EngineSpec:
    """按名字取预置；overrides 覆盖字段。非预置名构造自定义引擎。"""
    base = PRESETS.get(name)
    spec = EngineSpec(
        name=name,
        command=list(base.command) if base else [],
        prompt_how=base.prompt_how if base else "arg",
        timeout=base.timeout if base else 300,
    )
    if overrides:
        if overrides.get("command"):
            spec.command = [str(c) for c in overrides["command"]]
        if overrides.get("prompt_how"):
            spec.prompt_how = str(overrides["prompt_how"])
        if overrides.get("timeout"):
            spec.timeout = int(overrides["timeout"])
    return spec


def load_engine_config(knowledge_root: Path, name: str | None = None) -> EngineSpec:
    """引擎解析优先级：CLI --engine > .aimake/aimake.json > 默认 codex。"""
    if name:
        return resolve_engine(name)
    cfg_file = knowledge_root / ENGINE_CONFIG_NAME
    if cfg_file.is_file():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            eng = data.get("engine", {})
            if isinstance(eng, dict) and eng.get("name"):
                return resolve_engine(str(eng["name"]), eng)
        except (json.JSONDecodeError, OSError):
            pass  # 配置损坏 → 回退默认
    return PRESETS["codex"]


def load_budget(knowledge_root: Path, default: int = 20000) -> int:
    """每节点提示词预算（字符数）。CLI --budget 覆盖后由调用方传入。"""
    cfg_file = knowledge_root / ENGINE_CONFIG_NAME
    if cfg_file.is_file():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            b = data.get("budget")
            if isinstance(b, int) and b >= 0:
                return b
        except (json.JSONDecodeError, OSError):
            pass
    return default


def write_default_config(knowledge_root: Path) -> Path:
    """知识根缺失配置时写入默认（用户可自行修改——配置由用户决定）。"""
    cfg_file = knowledge_root / ENGINE_CONFIG_NAME
    if not cfg_file.exists():
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        default = {
            "engine": {"name": "codex", "prompt_how": "arg", "timeout": 300},
            "concurrency": 4,
            "retries": 2,
            "budget": 20000,  # 每节点提示词预算（字符数，超预算降级）
        }
        cfg_file.write_text(
            json.dumps(default, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return cfg_file
