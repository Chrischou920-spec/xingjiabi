from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol

from .mcp_client import McpCallError, McpClientError, McpProcessClient
from .models import TransportMode, TransportSegment
from .providers import TicketProvider


class ProviderUnavailableError(RuntimeError):
    pass


class ProviderResponseError(RuntimeError):
    pass


class ToolCaller(Protocol):
    def call_tool_text(self, name: str, arguments: dict[str, Any], timeout: float = 60) -> str:
        ...


class TrainMcpProvider(TicketProvider):
    mode = TransportMode.TRAIN

    def __init__(self, client: ToolCaller, retries: int = 2):
        self.client = client
        self.retries = retries
        self._station_cache: dict[str, str] = {}

    @classmethod
    def from_bundled_service(cls, project_root: str | Path | None = None) -> "TrainMcpProvider":
        root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
        service_dir = root / "services" / "12306-mcp"
        script = service_dir / "build" / "index.js"
        if not script.exists():
            raise ProviderUnavailableError(f"找不到 12306 MCP：{script}")
        client = McpProcessClient("node", [str(script)], cwd=service_dir, startup_timeout=45)
        return cls(client)

    def search(self, origin, destination, earliest, latest):
        if earliest > latest:
            raise ValueError("最早出发时间不能晚于最晚出发时间")
        from_code, to_code = self._station_codes(origin, destination)
        segments: list[TransportSegment] = []
        for travel_date in self._dates_between(earliest.date(), latest.date()):
            start_hour = earliest.hour if travel_date == earliest.date() else 0
            end_hour = latest.hour + (1 if latest.minute or latest.second else 0) if travel_date == latest.date() else 24
            end_hour = min(24, end_hour)
            tickets = self._get_tickets(travel_date, from_code, to_code, start_hour, end_hour)
            for ticket in tickets:
                segments.extend(self._normalize_ticket(ticket, origin, destination))

        filtered = [item for item in segments if earliest <= item.departure_at <= latest]
        unique: dict[tuple[Any, ...], TransportSegment] = {}
        for item in filtered:
            key = (item.number, item.departure_at, item.arrival_at, item.seat_or_cabin, item.price)
            unique[key] = item
        return sorted(unique.values(), key=lambda item: (item.departure_at, item.price))

    def _station_codes(self, origin: str, destination: str) -> tuple[str, str]:
        missing = [city for city in (origin, destination) if city not in self._station_cache]
        if missing:
            text = self._call("get-station-code-of-citys", {"citys": "|".join(missing)}, timeout=30)
            data = self._json(text, "车站代码")
            if not isinstance(data, dict):
                raise ProviderResponseError("车站代码响应不是对象")
            for city in missing:
                entry = data.get(city, {})
                code = entry.get("station_code") if isinstance(entry, dict) else None
                if not code:
                    raise ProviderResponseError(f"12306 未找到城市“{city}”的车站代码")
                self._station_cache[city] = str(code)
        return self._station_cache[origin], self._station_cache[destination]

    def _get_tickets(self, travel_date, from_code, to_code, start_hour, end_hour):
        text = self._call(
            "get-tickets",
            {
                "date": travel_date.isoformat(),
                "fromStation": from_code,
                "toStation": to_code,
                "earliestStartTime": start_hour,
                "latestStartTime": end_hour,
                "limitedNum": 50,
                "format": "json",
            },
            timeout=45,
        )
        if text.startswith("Error:"):
            raise ProviderUnavailableError(text)
        data = self._json(text, "余票")
        if not isinstance(data, list):
            raise ProviderResponseError("余票响应不是数组")
        return data

    def _call(self, name: str, arguments: dict[str, Any], timeout: float) -> str:
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                return self.client.call_tool_text(name, arguments, timeout=timeout)
            except (McpClientError, McpCallError) as exc:
                last_error = exc
        raise ProviderUnavailableError(f"12306 MCP 调用失败：{last_error}") from last_error

    @staticmethod
    def _json(text: str, label: str):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(f"{label}响应不是合法 JSON：{text[:160]}") from exc

    @classmethod
    def _normalize_ticket(cls, ticket: dict[str, Any], origin: str, destination: str):
        number = str(ticket.get("start_train_code") or ticket.get("station_train_code") or "")
        if not number:
            return []
        try:
            departure_at = cls._datetime(ticket.get("start_date"), ticket.get("start_time"))
            arrival_at = cls._datetime(ticket.get("arrive_date"), ticket.get("arrive_time"))
        except (TypeError, ValueError):
            return []
        if arrival_at < departure_at:
            arrival_at += timedelta(days=1)

        segments = []
        for price in ticket.get("prices") or []:
            if not isinstance(price, dict) or not cls._available(price.get("num")):
                continue
            try:
                amount = float(price.get("price"))
            except (TypeError, ValueError):
                continue
            if amount <= 0:
                continue
            segments.append(
                TransportSegment(
                    mode=TransportMode.TRAIN,
                    number=number,
                    origin=origin,
                    destination=destination,
                    departure_at=departure_at,
                    arrival_at=arrival_at,
                    price=amount,
                    departure_station=str(ticket.get("from_station") or origin),
                    arrival_station=str(ticket.get("to_station") or destination),
                    seat_or_cabin=str(price.get("seat_name") or "未知席别"),
                    source="12306",
                )
            )
        return segments

    @staticmethod
    def _datetime(date_value: Any, time_value: Any) -> datetime:
        raw_date = re.sub(r"\D", "", str(date_value or ""))
        if len(raw_date) != 8:
            raise ValueError("日期格式错误")
        parsed_date = datetime.strptime(raw_date, "%Y%m%d").date()
        parsed_time = datetime.strptime(str(time_value), "%H:%M").time()
        return datetime.combine(parsed_date, parsed_time)

    @staticmethod
    def _available(value: Any) -> bool:
        text = str(value or "").strip()
        return text not in {"", "0", "无", "--", "候补", "售罄", "null", "None"}

    @staticmethod
    def _dates_between(first: date, last: date):
        current = first
        while current <= last:
            yield current
            current += timedelta(days=1)

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close:
            close()

