import json
import unittest
from datetime import datetime

from student_trip.train_provider import TrainMcpProvider


class FakeToolCaller:
    def __init__(self):
        self.calls = []

    def call_tool_text(self, name, arguments, timeout=60):
        self.calls.append((name, arguments))
        if name == "get-station-code-of-citys":
            return json.dumps(
                {
                    "上海": {"station_code": "SHH"},
                    "北京": {"station_code": "BJP"},
                },
                ensure_ascii=False,
            )
        if name == "get-tickets":
            return json.dumps(
                [
                    {
                        "start_train_code": "G10",
                        "start_date": "20261001",
                        "start_time": "23:30",
                        "arrive_date": "20261002",
                        "arrive_time": "04:20",
                        "from_station": "上海虹桥",
                        "to_station": "北京南",
                        "prices": [
                            {"seat_name": "二等座", "num": "有", "price": 553},
                            {"seat_name": "一等座", "num": "0", "price": 933},
                            {"seat_name": "商务座", "num": "3", "price": 1748},
                        ],
                    }
                ],
                ensure_ascii=False,
            )
        raise AssertionError(name)


class TrainMcpProviderTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeToolCaller()
        self.provider = TrainMcpProvider(self.client)

    def test_json_is_normalized_and_unavailable_seat_filtered(self):
        segments = self.provider.search(
            "上海",
            "北京",
            datetime(2026, 10, 1, 20),
            datetime(2026, 10, 1, 23, 59),
        )
        self.assertEqual(len(segments), 2)
        self.assertEqual({item.seat_or_cabin for item in segments}, {"二等座", "商务座"})
        self.assertEqual(segments[0].number, "G10")
        self.assertEqual(segments[0].arrival_at, datetime(2026, 10, 2, 4, 20))
        self.assertEqual(segments[0].source, "12306")

    def test_station_codes_are_cached(self):
        for _ in range(2):
            self.provider.search(
                "上海",
                "北京",
                datetime(2026, 10, 1, 20),
                datetime(2026, 10, 1, 23, 59),
            )
        station_calls = [call for call in self.client.calls if call[0] == "get-station-code-of-citys"]
        self.assertEqual(len(station_calls), 1)

    def test_query_requests_json_and_time_window(self):
        self.provider.search(
            "上海",
            "北京",
            datetime(2026, 10, 1, 20, 30),
            datetime(2026, 10, 1, 23, 10),
        )
        ticket_call = next(call for call in self.client.calls if call[0] == "get-tickets")
        self.assertEqual(ticket_call[1]["format"], "json")
        self.assertEqual(ticket_call[1]["earliestStartTime"], 20)
        self.assertEqual(ticket_call[1]["latestStartTime"], 24)


if __name__ == "__main__":
    unittest.main()

