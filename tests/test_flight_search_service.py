"""Browser-free regression tests for the bundled upstream adapter."""
import importlib.util
import logging
from pathlib import Path
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, patch


path = Path(__file__).resolve().parents[1] / "services/FlightTicketMCP/flight_ticket_mcp_server/tools/flight_search_tools.py"
spec = importlib.util.spec_from_file_location("flight_search_under_test", path)
logging.getLogger("flight_search_under_test").disabled = True
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


class FakePage:
    def __init__(self, text="", html="", rows=()):
        self.html = html or text
        self.text = text
        self.rows = rows
        self.challenge = None

    def run_js(self, _script):
        return self.text

    def ele(self, selector, **kwargs):
        if selector == "css:.body-wrapper" and self.rows:
            return Mock(eles=lambda *_: self.rows)
        if selector == "css:.captcha":
            return self.challenge
        return None

    def eles(self, *_args, **_kwargs):
        return self.rows


class FlightSearchServiceTests(unittest.TestCase):
    def searcher(self, page):
        searcher = service.FlightRouteSearcher.__new__(service.FlightRouteSearcher)
        searcher.page = page
        searcher.cancel_event = threading.Event()
        searcher.deadline = service.time.monotonic() + 240
        searcher._parse_flight_container = lambda row, _: row
        return searcher

    def test_late_verification_and_block_are_not_success_empty(self):
        for text, html, code in (
            ("请完成安全验证", "", "VERIFICATION_REQUIRED"),
            ("", "x" * 6000 + "whaleguard block", "SOURCE_BLOCKED"),
            ("请先登录", "", "VERIFICATION_REQUIRED"),
            ("服务异常", "", "SOURCE_ERROR"),
            ("正在加载", "", "CONTENT_NOT_READY"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(service.FlightSearchError) as error:
                    self.searcher(FakePage(text, html))._parse_flights()
                self.assertEqual(error.exception.code, code)

    def test_explicit_no_flights_is_success_empty(self):
        for text in ("暂无航班", "抱歉，未找到符合条件的航班"):
            self.assertEqual(self.searcher(FakePage(text))._parse_flights(), [])

    def test_login_modal_takes_priority_over_empty_and_verification_login_label(self):
        page = FakePage("抱歉，未找到符合条件的航班\n账号密码登录\n验证码登录")
        self.assertEqual(self.searcher(page)._page_state(), "login")
        page = FakePage("登录 注册 我的订单", rows=[{"航班号": "CA1001"}])
        self.assertEqual(self.searcher(page)._page_state(), "unknown")

    def test_ctrip_puzzle_and_icon_challenges_override_no_flight_hint(self):
        for challenge in ("请按顺序点选图标", "向右滑动填充拼图"):
            page = FakePage("抱歉，未找到符合条件的航班\n" + challenge)
            self.assertEqual(self.searcher(page)._page_state(), "captcha")
            with self.assertRaises(service.FlightSearchError):
                self.searcher(page)._parse_flights()

    def test_script_keywords_do_not_trigger_verification(self):
        page = FakePage("上海到北京", '<script>captcha login verify</script>', [{"航班号": "CA1001"}])
        self.assertEqual(self.searcher(page)._parse_flights(), page.rows)

    def test_visible_challenge_overrides_existing_flight_cards(self):
        page = FakePage("上海到北京", rows=[{"航班号": "CA1001"}])
        page.challenge = Mock()
        page.challenge.states.is_displayed = True
        with self.assertRaises(service.FlightSearchError):
            self.searcher(page)._parse_flights()
        page.challenge.states.is_displayed = False
        self.assertEqual(self.searcher(page)._parse_flights(), page.rows)

    def test_all_flights_are_parsed_not_just_first_ten(self):
        rows = [{"航班号": f"CA{i:04}"} for i in range(25)]
        self.assertEqual(len(self.searcher(FakePage(rows=rows))._parse_flights()), 25)

    def test_disconnection_and_invalid_rows_are_not_empty(self):
        page = FakePage()
        page.run_js = Mock(side_effect=RuntimeError("页面连接已断开"))
        with self.assertRaises(service.FlightSearchError):
            self.searcher(page)._parse_flights()
        with self.assertRaises(service.FlightSearchError):
            self.searcher(FakePage(rows=[{"航班号": "未知"}]))._parse_flights()

    def test_captcha_timeout_uses_elapsed_time(self):
        clock = [0.0]
        searcher = self.searcher(FakePage())
        searcher.deadline = 240
        searcher._sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        def slow_poll(*_args, **_kwargs):
            clock[0] += 0.6
            return []
        searcher.page.eles = slow_poll
        with patch.object(service.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(service, "CAPTCHA_TIMEOUT_SECONDS", 2), \
             patch.object(service, "create_browser_options"), \
             patch.object(service, "ChromiumPage", return_value=searcher.page):
            searcher.page.get = Mock()
            with self.assertRaises(service.FlightSearchError) as error:
                searcher._create_new_browser_for_captcha("https://example.com")
        self.assertEqual(error.exception.code, "VERIFICATION_TIMEOUT")
        self.assertLessEqual(clock[0], 3)

    def test_one_flight_is_enough_to_finish_verification(self):
        searcher = self.searcher(FakePage(rows=[{"航班号": "CA1001"}]))
        searcher._sleep = Mock()
        searcher.page.get = Mock()
        with patch.object(service, "create_browser_options"), \
             patch.object(service, "ChromiumPage", return_value=searcher.page):
            searcher._create_new_browser_for_captcha("https://example.com")

    def test_cancel_before_start_never_opens_browser(self):
        service.cancelFlightSearch("early-cancel")
        with patch.object(service, "_search_flight_routes") as search:
            result = service.searchFlightRoutes("上海", "北京", "2099-10-01", "early-cancel")
        self.assertEqual(result["error_code"], "QUERY_CANCELLED")
        search.assert_not_called()

    def test_service_serializes_and_can_cancel_active_job(self):
        entered, release = threading.Event(), threading.Event()
        def run(_origin, _dest, _date, cancel_event):
            entered.set()
            self.assertTrue(release.wait(2))
            return {"status": "error", "error_code": "QUERY_CANCELLED"} if cancel_event.is_set() else {"status": "success"}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(service, "BROWSER_USER_DATA_DIR", directory), \
             patch.object(service, "_search_flight_routes", side_effect=run), \
             ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(service.searchFlightRoutes, "上海", "北京", "2099-10-01", "first")
            self.assertTrue(entered.wait(1))
            second = pool.submit(service.searchFlightRoutes, "北京", "上海", "2099-10-03", "second")
            service.cancelFlightSearch("first")
            release.set()
            self.assertEqual(first.result(timeout=2)["error_code"], "QUERY_CANCELLED")
            self.assertEqual(second.result(timeout=2)["status"], "success")

    def test_browser_does_not_use_default_debug_port(self):
        options = Mock()
        port_socket = Mock()
        port_socket.getsockname.return_value = ("127.0.0.1", 42317)
        with patch.object(service, "ChromiumOptions", return_value=options), \
             patch.object(service.socket, "socket") as socket_class:
            socket_class.return_value.__enter__.return_value = port_socket
            service.create_browser_options()
        port = options.set_local_port.call_args.args[0]
        self.assertNotEqual(port, 9222)
        options.set_user_data_path.assert_called_once_with(service.BROWSER_USER_DATA_DIR)

    def test_late_login_opens_visible_verification_once(self):
        searcher = self.searcher(FakePage())
        searcher.headless = True
        searcher.base_url = "https://example.com/{}-{}?date={}"
        searcher.page.get = Mock()
        searcher.page.quit = Mock()
        page = searcher.page
        searcher._create_new_browser = Mock()
        searcher._detect_captcha_or_login = Mock(return_value=(False, None))
        rows = [{"航班号": "CA1001"}]
        searcher._load_and_parse = Mock(side_effect=[service.FlightSearchError("VERIFICATION_REQUIRED", "登录"), rows])
        searcher._page_state = Mock(return_value="login")
        searcher.close = Mock()
        searcher._create_new_browser_for_captcha = Mock()
        with patch.object(service, "get_airport_code", side_effect=lambda city: city), \
             patch.object(service, "get_city_name", side_effect=lambda city: city):
            result = searcher.search_flights("SHA", "CTU", "2099-10-01")
        self.assertEqual(result, rows)
        searcher._create_new_browser_for_captcha.assert_called_once_with("https://example.com/SHA-CTU?date=2099-10-01", "login")
        page.quit.assert_called_once()
        self.assertIsNone(searcher.page)

    def test_visible_browser_waits_on_the_same_challenge_page(self):
        searcher = self.searcher(FakePage())
        searcher.headless = False
        searcher.base_url = "https://example.com/{}-{}?date={}"
        page = searcher.page
        page.get = Mock()
        page.quit = Mock()
        searcher._create_new_browser = Mock()
        searcher._detect_captcha_or_login = Mock(side_effect=[(True, "captcha"), (False, None)])
        searcher._wait_for_captcha_completion = Mock()
        searcher._create_new_browser_for_captcha = Mock()
        searcher._load_and_parse = Mock(return_value=[{"航班号": "CA1001"}])
        with patch.object(service, "get_airport_code", side_effect=lambda city: city), \
             patch.object(service, "get_city_name", side_effect=lambda city: city):
            result = searcher.search_flights("SHA", "BJS", "2099-10-01")
        self.assertEqual(result[0]["航班号"], "CA1001")
        searcher._wait_for_captcha_completion.assert_called_once_with("captcha")
        searcher._create_new_browser_for_captcha.assert_not_called()
        page.get.assert_called_once()

    def test_visible_challenge_cannot_be_accepted_just_because_cards_exist(self):
        page = FakePage("请完成安全验证", rows=[{"航班号": "CA1001"}])
        searcher = self.searcher(page)
        searcher._sleep = Mock()
        with patch.object(service, "CAPTCHA_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(service.FlightSearchError) as error:
                searcher._wait_for_captcha_completion()
        self.assertEqual(error.exception.code, "VERIFICATION_TIMEOUT")

    def test_prices_with_thousands_and_decimals_are_not_truncated(self):
        page = FakePage()
        searcher = self.searcher(page)
        del searcher._parse_flight_container
        container = Mock()
        container.eles.return_value = []
        def element(selector, **_kwargs):
            return Mock(text="¥1,234.50起") if selector == 'css:.price' else None
        container.ele.side_effect = element
        self.assertEqual(searcher._parse_flight_container(container, 1)["价格数值"], 1234.5)


if __name__ == "__main__":
    unittest.main()
