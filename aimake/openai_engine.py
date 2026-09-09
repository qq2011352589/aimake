"""openai 引擎（纯标准库）：OpenAI 兼容 /chat/completions + 仅 grep 工具。

不依赖 codex/opencode 等 CLI，也不需要沙箱——模型唯一的工具是只读的
`grep`（纯 Python 递归正则，限定目标项目目录内）。适用于 GitHub Actions
等只需一个 API key 的环境。
"""

from __future__ import annotations

import fnmatch
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

from .config import is_ignored, load_ignore_patterns

_ENDPOINT_SUFFIX = "/chat/completions"
_MAX_HTTP_ATTEMPTS = 5
_MAX_LINE = 10000  # 单行匹配上限，缓解正则回溯（ReDoS）风险

GREP_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "grep",
        "description": (
            "在目标项目目录内用正则搜索文本，返回 `相对路径:行号:内容`。"
            "只能搜索项目内的文件；pattern 是正则字面量，不是 shell 命令。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python 正则表达式"},
                "path": {"type": "string", "description": "相对项目根的路径，默认 ."},
                "glob": {"type": "string", "description": "文件名通配，如 *.ts"},
            },
            "required": ["pattern"],
        },
    },
}


def grep(
    pattern: str,
    cwd: Path,
    path: str = ".",
    glob: str | None = None,
    max_matches: int = 200,
    max_bytes: int = 20000,
) -> str:
    """项目内正则搜索（纯 Python，无 shell）；越界/非法正则返回错误字符串。"""
    root = Path(cwd).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        return "错误：路径越界（grep 仅限目标项目内）"
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return f"错误：非法正则：{exc}"
    patterns = load_ignore_patterns(root)
    lines: list[str] = []
    total = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
        current = Path(dirpath)
        rel_dir = current.relative_to(root).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = sorted(n for n in dirnames if not is_ignored(prefix + n, patterns))
        for name in sorted(filenames):
            if is_ignored(prefix + name, patterns):
                continue
            if glob and not fnmatch.fnmatch(name, glob):
                continue
            fp = current / name
            # B1：跳过符号链接，并二次校验真实路径仍在项目内
            #（防 `ln -s /proc/self/environ` 之类越界读取密钥）
            if fp.is_symlink() or not fp.resolve().is_relative_to(root):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = fp.relative_to(root).as_posix()
            for lineno, line in enumerate(text.splitlines(), 1):
                hay = line if len(line) <= _MAX_LINE else line[:_MAX_LINE]
                if not rx.search(hay):
                    continue
                entry = f"{rel}:{lineno}:{line}"
                # B2：写前截断，守住字节上限（单行超长也不突破）
                if total + len(entry) + 1 > max_bytes:
                    entry = entry[: max(0, max_bytes - total - 1)]
                    if entry:
                        lines.append(entry)
                    truncated = True
                    break
                lines.append(entry)
                total += len(entry) + 1
                if len(lines) >= max_matches:
                    truncated = True
                    break
            if truncated:
                break
        if truncated:
            break
    out = "\n".join(lines)
    return out + "\n…（已截断）" if truncated else out


def _endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith(_ENDPOINT_SUFFIX) else base + _ENDPOINT_SUFFIX


def _retry_delay(headers, attempt: int) -> float:
    """Retry-After（秒或 HTTP 日期）优先，否则指数退避 + 抖动。"""
    raw = headers.get("Retry-After") if headers else None
    if raw:
        raw = raw.strip()
        if raw.isdigit():
            return float(raw)
        try:
            when = parsedate_to_datetime(raw)
            delta = (when.timestamp() - time.time()) if when else 0
            if delta > 0:
                return delta
        except (TypeError, ValueError, OverflowError):
            pass
    return 0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.5)


def _http_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="ignore")[:300]
    except Exception:  # noqa: BLE001 - 读错误体失败不应掩盖原错误
        return str(exc.reason)


def _request_with_retry(req: urllib.request.Request, timeout: int) -> dict:
    """POST 并在 408/409/429/5xx 上重试；400/401/403/quota/超时立即失败。"""
    for attempt in range(1, _MAX_HTTP_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = _http_body(exc)
            if "insufficient_quota" in body.lower() or exc.code in (400, 401, 403):
                raise RuntimeError(f"openai 引擎请求失败（HTTP {exc.code}）：{body}") from exc
            if (exc.code in (408, 409, 429) or exc.code >= 500) and attempt < _MAX_HTTP_ATTEMPTS:
                time.sleep(_retry_delay(exc.headers, attempt))
                continue
            raise RuntimeError(f"openai 引擎请求失败（HTTP {exc.code}）：{body}") from exc
        except TimeoutError as exc:
            raise RuntimeError(f"openai 引擎超时（{timeout}s）") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise RuntimeError(f"openai 引擎超时（{timeout}s）") from exc
            if attempt >= _MAX_HTTP_ATTEMPTS:
                raise RuntimeError(f"openai 引擎网络错误：{exc.reason}") from exc
            time.sleep(_retry_delay(None, attempt))
    raise RuntimeError("openai 引擎重试耗尽")


def _post_chat(spec, messages: list[dict]) -> dict:
    key = os.environ.get(spec.api_key_env, "")
    if not key:
        raise RuntimeError(f"openai 引擎缺少 API key（请设置环境变量 {spec.api_key_env}）")
    if not spec.base_url:
        raise RuntimeError("openai 引擎缺少 base_url（请在 aimake.json 配置 engine.base_url）")
    if not spec.model:
        raise RuntimeError("openai 引擎缺少 model（请在 aimake.json 配置 engine.model）")
    body = {
        "model": spec.model,
        "messages": messages,
        "tools": [GREP_TOOL],
        "tool_choice": "auto",
        "max_tokens": spec.max_tokens,
        "stream": False,
    }
    req = urllib.request.Request(
        _endpoint(spec.base_url),
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    return _request_with_retry(req, spec.timeout)


def _run_grep_tool(name: str, args: dict, cwd: Path) -> str:
    if name != "grep":
        return f"错误：未知工具 {name}"
    return grep(
        str(args.get("pattern", "")),
        cwd,
        path=str(args.get("path", ".")),
        glob=args.get("glob") or None,
    )


def run_openai_engine(spec, prompt: str, cwd: Path) -> str:
    """调用 OpenAI 兼容端点，跑 grep 工具循环，返回最终 agents.md 文本。"""
    messages: list[dict] = [{"role": "user", "content": prompt}]
    for _ in range(max(1, spec.max_tool_rounds)):
        resp = _post_chat(spec, messages)
        try:
            choice = resp["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"openai 引擎返回格式异常：{str(resp)[:300]}") from exc
        tool_calls = message.get("tool_calls")
        if choice.get("finish_reason") != "tool_calls" and not tool_calls:
            return message.get("content") or ""
        messages.append(message)
        for call in tool_calls or []:
            if call.get("type") != "function":
                result = f"错误：不支持的工具类型 {call.get('type')}"
            else:
                fn = call.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError as exc:
                    result = f"错误：工具参数不是合法 JSON：{exc}"
                else:
                    result = _run_grep_tool(str(fn.get("name", "")), args, cwd)
            messages.append(
                {"role": "tool", "tool_call_id": call.get("id", ""), "content": result}
            )
    raise RuntimeError("openai 引擎工具调用轮次超限")
