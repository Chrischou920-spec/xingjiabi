from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .demo import demo_providers
from .domestic import MAINLAND_CITIES, validate_mainland_city
from .flight_provider import DomesticFlightMcpProvider
from .models import JourneyRequest, Preference, TransportMode
from .planner import DomesticTripPlanner
from .query_control import QueryCancelled, QueryRegistry, check_cancelled, current_query
from .train_provider import ProviderResponseError, ProviderUnavailableError, TrainMcpProvider


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
WEB_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def _parse_request(data: dict) -> JourneyRequest:
    def dt(name: str, required: bool = True):
        value = data.get(name)
        if not value and not required:
            return None
        if not value:
            raise ValueError(f"缺少字段：{name}")
        return datetime.fromisoformat(value)

    modes = tuple(TransportMode(item) for item in data.get("allowed_modes", ["train", "flight"]))
    if not modes:
        raise ValueError("请至少选择一种交通方式")
    if bool(data.get("return_after")) != bool(data.get("return_before")):
        raise ValueError("返程时间需要同时填写开始和结束")
    return JourneyRequest(
        origin=data.get("origin", ""),
        destination=data.get("destination", ""),
        outbound_after=dt("outbound_after"),
        outbound_before=dt("outbound_before"),
        return_after=dt("return_after", required=False),
        return_before=dt("return_before", required=False),
        budget=data.get("budget"),
        preference=Preference(data.get("preference", "balanced")),
        allowed_modes=modes,
        max_transfers=min(1, max(0, int(data.get("max_transfers", 1)))),
        min_transfer_minutes=int(data.get("min_transfer_minutes", 90)),
        dorm_deadline=dt("dorm_deadline", required=False),
        include_accommodation=bool(data.get("include_accommodation", True)),
        accommodation_cost=float(data.get("accommodation_cost", 200)),
    )


class AvailableProvider:
    """Keep a failed live source visible without discarding other real results."""

    def __init__(self, provider):
        self.provider = provider
        self.mode = provider.mode
        self.error: str | None = None
        self.results = []

    def search(self, origin, destination, earliest, latest):
        if self.error:
            return []
        try:
            results = list(self.provider.search(origin, destination, earliest, latest))
            self.results.extend(results)
            return results
        except (ProviderUnavailableError, ProviderResponseError) as exc:
            self.error = str(exc)
            return []


class Handler(BaseHTTPRequestHandler):
    providers = demo_providers()
    data_mode = "demo"
    queries = QueryRegistry()

    def _reply(self, status: int, data: dict | list):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Browser may have aborted after POST /cancel was acknowledged.

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._reply(200, {
                "status": "ok",
                "data_mode": self.data_mode,
                "available_modes": [provider.mode.value for provider in self.providers],
                "flight_browser_engine": os.environ.get("FLIGHT_BROWSER_ENGINE", "chromium"),
            })
        elif self.path == "/cities":
            self._reply(200, {"cities": sorted(MAINLAND_CITIES)})
        elif self.path in WEB_FILES:
            filename, content_type = WEB_FILES[self.path]
            try:
                body = (WEB_ROOT / filename).read_bytes()
            except OSError:
                self._reply(404, {"error": "not_found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._reply(404, {"error": "not_found"})

    def do_POST(self):
        if self.path not in ("/plan", "/cancel"):
            self._reply(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("请求内容必须是 JSON 对象")
            raw_id = data.get("query_id")
            if self.path == "/cancel" and not raw_id:
                raise ValueError("取消查询需要 query_id")
            query_id = uuid.UUID(str(raw_id)).hex if raw_id else uuid.uuid4().hex
            if self.path == "/cancel":
                self.queries.cancel(query_id)
                self._reply(200, {"status": "cancelling", "query_id": query_id})
                return
            control = self.queries.begin(query_id)
            token = current_query.set(control)
            try:
                check_cancelled()
                self._plan(data)
            finally:
                current_query.reset(token)
                self.queries.finish(query_id)
        except QueryCancelled:
            self._reply(499, {"error": "query_cancelled", "message": "查询已取消"})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._reply(400, {"error": "invalid_request", "message": str(exc)})

    def _plan(self, data):
        request = _parse_request(data)
        available_modes = {provider.mode for provider in self.providers}
        missing_modes = set(request.allowed_modes) - available_modes
        if missing_modes:
            names = "、".join(mode.value for mode in sorted(missing_modes, key=lambda item: item.value))
            raise ValueError(f"当前数据模式不支持：{names}")
        providers = [AvailableProvider(provider) for provider in self.providers]
        plans = DomesticTripPlanner(providers).plan(request)
        check_cancelled()
        source_errors = {provider.mode.value: provider.error for provider in providers if provider.error}
        flight_rows = next((provider.results for provider in providers if provider.mode == TransportMode.FLIGHT), [])

        def flight_group(origin, destination):
            unique = {
                (item.number, item.departure_at, item.arrival_at, item.price): item
                for item in flight_rows
                if item.origin == origin and item.destination == destination
            }
            return [item.to_dict() for item in sorted(unique.values(), key=lambda item: (item.departure_at, item.price))]
        origin = validate_mainland_city(request.origin)
        destination = validate_mainland_city(request.destination)
        flights = {
            "outbound": flight_group(origin, destination),
            "inbound": flight_group(destination, origin) if request.is_round_trip else [],
        }
        if source_errors and not plans and not any(flights.values()):
            self._reply(503, {
                "error": "provider_unavailable",
                "message": "票务来源暂不可用，无法生成完整方案",
                "source_errors": source_errors,
            })
            return
        self._reply(200, {
            "plans": [plan.to_dict() for plan in plans],
            "flights": flights,
            "flight_browser_engine": os.environ.get("FLIGHT_BROWSER_ENGINE", "chromium"),
            "data_mode": self.data_mode,
            "queried_at": datetime.now().astimezone().isoformat(),
            "source_errors": source_errors,
        })

    def log_message(self, format, *args):
        return


def main() -> None:
    data_mode = os.environ.get("STUDENT_TRIP_DATA_MODE", "demo").lower()
    active_providers = []
    if data_mode == "live_train":
        train_provider = TrainMcpProvider.from_bundled_service()
        active_providers.append(train_provider)
        Handler.providers = active_providers
        Handler.data_mode = "live_train"
    elif data_mode == "live_flight":
        flight_provider = DomesticFlightMcpProvider.from_bundled_service()
        active_providers.append(flight_provider)
        Handler.providers = active_providers
        Handler.data_mode = "live_flight"
    elif data_mode == "live_all":
        train_provider = TrainMcpProvider.from_bundled_service()
        flight_provider = DomesticFlightMcpProvider.from_bundled_service()
        active_providers.extend([train_provider, flight_provider])
        Handler.providers = active_providers
        Handler.data_mode = "live_all"
    elif data_mode != "demo":
        raise SystemExit(
            "STUDENT_TRIP_DATA_MODE 仅支持 demo、live_train、live_flight 或 live_all"
        )

    port = int(os.environ.get("STUDENT_TRIP_PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"行价比网站已启动：http://127.0.0.1:{port}")
    print(f"GET /health · GET /cities · POST /plan · 数据模式：{Handler.data_mode}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for provider in active_providers:
            provider.close()


if __name__ == "__main__":
    main()
