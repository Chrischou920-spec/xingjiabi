"""Request-scoped cooperative cancellation; never cancel another user's MCP call."""

from contextvars import ContextVar
from contextlib import contextmanager
import threading
import time


class QueryCancelled(RuntimeError):
    pass


class QueryControl:
    def __init__(self):
        self.event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks = set()

    def check(self):
        if self.event.is_set():
            raise QueryCancelled("查询已取消")

    def cancel(self):
        with self._lock:
            self.event.set()
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            callback()

    @contextmanager
    def on_cancel(self, callback):
        with self._lock:
            self.check()
            self._callbacks.add(callback)
        try:
            yield
        finally:
            with self._lock:
                self._callbacks.discard(callback)


current_query: ContextVar[QueryControl | None] = ContextVar("current_query", default=None)


def check_cancelled():
    control = current_query.get()
    if control:
        control.check()


class QueryRegistry:
    """Bounded cancellation registry, including cancel-before-start races."""
    def __init__(self):
        self._lock = threading.Lock()
        self._entries = {}

    def _prune(self):
        now = time.monotonic()
        for key, (_, active, stamp) in list(self._entries.items()):
            if not active and now - stamp > 600:
                self._entries.pop(key, None)

    def begin(self, query_id):
        with self._lock:
            self._prune()
            previous = self._entries.get(query_id)
            if previous and previous[1]:
                raise ValueError("查询标识正在使用")
            if not previous and len(self._entries) >= 1024:
                raise ValueError("查询过多，请稍后重试")
            control = previous[0] if previous else QueryControl()
            self._entries[query_id] = (control, True, time.monotonic())
            return control

    def cancel(self, query_id):
        with self._lock:
            self._prune()
            previous = self._entries.get(query_id)
            if not previous and len(self._entries) >= 1024:
                raise ValueError("查询过多，请稍后重试")
            control = previous[0] if previous else QueryControl()
            self._entries[query_id] = (control, bool(previous and previous[1]), time.monotonic())
        control.cancel()

    def finish(self, query_id):
        with self._lock:
            self._entries.pop(query_id, None)
