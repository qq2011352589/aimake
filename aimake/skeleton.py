"""知识根镜像骨架与指纹（T5）。

知识根 = 运行目录的 `.aimake/`；目标项目按目录路径镜像：
  目标项目 `rel` 目录 → 知识根 `<目标名>/<rel>/`（目标为运行目录时 → 知识根 `<rel>/`）。
每镜像目录写 `.meta` 指纹（记录目标侧文件清单 hash）。
"""

from __future__ import annotations

from pathlib import Path

from .meta import META_NAME, write_meta
from .walk import WalkResult


def resolve_knowledge_root(cwd: Path) -> Path:
    """知识根 = 运行目录的 .aimake/（单一模式，见 AGENTS.md）。"""
    return cwd / ".aimake"


def mirror_prefix(knowledge_root: Path, target: Path, cwd: Path) -> Path:
    """目标项目在知识根内的镜像前缀。"""
    if target == cwd:
        return knowledge_root
    return knowledge_root / target.name


def create_skeleton(
    knowledge_root: Path,
    target: Path,
    cwd: Path,
    walk: WalkResult,
) -> tuple[list[Path], list[Path]]:
    """创建镜像骨架目录 + 写 .meta 指纹。

    返回 (创建的镜像目录列表, 写入的 .meta 路径列表)。
    """
    prefix = mirror_prefix(knowledge_root, target, cwd)
    created: list[Path] = []
    metas: list[Path] = []
    for d in walk.directories:
        rel = d.relative_to(walk.root).as_posix()
        mirror_dir = prefix if rel == "." else prefix / rel
        mirror_dir.mkdir(parents=True, exist_ok=True)
        created.append(mirror_dir)
        metas.append(write_meta(d, walk.files[d], mirror_dir / META_NAME))
    return created, metas
