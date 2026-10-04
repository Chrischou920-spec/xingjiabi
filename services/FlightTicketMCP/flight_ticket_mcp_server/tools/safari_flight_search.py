"""Read ticket listings from a normal Safari tab using its existing login."""
from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from pathlib import Path


VERIFICATION_TEXT = re.compile(
    r"验证码|安全验证|人机验证|滑动验证|请按顺序点选|向右滑动填充拼图|"
    r"拖动滑块|请完成验证|captcha|verify you are human",
    re.IGNORECASE,
)


class SafariFlightError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def parse_safari_flights(text: str) -> list[dict]:
    # Restrict parsing to the actual list, excluding calendar prices and footer.
    listing = re.split(r"最近更新时间\s*[:：]?", text, maxsplit=1)
    if len(listing) < 2:
        return []
    listing = re.split(r"在线客服|航班信息免责声明|旅游资讯", listing[1], maxsplit=1)[0]
    rows = []
    for block in re.split(r"订票", listing):
        numbers = list(dict.fromkeys(re.findall(r"\b[A-Z0-9]{2}\d{3,4}\b", block)))
        if not numbers:
            continue
        times = list(re.finditer(r"(?:[01]\d|2[0-3]):[0-5]\d(?:\s*\+\d+(?:天)?)?", block))
        # Transfer combinations are not priced as individual direct segments.
        if len(numbers) != 1 or "通程" in block or re.search(r"转\d+次", block):
            continue
        if len(times) < 2:
            raise SafariFlightError("PARSE_FAILED", "Safari 航班卡片缺少起降时间")
        departure, arrival = times[-2:]
        price = re.search(r"[¥￥]\s*([\d,]+(?:\.\d+)?)\s*起", block[arrival.end():])
        if not price:
            raise SafariFlightError("PARSE_FAILED", "Safari 航班卡片缺少可核实票价")
        airline = re.search(r"([\u4e00-\u9fff]{2,16}(?:航空|国航))", block[:departure.start()])
        def airport(part):
            match = re.search(r"([\u4e00-\u9fffA-Za-z·]+机场)(?:\s*(T\d+))?", part)
            return (match.group(1), match.group(2) or "") if match else ("", "")
        origin, origin_terminal = airport(block[departure.end():arrival.start()])
        destination, destination_terminal = airport(block[arrival.end():])
        rows.append({
            "航班号": numbers[0], "航班类型": "直达",
            "航空公司": airline.group(1) if airline else "未知",
            "出发时间": re.sub(r"\s+", "", departure.group()),
            "到达时间": re.sub(r"\s+", "", arrival.group()),
            "出发机场": origin, "出发航站楼": origin_terminal,
            "到达机场": destination, "到达航站楼": destination_terminal,
            "价格": f"¥{price.group(1)}起",
            "价格数值": float(price.group(1).replace(",", "")),
            "舱位": "经济舱" if "经济舱" in block else "页面最低报价",
        })
    return rows


class SafariFlightSearcher:
    def __init__(self, get_airport_code, cancel_event=None, timeout=90, runner=subprocess.run):
        self.get_airport_code = get_airport_code
        self.cancel_event = cancel_event or threading.Event()
        self.timeout = timeout
        self.runner = runner
        self.script = Path(__file__).with_name("safari_page.applescript")

    def _command(self, action, url):
        if self.cancel_event.is_set():
            raise SafariFlightError("QUERY_CANCELLED", "航班查询已取消")
        try:
            result = self.runner(
                ["/usr/bin/osascript", str(self.script), action, url],
                capture_output=True, text=True, timeout=12, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SafariFlightError("SAFARI_TIMEOUT", "Safari 读取超时，请确认自动化授权已完成") from exc
        if result.returncode:
            error = result.stderr
            if "1743" in error or "Not authorized" in error or "不允许" in error:
                raise SafariFlightError("SAFARI_PERMISSION_REQUIRED", "需要允许本地查询程序自动化访问 Safari")
            if "SAFARI_CTRIP_TAB_REQUIRED" in error:
                raise SafariFlightError("SAFARI_CTRIP_TAB_REQUIRED", "请先在 Safari 打开已登录的携程机票页面")
            if "SAFARI_QUERY_TAB_" in error:
                raise SafariFlightError("SAFARI_QUERY_CHANGED", "查询中的 Safari 标签页被关闭或更改，请重新查询")
            raise SafariFlightError("SAFARI_READ_FAILED", "无法读取 Safari 携程页面")
        return result.stdout.rstrip("\n")

    def search_flights(self, origin, destination, departure_date):
        if sys.platform != "darwin":
            raise SafariFlightError("SAFARI_NOT_AVAILABLE", "Safari 数据源仅支持 macOS")
        origin_code = self.get_airport_code(origin).lower()
        destination_code = self.get_airport_code(destination).lower()
        url = (f"https://flights.ctrip.com/online/list/oneway-{origin_code}-{destination_code}"
               f"?depdate={departure_date}&cabin=y_s_c_f#xingjiabi-live")
        self._command("prepare", url)
        deadline = time.monotonic() + self.timeout
        previous = None
        verification_pending = False
        while time.monotonic() < deadline:
            response = self._command("read", url)
            actual_url, _, text = response.partition("\n")
            if actual_url != url:
                raise SafariFlightError("SAFARI_QUERY_CHANGED", "Safari 页面与当前查询条件不一致")
            if "whaleguard block" in text.lower() or "访问受限" in text:
                raise SafariFlightError("SOURCE_BLOCKED", "携程限制了当前访问")
            if re.search(r"账号密码登录|请登录后|请先登录|登录后继续", text):
                raise SafariFlightError("LOGIN_REQUIRED", "请在 Safari 携程页面完成登录后重新查询")
            verification_pending = bool(VERIFICATION_TEXT.search(text))
            if verification_pending:
                # A challenge can cover both an empty state and old ticket rows.
                # Never accept either until the person completes verification.
                previous = None
            else:
                rows = parse_safari_flights(text)
                if rows and rows == previous:
                    return rows
                previous = rows
                if re.search(r"(?:暂无|未找到|没有找到)[^。\n]{0,40}航班|无搜索结果", text):
                    if not re.search(r"我的账户|尊敬的会员|退出登录", text):
                        raise SafariFlightError("LOGIN_REQUIRED", "携程返回空列表，请在 Safari 确认登录后重新查询")
                    return []
            if self.cancel_event.wait(2):
                raise SafariFlightError("QUERY_CANCELLED", "航班查询已取消")
        if verification_pending:
            raise SafariFlightError("VERIFICATION_REQUIRED", "请在 Safari 携程查询标签中完成人工验证后重新查询")
        raise SafariFlightError("CONTENT_NOT_READY", "Safari 航班列表尚未加载完成，请保持携程查询标签打开并稍后重试")

    def close(self):
        # The dedicated tab retains the login context for subsequent searches.
        pass
