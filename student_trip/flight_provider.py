from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .domestic import validate_mainland_city
from .mcp_client import McpCallError, McpClientError, McpProcessClient
from .models import TransportMode, TransportSegment
from .providers import TicketProvider
from .train_provider import ProviderResponseError, ProviderUnavailableError, ToolCaller


class DomesticFlightMcpProvider(TicketProvider):
    mode = TransportMode.FLIGHT

    def __init__(self, client: ToolCaller, retries: int = 1):
        self.client = client
        self.retries = retries

    @classmethod
    def from_bundled_service(
        cls,
        project_root: str | Path | None = None,
        python_executable: str | Path | None = None,
    ) -> "DomesticFlightMcpProvider":
        root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
        service_dir = root / "services" / "FlightTicketMCP"
        if not (service_dir / "flight_ticket_mcp_server").exists():
            raise ProviderUnavailableError(f"找不到 FlightTicketMCP：{service_dir}")
        executable = str(
            python_executable
            or os.environ.get("FLIGHT_MCP_PYTHON")
            or sys.executable
        )
        if not os.path.isabs(executable) and os.path.sep in executable:
            # 不使用 resolve()：虚拟环境的 python 通常是符号链接，解析到基础
            # 解释器后会丢失 venv 的 site-packages。
            executable = str(Path(executable).expanduser().absolute())
        env = os.environ.copy()
        env.update(
            {
                "MCP_TRANSPORT": "stdio",
                "PYTHONUNBUFFERED": "1",
                "NO_COLOR": "1",
                "FORCE_COLOR": "0",
            }
        )
        browser_path = cls._discover_chromium(env.get("FLIGHT_BROWSER_PATH"))
        if browser_path:
            env["FLIGHT_BROWSER_PATH"] = browser_path
        client = McpProcessClient(
            executable,
            ["-m", "flight_ticket_mcp_server"],
            cwd=service_dir,
            env=env,
            startup_timeout=45,
        )
        return cls(client)

    @staticmethod
    def _discover_chromium(configured: str | None = None) -> str | None:
        candidates = []
        if configured:
            candidates.append(Path(configured).expanduser())
        candidates.extend(
            [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            ]
        )
        playwright_root = Path.home() / "Library" / "Caches" / "ms-playwright"
        candidates.extend(
            sorted(
                playwright_root.glob(
                    "chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
                ),
                reverse=True,
            )
        )
        candidates.extend(
            sorted(
                playwright_root.glob(
                    "chromium_headless_shell-*/chrome-headless-shell-mac-arm64/chrome-headless-shell"
                ),
                reverse=True,
            )
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    def search(self, origin, destination, earliest, latest):
        origin = validate_mainland_city(origin)
        destination = validate_mainland_city(destination)
        if earliest > latest:
            raise ValueError("最早出发时间不能晚于最晚出发时间")

        segments: list[TransportSegment] = []
        for travel_date in self._dates_between(earliest.date(), latest.date()):
            response = self._search_date(origin, destination, travel_date)
            for flight in response:
                segment = self._normalize_flight(flight, origin, destination, travel_date)
                if segment and earliest <= segment.departure_at <= latest:
                    segments.append(segment)

        unique: dict[tuple[Any, ...], TransportSegment] = {}
        for item in segments:
            key = (item.number, item.departure_at, item.arrival_at, item.price)
            unique[key] = item
        return sorted(unique.values(), key=lambda item: (item.departure_at, item.price))

    def _search_date(self, origin: str, destination: str, travel_date: date):
        text = self._call(
            "searchFlightRoutes",
            {
                "departure_city": origin,
                "destination_city": destination,
                "departure_date": travel_date.isoformat(),
            },
            timeout=150,
        )
        data = self._json(text)
        if not isinstance(data, dict):
            raise ProviderResponseError("航班响应不是对象")
        if data.get("status") != "success":
            code = data.get("error_code", "UNKNOWN")
            message = data.get("message", "航班查询失败")
            if "WhaleGuard" in message or "拦截" in message:
                message = f"携程反爬拦截当前网络；请更换网络、关闭异常代理或稍后重试。原始信息：{message}"
            raise ProviderUnavailableError(f"航班服务错误 {code}：{message}")
        flights = data.get("flights", [])
        if not isinstance(flights, list):
            raise ProviderResponseError("航班列表不是数组")
        return flights

    def _call(self, name: str, arguments: dict[str, Any], timeout: float):
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                return self.client.call_tool_text(name, arguments, timeout=timeout)
            except (McpClientError, McpCallError) as exc:
                last_error = exc
        detail = str(last_error or "未知错误")
        if "验证码" in detail or "verification" in detail.lower():
            detail = f"需要在浏览器中完成验证码：{detail}"
        raise ProviderUnavailableError(f"国内机票 MCP 调用失败：{detail}") from last_error

    @staticmethod
    def _json(text: str):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(f"航班响应不是合法 JSON：{text[:160]}") from exc

    @classmethod
    def _normalize_flight(cls, flight, origin, destination, travel_date):
        if not isinstance(flight, dict):
            return None
        flight_type = str(flight.get("航班类型") or "直达")
        if flight_type != "直达":
            return None
        number = str(flight.get("航班号") or "").strip()
        if not number or "/" in number:
            return None
        departure_raw = str(flight.get("出发时间") or "")
        arrival_raw = str(flight.get("到达时间") or "")
        try:
            departure_at = datetime.combine(travel_date, cls._time(departure_raw))
            arrival_at = datetime.combine(travel_date, cls._time(arrival_raw))
        except ValueError:
            return None
        day_match = re.search(r"\+(\d+)", arrival_raw)
        if day_match:
            arrival_at += timedelta(days=int(day_match.group(1)))
        elif arrival_at < departure_at:
            arrival_at += timedelta(days=1)

        amount = flight.get("价格数值")
        if amount is None:
            match = re.search(r"(\d+(?:\.\d+)?)", str(flight.get("价格") or "" ).replace(",", ""))
            amount = match.group(1) if match else None
        try:
            price = float(amount)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None

        departure_station = cls._station(flight, "出发机场", "出发航站楼", origin)
        arrival_station = cls._station(flight, "到达机场", "到达航站楼", destination)
        return TransportSegment(
            mode=TransportMode.FLIGHT,
            number=number,
            origin=origin,
            destination=destination,
            departure_at=departure_at,
            arrival_at=arrival_at,
            price=price,
            departure_station=departure_station,
            arrival_station=arrival_station,
            seat_or_cabin=str(flight.get("舱位") or "经济舱"),
            source="携程",
        )

    @staticmethod
    def _time(value: str):
        match = re.search(r"([01]?\d|2[0-3]):[0-5]\d", value)
        if not match:
            raise ValueError("时间格式错误")
        return datetime.strptime(match.group(0), "%H:%M").time()

    @staticmethod
    def _station(data, airport_key, terminal_key, fallback):
        airport = str(data.get(airport_key) or fallback).strip()
        terminal = str(data.get(terminal_key) or "").strip()
        return f"{airport}{terminal}" if terminal and terminal not in airport else airport

    @staticmethod
    def _dates_between(first: date, last: date):
        current = first
        while current <= last:
            yield current
            current += timedelta(days=1)

    def close(self):
        close = getattr(self.client, "close", None)
        if close:
            close()
