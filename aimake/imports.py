"""import 静态扫描（T4）。

只产**依赖候选名单**（纯目录名列表，提升召回，不携带任何知识内容）——
最终 DEPENDS 由模型生成时确认（见 AGENTS.md「生成规则 · 依赖发现」）。
"""

from __future__ import annotations

import re
from pathlib import Path

# 单文件扫描大小上限（避免把超大/二进制文件读进内存）
_MAX_FILE_BYTES = 512 * 1024

# 各语言 import 提取模式（够用即可，不追求完备——候选名单只求召回）
_IMPORT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("python", re.compile(r"^\s*from\s+([.\w]+)\s+import", re.M)),
    ("python", re.compile(r"^\s*import\s+([\w.]+)", re.M)),
    ("js", re.compile(r"(?:from\s*|require\s*\()\s*['\"]([^'\"]+)['\"]")),
    ("c", re.compile(r"#include\s*[<\"]([^>\"]+)")),
    ("rust", re.compile(r"^\s*use\s+([\w:]+)", re.M)),
    ("cs", re.compile(r"^\s*using\s+([\w.]+)\s*;", re.M)),
    ("go", re.compile(r"^\s*import\s+(?:[\w\s.]+\s+)?[\"]([^\"]+)", re.M)),
    ("java", re.compile(r"^\s*import\s+([\w.]+)\s*;", re.M)),
)

# Go 分组导入块：import (\n "a/b" \n "c" \n)
_GO_BLOCK = re.compile(r"import\s*\(([^)]*)\)", re.S)
_QUOTED = re.compile(r'"([^"]+)"')

# 语义噪声：与项目目录无关的通用段，直接丢弃
_NOISE_TOKENS: frozenset[str] = frozenset(
    {"self", "super", "crate", "std", "os", "sys", "io", "collections", "types"}
)


def _extract_refs(text: str) -> list[str]:
    """从文件文本提取所有 import 引用（原始字符串）。"""
    refs: list[str] = []
    # Go 分组导入块：提取块内所有带引号路径
    for m in _GO_BLOCK.finditer(text):
        refs.extend(_QUOTED.findall(m.group(1)))
    for _, pattern in _IMPORT_PATTERNS:
        for m in pattern.finditer(text):
            refs.extend(g for g in m.groups() if g)
    return refs


def _normalize(ref: str) -> list[str]:
    """规范化引用：去引号/扩展名，按 . / : 拆段，返回候选段。"""
    ref = ref.strip().strip('"').strip("'").lstrip(".")
    if "." in ref.split("/")[-1]:
        ref = ref.rsplit(".", 1)[0]
    tokens: list[str] = []
    for part in ref.replace(":", "/").replace(".", "/").split("/"):
        part = part.strip()
        if part and part not in _NOISE_TOKENS:
            tokens.append(part)
    return tokens


def scan_imports(file_text: str) -> list[str]:
    """提取文件 import 引用，返回规范化候选段列表。"""
    tokens: list[str] = []
    for ref in _extract_refs(file_text):
        tokens.extend(_normalize(ref))
    return tokens


def build_dep_candidates(
    files: dict[Path, list[str]],
    dir_names: set[str],
) -> dict[Path, list[str]]:
    """按目录构建依赖候选名单：目录 → 可能依赖的目录名列表。

    只产纯目录名（不含知识内容）；匹配不上项目的引用丢弃；
    排除自身目录名（同目录引用不算跨目录依赖）。
    """
    result: dict[Path, list[str]] = {}
    for dirpath, filenames in files.items():
        candidates: set[str] = set()
        for name in filenames:
            path = dirpath / name
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for token in scan_imports(text):
                if token in dir_names and token != dirpath.name:
                    candidates.add(token)
        result[dirpath] = sorted(candidates)
    return result
