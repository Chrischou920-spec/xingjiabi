import json
import sys
import unittest
from pathlib import Path

from student_trip.mcp_client import McpProcessClient


class McpProcessClientTests(unittest.TestCase):
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

