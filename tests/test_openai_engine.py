"""openai 引擎：工具调用循环 + HTTP 重试 + grep 安全（stdlib mock server）。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from aimake.engine import EngineSpec
from aimake.openai_engine import grep, run_openai_engine


def _chat(content=None, tool_calls=None, finish="stop"):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"index": 0, "message": msg, "finish_reason": finish}]}


def _call(call_id, name, args):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


class _MockServer:
    """记录请求、按脚本返回响应的最小 OpenAI 兼容 server。"""

    def __init__(self, responses, delay=0.0):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.hits = 0
        self.delay = delay
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append(json.loads(self.rfile.read(length).decode("utf-8")))
                outer.hits += 1
                if outer.delay:
                    time.sleep(outer.delay)
                item = outer.responses.pop(0) if outer.responses else (500, {"error": "no script"})
                status, body = item[0], item[1]
                headers = item[2] if len(item) > 2 else {}
                payload = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # 客户端超时/断开时正常现象

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _spec(base_url: str, timeout: int = 10) -> EngineSpec:
    return EngineSpec(
        "openai", [], "arg", timeout,
        base_url=base_url, model="test-model", api_key_env="AIMAKE_TEST_KEY",
    )


class TestToolLoop(unittest.TestCase):
    def test_tool_call_then_final(self):
        """E1：先 grep 工具调用，再返回最终 agents.md 文本。"""
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / "foo.txt").write_text("hello needle world\n", encoding="utf-8")
            srv = _MockServer([
                (200, _chat(
                    tool_calls=[_call("c1", "grep", {"pattern": "needle", "path": "."})],
                    finish="tool_calls",
                )),
                (200, _chat(content="# agents.md — ok")),
            ])
            os.environ["AIMAKE_TEST_KEY"] = "sk-test"
            try:
                out = run_openai_engine(_spec(srv.base_url), "make agents.md", cwd)
            finally:
                os.environ.pop("AIMAKE_TEST_KEY", None)
                srv.close()
            self.assertEqual(out, "# agents.md — ok")
            self.assertEqual(srv.requests[0]["tools"][0]["function"]["name"], "grep")
            self.assertEqual(srv.requests[1]["messages"][-1]["role"], "tool")
            self.assertIn("needle", srv.requests[1]["messages"][-1]["content"])


class TestRetry(unittest.TestCase):
    def test_429_then_200(self):
        """E2：429 后重试成功。"""
        with tempfile.TemporaryDirectory() as td:
            srv = _MockServer([
                (429, {"error": "rate"}, {"Retry-After": "0"}),
                (200, _chat(content="ok")),
            ])
            os.environ["AIMAKE_TEST_KEY"] = "k"
            try:
                with mock.patch("aimake.openai_engine.time.sleep"):
                    out = run_openai_engine(_spec(srv.base_url), "p", Path(td))
            finally:
                os.environ.pop("AIMAKE_TEST_KEY", None)
                srv.close()
            self.assertEqual(out, "ok")
            self.assertEqual(srv.hits, 2)

    def test_400_no_retry(self):
        """E2：400 立即失败，不重试。"""
        with tempfile.TemporaryDirectory() as td:
            srv = _MockServer([(400, {"error": "bad"})])
            os.environ["AIMAKE_TEST_KEY"] = "k"
            try:
                with self.assertRaises(RuntimeError):
                    run_openai_engine(_spec(srv.base_url), "p", Path(td))
            finally:
                os.environ.pop("AIMAKE_TEST_KEY", None)
                srv.close()
            self.assertEqual(srv.hits, 1)

    def test_timeout_raises(self):
        """E2：超时立即抛出，不重试。"""
        with tempfile.TemporaryDirectory() as td:
            srv = _MockServer([(200, _chat(content="late"))], delay=3.0)
            os.environ["AIMAKE_TEST_KEY"] = "k"
            try:
                with self.assertRaises(RuntimeError):
                    run_openai_engine(_spec(srv.base_url, timeout=1), "p", Path(td))
            finally:
                os.environ.pop("AIMAKE_TEST_KEY", None)
                srv.close()


class TestGrepTool(unittest.TestCase):
    def test_path_escape_rejected(self):
        """E3：路径越界被拒。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.txt").write_text("x\n", encoding="utf-8")
            out = grep("x", root, path="../..")
            self.assertIn("越界", out)

    def test_output_cap(self):
        """E3：命中数封顶并标记截断。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "big.txt").write_text(
                "\n".join(f"needle {i}" for i in range(500)), encoding="utf-8"
            )
            out = grep("needle", root, max_matches=10)
            self.assertIn("截断", out)
            self.assertLessEqual(len(out.splitlines()), 11)

    def test_no_shell_injection(self):
        """E3：正则字面量，不经 shell；哨兵文件仍在。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.txt").write_text("literal ; rm -rf / here\n", encoding="utf-8")
            (root / "sentinel").write_text("keep\n", encoding="utf-8")
            out = grep(r"; rm -rf /", root)
            self.assertIn("a.txt", out)
            self.assertTrue((root / "sentinel").is_file())

    def test_ignored_dirs_skipped(self):
        """E3：默认忽略目录（node_modules 等）不参与搜索。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "node_modules").mkdir()
            (root / "node_modules" / "x.js").write_text("needle\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("needle\n", encoding="utf-8")
            out = grep("needle", root)
            self.assertIn("src/a.py", out)
            self.assertNotIn("node_modules", out)

    def test_symlink_escape_rejected(self):
        """B1：符号链接指向项目外的文件不得被读取（防 /proc/self/environ 泄密）。"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "proj"
            root.mkdir()
            secret = base / "outside.txt"
            secret.write_text("TOPSECRET_LEAK\n", encoding="utf-8")
            (root / "link").symlink_to(secret)
            (root / "ok.txt").write_text("TOPSECRET_INSIDE\n", encoding="utf-8")
            out = grep("TOPSECRET", root)
            self.assertIn("ok.txt", out)
            self.assertNotIn("link:", out)
            self.assertNotIn("LEAK", out)

    def test_byte_cap_enforced(self):
        """B2：单行超长命中也不得突破 max_bytes。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "long.txt").write_text("x" * 5000 + "needle\n", encoding="utf-8")
            out = grep("needle", root, max_bytes=100)
            self.assertIn("截断", out)
            self.assertLessEqual(len(out), 150)


class TestRunnerDispatch(unittest.TestCase):
    def test_run_engine_dispatches_openai(self):
        """T3：run_engine 把 openai 引擎分派到 HTTP 实现（不撞空 command 检查）。"""
        from aimake.runner import run_engine

        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / "foo.txt").write_text("needle\n", encoding="utf-8")
            srv = _MockServer([
                (200, _chat(
                    tool_calls=[_call("c1", "grep", {"pattern": "needle"})],
                    finish="tool_calls",
                )),
                (200, _chat(content="# dispatched")),
            ])
            os.environ["AIMAKE_TEST_KEY"] = "k"
            try:
                out = run_engine(_spec(srv.base_url), "p", cwd)
            finally:
                os.environ.pop("AIMAKE_TEST_KEY", None)
                srv.close()
            self.assertEqual(out, "# dispatched")


if __name__ == "__main__":
    unittest.main()
