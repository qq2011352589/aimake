"""反馈文件（T17）：事实性错误报告格式 + 解析 + 写入。

路径：.aimake/feedback/<日期>-<目录>[-<报告方>].md
格式：来源小节 + 错误描述 + 证据（可溯源，禁主观评分）。
四方确认：同一目标+来源的多个报告方文件构成"票"（T18/T19 处理）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

FEEDBACK_DIR_NAME = "feedback"


@dataclass
class FeedbackEntry:
    """一条事实性错误：来源条目 + 错误 + 证据。"""

    source: str = ""  # 来源小节（KEY SYMBOLS / QA #2 / OVERVIEW ...）
    error: str = ""
    evidence: str = ""


@dataclass
class Feedback:
    """一份反馈报告。"""

    path: Path
    target: str = ""  # 目标目录 rel（"" = 根）
    date: str = ""
    reporter: str = ""  # 报告方角色（消费者/消费者父目录/owner/owner 父目录）
    entries: list[FeedbackEntry] = field(default_factory=list)

    def sources(self) -> list[str]:
        return [e.source for e in self.entries]


def feedback_dir(knowledge_root: Path) -> Path:
    """反馈队列目录。"""
    return knowledge_root / FEEDBACK_DIR_NAME


def write_feedback(
    knowledge_root: Path,
    target: str,
    reporter: str,
    entries: list[FeedbackEntry],
    date: str,
) -> Path:
    """写一份反馈文件（供消费方 AI 与 T20 使用）。"""
    d = feedback_dir(knowledge_root)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{date}-{target.replace('/', '-') or '根'}"
    if reporter:
        name += f"-{reporter}"
    path = d / f"{name}.md"
    lines = [
        "# 反馈报告",
        f"日期: {date}",
        f"报告方: {reporter}",
        f"目标目录: {target or '根'}",
        "",
    ]
    for e in entries:
        lines += ["## 条目", f"来源: {e.source}", f"错误: {e.error}", f"证据: {e.evidence}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def parse_feedback(path: Path) -> Feedback | None:
    """解析反馈文件；无有效条目返回 None。"""
    if not path.is_file():
        return None
    fb = Feedback(path=path)
    cur: FeedbackEntry | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        key, _, value = s.partition(":")
        key = key.strip()
        value = value.strip()
        if not value:
            key, _, value = s.partition("：")
            value = value.strip()
        if key == "日期":
            fb.date = value
        elif key == "报告方":
            fb.reporter = value
        elif key == "目标目录":
            # 归一化：写入端用 "根" 表示根节点，解析端还原为 ""（与 node_plan 键一致）
            fb.target = "" if value == "根" else value
        elif key == "来源":
            if cur:
                fb.entries.append(cur)
            cur = FeedbackEntry(source=value)
        elif key == "错误":
            if cur:
                cur.error = value
        elif key == "证据":
            if cur:
                cur.evidence = value
    if cur:
        fb.entries.append(cur)
    return fb if fb.entries else None


def list_feedback(knowledge_root: Path) -> list[Feedback]:
    """反馈队列（按文件名排序）。"""
    d = feedback_dir(knowledge_root)
    if not d.is_dir():
        return []
    result: list[Feedback] = []
    for f in sorted(d.iterdir()):
        if f.is_file():
            fb = parse_feedback(f)
            if fb:
                result.append(fb)
    return result
