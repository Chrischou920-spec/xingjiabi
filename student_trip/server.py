from __future__ import annotations

import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .demo import demo_providers
from .flight_provider import DomesticFlightMcpProvider
from .models import JourneyRequest, Preference, TransportMode
from .planner import DomesticTripPlanner
from .train_provider import ProviderUnavailableError, TrainMcpProvider


def _parse_request(data: dict) -> JourneyRequest:
    def dt(name: str, required: bool = True):
        value = data.get(name)
        if not value and not required:
            return None
        if not value:
            raise ValueError(f"缺少字段：{name}")
        return datetime.fromisoformat(value)

    modes = tuple(TransportMode(item) for item in data.get("allowed_modes", ["train", "flight"]))
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


class Handler(BaseHTTPRequestHandler):
    planner = DomesticTripPlanner(demo_providers())
    data_mode = "demo"

    def _reply(self, status: int, data: dict | list):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._reply(200, {"status": "ok", "data_mode": self.data_mode})
        else:
            self._reply(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/plan":
            self._reply(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            plans = self.planner.plan(_parse_request(data))
            self._reply(200, {"plans": [plan.to_dict() for plan in plans]})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._reply(400, {"error": "invalid_request", "message": str(exc)})
        except ProviderUnavailableError as exc:
            self._reply(503, {"error": "train_provider_unavailable", "message": str(exc)})

    def log_message(self, format, *args):
        return


def main() -> None:
    data_mode = os.environ.get("STUDENT_TRIP_DATA_MODE", "demo").lower()
    active_providers = []
    if data_mode == "live_train":
        train_provider = TrainMcpProvider.from_bundled_service()
        active_providers.append(train_provider)
        Handler.planner = DomesticTripPlanner([train_provider])
        Handler.data_mode = "live_train"
    elif data_mode == "live_flight":
        flight_provider = DomesticFlightMcpProvider.from_bundled_service()
        active_providers.append(flight_provider)
        Handler.planner = DomesticTripPlanner([flight_provider])
        Handler.data_mode = "live_flight"
    elif data_mode == "live_all":
        train_provider = TrainMcpProvider.from_bundled_service()
        flight_provider = DomesticFlightMcpProvider.from_bundled_service()
        active_providers.extend([train_provider, flight_provider])
        Handler.planner = DomesticTripPlanner(active_providers)
        Handler.data_mode = "live_all"
    elif data_mode != "demo":
        raise SystemExit(
            "STUDENT_TRIP_DATA_MODE 仅支持 demo、live_train、live_flight 或 live_all"
        )

    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("行程规划接口已启动：http://127.0.0.1:8765")
    print(f"GET /health · POST /plan · 数据模式：{Handler.data_mode}")
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
