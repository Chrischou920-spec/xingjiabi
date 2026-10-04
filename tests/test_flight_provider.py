import json
import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from student_trip.flight_provider import DomesticFlightMcpProvider
from student_trip.mcp_client import McpCallError, McpTimeoutError
from student_trip.query_control import QueryCancelled, QueryControl, current_query


class FakeFlightCaller:
    def __init__(self):
        self.calls = []

    def call_tool_text(self, name, arguments, timeout=60):
        self.calls.append((name, arguments, timeout))
        return json.dumps(
            {
                "status": "success",
                "flights": [
                    {
                        "航空公司": "东方航空",
                        "航班号": "MU5101",
                        "航班类型": "直达",
                        "出发时间": "23:20",
                        "到达时间": "01:35+1",
                        "出发机场": "虹桥机场",
                        "出发航站楼": "T2",
                        "到达机场": "首都机场",
                        "到达航站楼": "T2",
                        "价格": "¥680起",
                    },
                    {
                        "航班号": "CZ100/CZ200",
                        "航班类型": "中转",
                        "出发时间": "10:00",
                        "到达时间": "16:00",
                        "价格数值": 500,
                    },
                    {
                        "航班号": "CA1501",
                        "航班类型": "直达",
                        "出发时间": "09:00",
                        "到达时间": "11:20",
                        "价格数值": 720,
                        "出发机场": "虹桥机场",
                        "到达机场": "首都机场",
                    },
                ],
            },
            ensure_ascii=False,
        )


class BlockedFlightCaller:
    def call_tool_text(self, name, arguments, timeout=60):
        return json.dumps(
            {
                "status": "error",
                "error_code": "SEARCH_FAILED",
                "message": "携程 WhaleGuard 已拦截当前网络/IP",
            },
            ensure_ascii=False,
        )


class DomesticFlightMcpProviderTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeFlightCaller()
        self.provider = DomesticFlightMcpProvider(self.client)

    def test_direct_flights_are_normalized(self):
        rows = self.provider.search(
            "上海",
            "北京",
            datetime(2026, 10, 1),
            datetime(2026, 10, 1, 23, 59),
        )
        self.assertEqual([row.number for row in rows], ["CA1501", "MU5101"])
        overnight = rows[1]
        self.assertEqual(overnight.arrival_at, datetime(2026, 10, 2, 1, 35))
        self.assertEqual(overnight.price, 680)
        self.assertEqual(overnight.departure_station, "虹桥机场T2")
        self.assertEqual(overnight.source, "携程")

    def test_transfer_flight_is_not_treated_as_one_segment(self):
        rows = self.provider.search(
            "上海",
            "北京",
            datetime(2026, 10, 1),
            datetime(2026, 10, 1, 23, 59),
        )
        self.assertNotIn("CZ100/CZ200", {row.number for row in rows})

    def test_international_city_is_rejected_before_mcp_call(self):
        with self.assertRaisesRegex(ValueError, "中国大陆城市"):
            self.provider.search(
                "上海",
                "东京",
                datetime(2026, 10, 1),
                datetime(2026, 10, 1, 23, 59),
            )
        self.assertEqual(self.client.calls, [])

    def test_mcp_call_uses_domestic_search_tool(self):
        self.provider.search(
            "上海",
            "北京",
            datetime(2026, 10, 1),
            datetime(2026, 10, 1, 23, 59),
        )
        name, arguments, timeout = self.client.calls[0]
        self.assertEqual(name, "searchFlightRoutes")
        self.assertEqual(arguments["departure_date"], "2026-10-01")
        self.assertEqual(timeout, 300)
        self.assertTrue(arguments["query_id"])

    def test_timeout_and_tool_error_are_never_retried(self):
        for error in (McpTimeoutError("超时"), McpCallError("验证失败")):
            client = Mock()
            client.call_tool_text.side_effect = error
            provider = DomesticFlightMcpProvider(client, retries=3)
            with self.assertRaisesRegex(Exception, "MCP 调用失败"):
                provider._search_date("上海", "北京", datetime(2026, 10, 1).date())
            self.assertEqual(client.call_tool_text.call_count, 1)
            client.interrupt_tool.assert_called_once()

    def test_incomplete_direct_flight_is_not_silently_no_tickets(self):
        client = Mock()
        client.call_tool_text.return_value = json.dumps({"status": "success", "flights": [{"航班号": "CA1001"}]})
        with self.assertRaisesRegex(Exception, "缺少有效"):
            DomesticFlightMcpProvider(client).search("上海", "北京", datetime(2026, 10, 1), datetime(2026, 10, 1, 23, 59))

    def test_shared_provider_serializes_flight_calls(self):
        entered, release = threading.Event(), threading.Event()
        client = FakeFlightCaller()
        original = client.call_tool_text
        active = 0
        maximum = 0
        lock = threading.Lock()
        def call(*args, **kwargs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            entered.set()
            self.assertTrue(release.wait(2))
            result = original(*args, **kwargs)
            with lock:
                active -= 1
            return result
        client.call_tool_text = call
        provider = DomesticFlightMcpProvider(client)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(provider._search_date, "上海", "北京", datetime(2026, 10, 1).date())
            self.assertTrue(entered.wait(1))
            second = pool.submit(provider._search_date, "北京", "上海", datetime(2026, 10, 3).date())
            release.set()
            first.result(timeout=2)
            second.result(timeout=2)
        self.assertEqual(maximum, 1)
        self.assertNotEqual(client.calls[0][1]["query_id"], client.calls[1][1]["query_id"])

    def test_cancel_is_delivered_to_only_the_active_flight(self):
        control = QueryControl()
        entered, released = threading.Event(), threading.Event()
        client = Mock()
        def call(*args, **kwargs):
            entered.set()
            self.assertTrue(released.wait(2))
            return json.dumps({"status": "success", "flights": []})
        client.call_tool_text.side_effect = call
        client.interrupt_tool.side_effect = lambda *_: released.set()
        provider = DomesticFlightMcpProvider(client)
        def run():
            token = current_query.set(control)
            try:
                return provider._search_date("上海", "北京", datetime(2026, 10, 1).date())
            finally:
                current_query.reset(token)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run)
            self.assertTrue(entered.wait(1))
            control.cancel()
            with self.assertRaises(QueryCancelled):
                future.result(timeout=2)
        sent_id = client.call_tool_text.call_args.args[1]["query_id"]
        client.interrupt_tool.assert_called_once_with("cancelFlightSearch", {"query_id": sent_id})

    def test_configured_browser_is_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "chromium"
            executable.write_text("browser")
            self.assertEqual(
                DomesticFlightMcpProvider._discover_chromium(str(executable)),
                str(executable),
            )

    def test_whaleguard_is_not_reported_as_no_flights(self):
        provider = DomesticFlightMcpProvider(BlockedFlightCaller())
        with self.assertRaisesRegex(Exception, "反爬拦截"):
            provider.search(
                "上海",
                "北京",
                datetime(2026, 10, 1),
                datetime(2026, 10, 1, 23, 59),
            )


if __name__ == "__main__":
    unittest.main()
