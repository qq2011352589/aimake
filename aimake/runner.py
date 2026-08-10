"""生成执行器（T7）。

引擎调用 + 并发池（并发上限、超时、失败重试、失败不阻塞父级）。
mock 引擎：内置确定性生成器，用于无认证测试/演示。
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .engine import EngineSpec


@dataclass
class GenResult:
    """单节点生成结果。"""

    rel: str
    ok: bool
    output: str = ""
    error: str = ""
    attempts: int = 1


def run_engine(engine: EngineSpec, prompt: str, cwd: Path) -> str:
    """调用引擎，返回 stdout 文本（aimake 负责写文件，引擎只产文本）。"""
    if engine.name == "mock":
        return _mock_output(prompt)
    if not engine.command:
        raise RuntimeError(
            f"引擎 {engine.name} 未配置命令（请在 .aimake/aimake.json 定义 command）"
        )
    if engine.prompt_how == "stdin":
        proc = subprocess.run(
            engine.command, input=prompt, capture_output=True, text=True,
            cwd=cwd, timeout=engine.timeout,
        )
    else:  # arg：提示词作为最后一个位置参数
        proc = subprocess.run(
            engine.command + [prompt], capture_output=True, text=True,
            cwd=cwd, timeout=engine.timeout,
        )
    if proc.returncode != 0:
        raise RuntimeError(
            f"引擎 {engine.name} 失败（rc={proc.returncode}）："
            f"{proc.stderr.strip() or proc.stdout.strip()[:200]}"
        )
    return proc.stdout


def run_nodes(
    plan: list[tuple[str, str, Path]],  # (rel, prompt, cwd)
    engine: EngineSpec,
    concurrency: int = 4,
    retries: int = 2,
) -> list[GenResult]:
    """并行执行节点生成（并发上限 + 超时 + 重试 + 失败不阻塞）。"""
    results: list[GenResult] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {}
        for rel, prompt, cwd in plan:
            futures[pool.submit(_run_with_retry, engine, prompt, cwd, retries)] = rel
        for fut in as_completed(futures):
            rel = futures[fut]
            try:
                output, attempts = fut.result()
                results.append(GenResult(rel=rel, ok=True, output=output, attempts=attempts))
            except Exception as exc:  # 子级失败不阻塞父级（标失败，供后续重试）
                results.append(GenResult(rel=rel, ok=False, error=str(exc)))
    results.sort(key=lambda r: r.rel)
    return results


def _run_with_retry(
    engine: EngineSpec, prompt: str, cwd: Path, retries: int
) -> tuple[str, int]:
    attempts = 0
    last_err: Exception | None = None
    while attempts <= retries:
        attempts += 1
        try:
            return run_engine(engine, prompt, cwd), attempts
        except Exception as exc:
            last_err = exc
    assert last_err is not None
    raise last_err


def _mock_output(prompt: str) -> str:
    """mock 引擎：回显提示词中注入的上下文，产出可验证的 agents.md。"""
    rel = _section(prompt, "# 目标目录")
    rel = rel[0] if rel else ""
    children = _section(prompt, "# 子目录摘要")
    deps = _section(prompt, "# 依赖候选名单")
    child_block = "\n".join(f"- {c}" for c in children) if children else "- （无子目录）"
    deps_block = "\n".join(f"- {d}" for d in deps) if deps else "- （无）"
    root_block = ""
    if rel == ".":  # 根节点：mock 占位全局捷径表
        root_block = (
            "## WHERE TO LOOK\n"
            "- （mock：全局捷径表占位——真实生成由模型从全局视角写入）\n"
        )
    return (
        f"# agents.md — {rel} 的知识边界\n"
        "## OVERVIEW\n"
        "（mock 引擎占位——本目录职责摘要，真实生成由配置的 AI 引擎完成）\n"
        f"## SUB-KNOWLEDGE\n{child_block}\n"
        f"## DEPENDS\n{deps_block}\n"
        f"{root_block}"
        "## FILES\n"
        "- （mock：见目录实际文件）\n"
    )


def _section(prompt: str, header: str) -> list[str]:
    """取提示词中某个 # 节的内容行（去掉前导 -，直到下一个 # 节）。"""
    out: list[str] = []
    in_section = False
    for line in prompt.splitlines():
        if line.startswith("# "):
            in_section = line.strip().startswith(header)
            continue
        if in_section and line.strip():
            out.append(line.strip().lstrip("- "))
    return out
