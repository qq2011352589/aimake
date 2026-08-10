"""目录遍历（T3）。

os.walk + followlinks=False（symlink 不递归，防环第一道闸）；
原地剪枝被忽略目录；收集可见目录树与每目录可见文件清单。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import is_ignored, load_ignore_patterns


@dataclass
class WalkResult:
    """遍历结果：可见目录树 + 每目录可见文件。"""

    root: Path
    directories: list[Path] = field(default_factory=list)
    files: dict[Path, list[str]] = field(default_factory=dict)

    def tree_text(self) -> str:
        """可见目录树的文本呈现（scan 命令输出）。"""
        lines: list[str] = [f"{self.root}（{len(self.directories)} 个可见目录）"]
        for d in self.directories:
            rel = d.relative_to(self.root).as_posix()
            depth = 0 if rel == "." else rel.count("/") + 1
            lines.append(f"{'  ' * depth}{d.name}/")
            for f in self.files.get(d, []):
                lines.append(f"{'  ' * (depth + 1)}{f}")
        return "\n".join(lines)


def walk_project(root: Path, extra_patterns: tuple[str, ...] = ()) -> WalkResult:
    """遍历项目，返回可见目录树（ignore 规则生效）。"""
    root = root.resolve()
    patterns = load_ignore_patterns(root, extra_patterns)
    result = WalkResult(root=root)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        rel = current.relative_to(root).as_posix()
        prefix = "" if rel == "." else rel + "/"

        # 原地剪枝：不进入被忽略的子目录（os.walk 尊重 dirnames 修改）
        dirnames[:] = sorted(
            d for d in dirnames if not is_ignored(prefix + d, patterns)
        )

        result.directories.append(current)
        result.files[current] = sorted(
            f for f in filenames if not is_ignored(prefix + f, patterns)
        )

    return result
