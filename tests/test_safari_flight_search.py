import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "FlightTicketMCP"))
from flight_ticket_mcp_server.tools.safari_flight_search import (
    SafariFlightError, SafariFlightSearcher, parse_safari_flights,
)


PAGE = """我的账户: 尊敬的会员
更多日期 ¥400低
单程：上海 北京 10月20日
最近更新时间: 13:02:20
中国联合航空 KN5956 波音737(中) 当日低价
20:05 虹桥国际机场 T2
22:15 大兴国际机场
已减¥10 普通会员可享
¥ 440 起 经济舱
订票
中国联合航空 KN5978 波音737(中)
08:15 浦东国际机场 T1
10:25 大兴国际机场
已减¥10 普通会员可享
¥ 480 起 经济舱
订票
国航 CA8954 国航 CA1618
10:40 浦东国际机场 T2 通程 大连 2h50m 17:00 首都国际机场 T3
¥500 起 经济舱
订票 剩3张
在线客服
旅游资讯
"""

CHALLENGES = (
    "验证码", "安全验证", "人机验证", "滑动验证",
    "请按顺序点选图标", "向右滑动填充拼图", "拖动滑块", "请完成验证",
    "CAPTCHA", "Verify you are human",
)
LOGGED_IN_EMPTY_PAGE = "我的账户: 尊敬的会员\n抱歉，未找到符合条件的航班"


