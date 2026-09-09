"""生成引擎抽象（T7）。

aimake 的引擎接口**通用**——任意 AI CLI 工具都可经配置接入（cc 类比：
Makefile 里的 cc 可换成任意编译器）。codex exec / opencode run 只是预置项，
配置由用户决定（`.aimake/aimake.json`）。
"""

from __future__ import annotations

import json
import os
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
    # —— openai 引擎专用（HTTP，无子进程）——
    base_url: str = ""  # OpenAI 兼容端点，如 https://api.deepseek.com/v1
    model: str = ""  # 模型名
    api_key_env: str = "AIMAKE_OPENAI_API_KEY"  # 读取密钥的环境变量名
    max_tokens: int = 4096
    max_tool_rounds: int = 8  # grep 工具调用最大轮次


# 预置引擎（可扩展；任意 AI CLI 均可通过配置自定义）
PRESETS: dict[str, EngineSpec] = {
    "codex": EngineSpec("codex", ["codex", "exec", "--full-auto"], "arg", 300),
    "opencode": EngineSpec("opencode", ["opencode", "run"], "arg", 300),
    "mock": EngineSpec("mock", [], "arg", 30),  # 内置确定性生成器（测试/演示）
    # openai：纯标准库 HTTP 引擎（仅 grep 工具），base_url/model 由配置/环境变量提供
    "openai": EngineSpec("openai", [], "arg", 300),
}


def resolve_engine(name: str, overrides: dict | None = None) -> EngineSpec:
    """按名字取预置；overrides 覆盖字段。非预置名构造自定义引擎。

    字段优先级（低→高）：预置默认 < overrides（配置）< AIMAKE_OPENAI_* 环境变量。
    """
    base = PRESETS.get(name)
    spec = EngineSpec(
        name=name,
        command=list(base.command) if base else [],
        prompt_how=base.prompt_how if base else "arg",
        timeout=base.timeout if base else 300,
        base_url=base.base_url if base else "",
        model=base.model if base else "",
        api_key_env=base.api_key_env if base else "AIMAKE_OPENAI_API_KEY",
        max_tokens=base.max_tokens if base else 4096,
        max_tool_rounds=base.max_tool_rounds if base else 8,
    )
    if overrides:
        if overrides.get("command"):
            spec.command = [str(c) for c in overrides["command"]]
        if overrides.get("prompt_how"):
            spec.prompt_how = str(overrides["prompt_how"])
        if overrides.get("timeout"):
            spec.timeout = int(overrides["timeout"])
        if overrides.get("base_url"):
            spec.base_url = str(overrides["base_url"])
        if overrides.get("model"):
            spec.model = str(overrides["model"])
        if overrides.get("api_key_env"):
            spec.api_key_env = str(overrides["api_key_env"])
        if overrides.get("max_tokens"):
            spec.max_tokens = int(overrides["max_tokens"])
        if overrides.get("max_tool_rounds") is not None:
            spec.max_tool_rounds = int(overrides["max_tool_rounds"])
    # 环境变量最高优先级（便于 CI 注入，不落盘）
    if os.environ.get("AIMAKE_OPENAI_BASE_URL"):
        spec.base_url = os.environ["AIMAKE_OPENAI_BASE_URL"]
    if os.environ.get("AIMAKE_OPENAI_MODEL"):
        spec.model = os.environ["AIMAKE_OPENAI_MODEL"]
    env_max = os.environ.get("AIMAKE_OPENAI_MAX_TOKENS", "")
    if env_max.isdigit() and int(env_max) > 0:
        spec.max_tokens = int(env_max)
    return spec


def load_engine_config(knowledge_root: Path, name: str | None = None) -> EngineSpec:
    """引擎解析优先级：CLI --engine > .aimake/aimake.json > 默认 codex。

    TRAP-1 修复：CLI 指定 name 时，配置里的**字段**仍合并（否则 `--engine openai`
    会丢掉 base_url/model）。但 command 与引擎名绑定——配置 name 与 CLI name
    不一致时丢弃配置 command，避免用 codex 的命令去跑 openai。
    """
    cfg_engine: dict = {}
    cfg_file = knowledge_root / ENGINE_CONFIG_NAME
    if cfg_file.is_file():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            eng = data.get("engine", {})
            if isinstance(eng, dict):
                cfg_engine = eng
        except (json.JSONDecodeError, OSError):
            cfg_engine = {}  # 配置损坏 → 回退默认
    if name:
        overrides = dict(cfg_engine)
        if cfg_engine.get("name") != name:
            # command 与引擎名绑定：配置名缺失或不等于 CLI 名时一律丢弃，
            # 避免把 codex 的命令套到 openai/opencode 上。
            overrides.pop("command", None)
        return resolve_engine(name, overrides)
    if cfg_engine.get("name"):
        return resolve_engine(str(cfg_engine["name"]), cfg_engine)
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
