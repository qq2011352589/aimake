"""ignore 规则集中管理（T3）。

默认排除项 + 项目根 .aimakeignore 文件（.gitignore 风格，每行一个模式）。
匹配规则：模式匹配任意深度的路径段（精确名或 fnmatch 通配，如 *.pyc）。
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

# 设计既定默认排除项（见 AGENTS.md「生成规则 · 可见性」）
# .omo：opencode 内部会话目录（非项目知识）；其余为版本/构建/缓存噪音
DEFAULT_IGNORES: tuple[str, ...] = (
    ".git",
    ".omo",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".aimake",
)

IGNORE_FILE = ".aimakeignore"


def load_ignore_patterns(project_root: Path, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    """合并默认规则、.aimakeignore 文件与调用方附加规则。"""
    patterns: list[str] = list(DEFAULT_IGNORES)
    ignore_file = project_root / IGNORE_FILE
    if ignore_file.is_file():
        for raw in ignore_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip().rstrip("/")
            if line and not line.startswith("#"):
                patterns.append(line)
    patterns.extend(extra)
    return tuple(patterns)


def is_ignored(relative_posix: str, patterns: tuple[str, ...]) -> bool:
    """判断相对路径（POSIX 风格，如 "src/foo.py"）是否被忽略。

    任意深度的路径段命中即忽略：段名精确相等或 fnmatch 通配匹配。
    """
    segments = [s for s in relative_posix.split("/") if s]
    if not segments:
        return False
    for pattern in patterns:
        if not pattern:
            continue
        for seg in segments:
            if seg == pattern or fnmatch.fnmatch(seg, pattern):
                return True
    return False