class SafariFlightTests(unittest.TestCase):
    def search_mock_pages(self, pages, timeout=6, cancel_on_wait=False):
        clock = [0.0]
        cancelled = [False]
        read_count = [0]
        cancel_event = Mock()
        cancel_event.is_set.side_effect = lambda: cancelled[0]

        def wait(seconds):
            clock[0] += seconds
            cancelled[0] = cancel_on_wait
            return cancelled[0]

        cancel_event.wait.side_effect = wait

        def run(args, **_kwargs):
            if args[-2] == "prepare":
                text = "ready"
            else:
                text = args[-1] + "\n" + pages[min(read_count[0], len(pages) - 1)]
                read_count[0] += 1
            return SimpleNamespace(returncode=0, stderr="", stdout=text)

        searcher = SafariFlightSearcher(
            lambda city: {"上海": "SHA", "北京": "BJS"}[city],
            cancel_event=cancel_event, timeout=timeout, runner=Mock(side_effect=run),
        )
        with patch("sys.platform", "darwin"), \
             patch("flight_ticket_mcp_server.tools.safari_flight_search.time.monotonic", side_effect=lambda: clock[0]):
            return searcher.search_flights("上海", "北京", "2026-10-20")

    def test_prices_are_ticket_prices_not_calendar_or_discount_amounts(self):
        rows = parse_safari_flights(PAGE)
        self.assertEqual([row["航班号"] for row in rows], ["KN5956", "KN5978"])
        self.assertEqual([row["价格数值"] for row in rows], [440, 480])
        self.assertEqual(rows[1]["出发机场"], "浦东国际机场")
        self.assertEqual(rows[1]["出发航站楼"], "T1")

    def test_missing_ticket_price_does_not_become_discount_price(self):
        with self.assertRaisesRegex(SafariFlightError, "票价"):
            parse_safari_flights(PAGE.replace("¥ 440 起", "价格加载中"))

    def test_empty_guest_page_is_not_treated_as_no_flights(self):
        runner = Mock()
        runner.side_effect = lambda args, **_: SimpleNamespace(
            returncode=0, stderr="", stdout="ready" if args[-2] == "prepare" else args[-1] + "\n暂无航班",
        )
        searcher = SafariFlightSearcher(lambda city: {"上海": "SHA", "北京": "BJS"}[city], runner=runner)
        with patch("sys.platform", "darwin"), self.assertRaisesRegex(SafariFlightError, "登录"):
            searcher.search_flights("上海", "北京", "2026-10-20")

    def test_login_overlay_takes_priority_over_background_ticket_rows(self):
        runner = Mock()
        runner.side_effect = lambda args, **_: SimpleNamespace(
            returncode=0, stderr="", stdout="ready" if args[-2] == "prepare" else args[-1] + "\n账号密码登录\n" + PAGE,
        )
        searcher = SafariFlightSearcher(lambda _: "SHA", runner=runner)
        with patch("sys.platform", "darwin"), self.assertRaisesRegex(SafariFlightError, "登录"):
            searcher.search_flights("上海", "北京", "2026-10-20")

    def test_verification_overrides_logged_in_empty_page(self):
        for challenge in CHALLENGES:
            with self.subTest(challenge=challenge):
                with self.assertRaises(SafariFlightError) as error:
                    self.search_mock_pages([LOGGED_IN_EMPTY_PAGE + "\n" + challenge])
                self.assertEqual(error.exception.code, "VERIFICATION_REQUIRED")

    def test_verification_overrides_existing_flight_rows(self):
        for challenge in CHALLENGES:
            with self.subTest(challenge=challenge):
                with self.assertRaises(SafariFlightError) as error:
                    self.search_mock_pages([PAGE + "\n" + challenge])
                self.assertEqual(error.exception.code, "VERIFICATION_REQUIRED")

    def test_completed_verification_allows_real_rows(self):
        for challenge in CHALLENGES:
            with self.subTest(challenge=challenge):
                rows = self.search_mock_pages([LOGGED_IN_EMPTY_PAGE + "\n" + challenge, PAGE, PAGE])
                self.assertEqual(rows, parse_safari_flights(PAGE))

    def test_late_verification_resets_previous_rows(self):
        updated_page = PAGE.replace("¥ 440 起", "¥ 450 起")
        rows = self.search_mock_pages(
            [PAGE, PAGE + "\n请按顺序点选图标", PAGE, updated_page, updated_page],
            timeout=12,
        )
        self.assertEqual(rows, parse_safari_flights(updated_page))

    def test_cleared_verification_without_rows_reports_loading_failure(self):
        with self.assertRaises(SafariFlightError) as error:
            self.search_mock_pages(["请按顺序点选图标", "航班正在加载"])
        self.assertEqual(error.exception.code, "CONTENT_NOT_READY")

    def test_cancellation_during_verification_keeps_cancelled_error(self):
        for background in (LOGGED_IN_EMPTY_PAGE, PAGE):
            with self.subTest(background_has_flights=background == PAGE):
                with self.assertRaises(SafariFlightError) as error:
                    self.search_mock_pages(
                        [background + "\n向右滑动填充拼图"], cancel_on_wait=True,
                    )
                self.assertEqual(error.exception.code, "QUERY_CANCELLED")

    def test_tab_permission_error_is_actionable(self):
        runner = Mock(return_value=SimpleNamespace(returncode=1, stderr="Not authorized (-1743)", stdout=""))
        searcher = SafariFlightSearcher(lambda _: "SHA", runner=runner)
        with self.assertRaises(SafariFlightError) as error:
            searcher._command("read", "https://flights.ctrip.com/")
        self.assertEqual(error.exception.code, "SAFARI_PERMISSION_REQUIRED")

    def test_mcp_selects_safari_without_chromium_dependency(self):
        from flight_ticket_mcp_server.tools import flight_search_tools as service
        with patch.dict("os.environ", {"FLIGHT_BROWSER_ENGINE": "safari"}), \
             patch.object(service, "DRISSION_PAGE_AVAILABLE", False), \
             patch("flight_ticket_mcp_server.tools.safari_flight_search.SafariFlightSearcher") as factory:
            factory.return_value.search_flights.return_value = parse_safari_flights(PAGE)
            response = service._search_flight_routes("上海", "北京", "2099-10-20")
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["flight_count"], 2)
        factory.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
