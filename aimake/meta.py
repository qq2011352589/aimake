"""指纹（.meta）管理（T5）。

每目录一个 .meta（位于知识根镜像目录内），记录**目标项目对应目录**的
可见文件清单 hash——update 通道 1 的核心判定依据（指纹幂等）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

META_NAME = ".meta"
_CHUNK = 65536


def file_hash(path: Path, length: int = 12) -> str:
    """计算文件 sha256（截断前 length 位）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(_CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()[:length]


def write_meta(source_dir: Path, files: list[str], meta_path: Path) -> Path:
    """记录 source_dir 的文件指纹到 meta_path。

    行格式：`<文件名> <hash>`（# 开头为注释）。返回 meta_path。
    """
    lines = ["# aimake meta — 文件指纹（文件名 sha256 前 12 位）"]
    for name in files:
        try:
            digest = file_hash(source_dir / name)
        except OSError:
            digest = "000000000000"
        lines.append(f"{name} {digest}")
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return meta_path


def read_meta(meta_path: Path) -> dict[str, str]:
    """读指纹：文件名 → hash。"""
    result: dict[str, str] = {}
    if not meta_path.is_file():
        return result
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 2:
            result[parts[0]] = parts[1]
    return result


def current_fingerprint(source_dir: Path, files: list[str]) -> dict[str, str]:
    """计算当前指纹（用于与 .meta 比对）。

    文件缺失（记录过但被删）以空串占位 → 与 .meta 差异即判过期。
    """
    current: dict[str, str] = {}
    for name in files:
        try:
            current[name] = file_hash(source_dir / name)
        except OSError:
            current[name] = ""
    return current


def is_stale(source_dir: Path, files: list[str], meta_path: Path) -> bool:
    """指纹比对：目标目录文件是否变化（真 → 过期，需重生成）。"""
    recorded = read_meta(meta_path)
    current = current_fingerprint(source_dir, files)
    return current != recorded
