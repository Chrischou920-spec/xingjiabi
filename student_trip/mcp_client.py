from __future__ import annotations

import json
import queue
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any


class McpClientError(RuntimeError):
    """MCP 客户端基础异常。"""


class McpStartupError(McpClientError):
    """MCP 子进程无法启动或初始化失败。"""


class McpCallError(McpClientError):
    """MCP 工具返回协议错误。"""


class McpTimeoutError(McpClientError):
    """等待 MCP 响应超时。"""


class McpProcessClient:
    """同步、线程安全、长连接的 MCP stdio 客户端。

    Node MCP SDK 的 stdio transport 使用一行一个 JSON-RPC 消息。客户端将读取和
    写入放在独立线程中，供同步的 TicketProvider 重复调用同一个 MCP 会话。
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        startup_timeout: float = 30,
    ):
        self.command = command
        self.args = list(args or [])
        self.cwd = str(cwd) if cwd else None
        self.env = env
        self.startup_timeout = startup_timeout
        self._process: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._next_id = 1
        self._stderr_lines: deque[str] = deque(maxlen=30)

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def recent_stderr(self) -> str:
        return "\n".join(self._stderr_lines)

    def start(self) -> None:
        if self.running:
            return
        try:
            self._process = subprocess.Popen(
                [self.command, *self.args],
                cwd=self.cwd,
                env=self.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            raise McpStartupError(f"无法启动 MCP 服务：{exc}") from exc

        self._reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader_thread.start()
        self._stderr_thread.start()

        try:
            response = self._request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "student-trip", "version": "0.1.0"},
                },
                timeout=self.startup_timeout,
            )
            if "protocolVersion" not in response:
                raise McpStartupError("MCP initialize 响应缺少 protocolVersion")
            self._notify("notifications/initialized", {})
        except Exception:
            self.close()
            raise

    def call_tool(self, name: str, arguments: dict[str, Any], timeout: float = 60) -> dict[str, Any]:
        if not self.running:
            self.start()
        return self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=timeout,
        )

    def call_tool_text(self, name: str, arguments: dict[str, Any], timeout: float = 60) -> str:
        result = self.call_tool(name, arguments, timeout)
        if result.get("isError"):
            raise McpCallError(self._content_text(result) or f"工具 {name} 调用失败")
        text = self._content_text(result)
        if not text:
            raise McpCallError(f"工具 {name} 没有返回文本内容")
        return text

    @staticmethod
    def _content_text(result: dict[str, Any]) -> str:
        return "\n".join(
            block.get("text", "")
            for block in result.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()

    def _request(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        if not self.running:
            raise McpStartupError("MCP 子进程未运行")
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        try:
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            try:
                message = response_queue.get(timeout=timeout)
            except queue.Empty as exc:
                detail = f"；服务日志：{self.recent_stderr}" if self.recent_stderr else ""
                raise McpTimeoutError(f"MCP 调用 {method} 超时{detail}") from exc
            if "error" in message:
                error = message["error"]
                raise McpCallError(f"MCP 调用 {method} 失败：{error}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise McpCallError(f"MCP 调用 {method} 返回格式错误")
            return result
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _write(self, message: dict[str, Any]) -> None:
        if not self.running or not self._process or not self._process.stdin:
            raise McpStartupError("MCP 子进程不可用")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            try:
                self._process.stdin.write(payload + "\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise McpClientError(f"写入 MCP 子进程失败：{exc}") from exc

    def _read_stdout(self) -> None:
        assert self._process and self._process.stdout
        for raw_line in self._process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._stderr_lines.append(f"[stdout 非协议内容] {line}")
                continue
            request_id = message.get("id")
            if request_id is None:
                continue
            with self._pending_lock:
                response_queue = self._pending.get(request_id)
            if response_queue:
                response_queue.put(message)

    def _read_stderr(self) -> None:
        assert self._process and self._process.stderr
        for line in self._process.stderr:
            if line.strip():
                self._stderr_lines.append(line.rstrip())

    def close(self) -> None:
        process = self._process
        self._process = None
        if not process:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        for stream in (process.stdout, process.stderr):
            if stream and not stream.closed:
                stream.close()
        for thread in (self._reader_thread, self._stderr_thread):
            if thread and thread.is_alive():
                thread.join(timeout=1)
        self._reader_thread = None
        self._stderr_thread = None
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        failure = {"error": {"code": -32000, "message": "MCP 服务已关闭"}}
        for response_queue in pending:
            try:
                response_queue.put_nowait(failure)
            except queue.Full:
                pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
