import json
import sys
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from student_trip.mcp_client import McpCallError, McpProcessClient, McpTimeoutError


class McpProcessClientTests(unittest.TestCase):
    def client(self):
        fixture = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"
        return McpProcessClient(sys.executable, [str(fixture)], startup_timeout=2, serialize_calls=True)

    def test_timeout_keeps_old_call_isolated_until_real_completion(self):
        with self.client() as client:
            with self.assertRaises(McpTimeoutError):
                client.call_tool_text("slow", {"value": "old", "delay": 0.15}, timeout=0.01)
            with self.assertRaisesRegex(McpCallError, "清理"):
                client.call_tool_text("echo", {"value": "new"}, timeout=1)
            # Wait for the reader to receive the old response without consuming it.
            threading.Event().wait(0.25)
            result = json.loads(client.call_tool_text("echo", {"value": "new"}, timeout=1))
            self.assertEqual(result, {"value": "new"})
            self.assertFalse(client._pending)

    def test_cancel_control_call_bypasses_serial_search_lock(self):
        with self.client() as client, ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.call_tool_text, "slow", {"delay": 0.25}, 1)
            client.interrupt_tool("cancelFlightSearch", {"query_id": "one"})
            self.assertEqual(json.loads(future.result(timeout=2)), {"delay": 0.25})

    def test_concurrent_first_calls_share_one_initialized_process(self):
        client = self.client()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda value: json.loads(client.call_tool_text("echo", {"value": value}, timeout=2)), (1, 2)))
            self.assertEqual(results, [{"value": 1}, {"value": 2}])
            self.assertTrue(client.running)
        finally:
            client.close()

    def test_initialize_and_reuse_session(self):
        fixture = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"
        client = McpProcessClient(sys.executable, [str(fixture)], startup_timeout=2)
        try:
            first = json.loads(client.call_tool_text("echo", {"value": 1}, timeout=2))
            second = json.loads(client.call_tool_text("echo", {"value": 2}, timeout=2))
            self.assertEqual(first, {"value": 1})
            self.assertEqual(second, {"value": 2})
            self.assertTrue(client.running)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
