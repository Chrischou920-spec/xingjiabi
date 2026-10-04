from io import BytesIO
import json
import unittest
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from student_trip.demo import demo_providers
from student_trip.models import TransportMode, TransportSegment
from student_trip.providers import InMemoryProvider
from student_trip.server import Handler
from student_trip.query_control import QueryRegistry
from student_trip.train_provider import ProviderUnavailableError


class FailingFlightProvider:
    mode = TransportMode.FLIGHT

    def search(self, *_args):
        raise ProviderUnavailableError("航班数据源被拦截")


class CaptureHandler(Handler):
    def __init__(self, path, body):
        self.path = path
        self.headers = {"Content-Length": str(len(body))}
        self.rfile = BytesIO(body)
        self.wfile = BytesIO()
        self.status = None
        self.response_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.response_headers[key] = value

    def end_headers(self):
        pass


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_providers = Handler.providers
        cls.previous_mode = Handler.data_mode

    @classmethod
    def tearDownClass(cls):
        Handler.providers = cls.previous_providers
        Handler.data_mode = cls.previous_mode

    def setUp(self):
        Handler.providers = demo_providers()
        Handler.data_mode = "demo"
        Handler.queries = QueryRegistry()

    def read(self, path, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        handler = CaptureHandler(path, body)
        if payload is None:
            handler.do_GET()
        else:
            handler.do_POST()
        return handler.status, handler.wfile.getvalue(), handler.response_headers

    @staticmethod
    def journey(**changes):
        data = {
            "origin": "上海",
            "destination": "北京",
            "outbound_after": "2026-10-01T06:00:00",
            "outbound_before": "2026-10-01T12:00:00",
            "return_after": "2026-10-03T16:00:00",
            "return_before": "2026-10-03T22:30:00",
            "allowed_modes": ["train", "flight"],
            "max_transfers": 0,
        }
        data.update(changes)
        return data

    def test_serves_site_and_city_options(self):
        status, body, headers = self.read("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("出行规划".encode(), body)
        status, body, _ = self.read("/cities")
        self.assertEqual(status, 200)
        self.assertIn("上海", json.loads(body)["cities"])

    def test_plan_has_results_and_query_metadata(self):
        status, body, _ = self.read("/plan", self.journey())
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(data["plans"])
        self.assertEqual(data["data_mode"], "demo")
        self.assertIn("queried_at", data)
        self.assertEqual(data["flights"]["outbound"][0]["number"], "MU5101")
        self.assertEqual(data["flights"]["inbound"][0]["number"], "CA1501")

    def test_all_scraped_flights_are_returned_not_only_top_plans(self):
        flights = [
            TransportSegment(
                TransportMode.FLIGHT, f"MU{5100 + index}", "上海", "北京",
                datetime(2026, 10, 1, 7) + timedelta(minutes=30 * index),
                datetime(2026, 10, 1, 9) + timedelta(minutes=30 * index),
                600 + index, "虹桥机场", "首都机场", "经济舱", "携程",
            ) for index in range(5)
        ]
        Handler.providers = [InMemoryProvider(TransportMode.FLIGHT, flights)]
        Handler.data_mode = "live_flight"
        status, body, _ = self.read("/plan", self.journey(
            return_after=None, return_before=None, allowed_modes=["flight"],
        ))
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(len(data["plans"]), 3)
        self.assertEqual(len(data["flights"]["outbound"]), 5)
        self.assertEqual(data["flights"]["outbound"][0]["source"], "携程")

    def test_flight_failure_keeps_real_train_results_visible(self):
        Handler.providers = [demo_providers()[0], FailingFlightProvider()]
        Handler.data_mode = "live_all"
        status, body, _ = self.read("/plan", self.journey())
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(data["plans"])
        self.assertIn("flight", data["source_errors"])
        self.assertTrue(all(segment["mode"] == "train" for plan in data["plans"] for segment in plan["outbound"]))

    def test_no_result_with_source_failure_is_503(self):
        Handler.providers = [FailingFlightProvider()]
        status, body, _ = self.read("/plan", self.journey(allowed_modes=["flight"]))
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["error"], "provider_unavailable")

    def test_unavailable_mode_is_rejected(self):
        Handler.providers = [demo_providers()[0]]
        status, body, _ = self.read("/plan", self.journey(allowed_modes=["flight"]))
        self.assertEqual(status, 400)
        self.assertIn("不支持", json.loads(body)["message"])

    def test_non_object_request_is_rejected(self):
        status, body, _ = self.read("/plan", [])
        self.assertEqual(status, 400)
        self.assertIn("JSON 对象", json.loads(body)["message"])

    def test_cancel_before_plan_does_not_run_provider(self):
        query_id = uuid.uuid4().hex
        status, _, _ = self.read("/cancel", {"query_id": query_id})
        self.assertEqual(status, 200)
        status, body, _ = self.read("/plan", self.journey(query_id=query_id))
        self.assertEqual(status, 499)
        self.assertEqual(json.loads(body)["error"], "query_cancelled")

    def test_cancel_active_plan_skips_return_query(self):
        entered, release = threading.Event(), threading.Event()
        original = demo_providers()[0]
        calls = []
        class SlowProvider:
            mode = TransportMode.TRAIN
            def search(self, *args):
                calls.append(args)
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("test timed out")
                return original.search(*args)
        Handler.providers = [SlowProvider()]
        query_id = uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.read, "/plan", self.journey(allowed_modes=["train"], query_id=query_id))
            self.assertTrue(entered.wait(1))
            status, _, _ = self.read("/cancel", {"query_id": query_id})
            self.assertEqual(status, 200)
            release.set()
            status, body, _ = future.result(timeout=2)
        self.assertEqual(status, 499)
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(body)["error"], "query_cancelled")

    def test_cancel_requires_valid_query_id(self):
        for payload in ({}, {"query_id": "bad"}):
            status, _, _ = self.read("/cancel", payload)
            self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
