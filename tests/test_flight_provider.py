import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from student_trip.flight_provider import DomesticFlightMcpProvider


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
        self.assertEqual(timeout, 150)

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
