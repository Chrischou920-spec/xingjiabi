from __future__ import annotations

import argparse
import json
from datetime import datetime

from .demo import demo_providers
from .models import JourneyRequest, Preference
from .planner import DomesticTripPlanner


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="国内大学生往返行程规划雏形")
    parser.add_argument("--origin", default="上海")
    parser.add_argument("--destination", default="北京")
    parser.add_argument("--outbound-after", type=parse_time, default=parse_time("2026-10-01T00:00"))
    parser.add_argument("--outbound-before", type=parse_time, default=parse_time("2026-10-01T23:59"))
    parser.add_argument("--return-after", type=parse_time, default=parse_time("2026-10-03T00:00"))
    parser.add_argument("--return-before", type=parse_time, default=parse_time("2026-10-03T23:59"))
    parser.add_argument("--budget", type=float)
    parser.add_argument("--preference", choices=[item.value for item in Preference], default="balanced")
    args = parser.parse_args()
    request = JourneyRequest(
        origin=args.origin,
        destination=args.destination,
        outbound_after=args.outbound_after,
        outbound_before=args.outbound_before,
        return_after=args.return_after,
        return_before=args.return_before,
        budget=args.budget,
        preference=Preference(args.preference),
    )
    plans = DomesticTripPlanner(demo_providers()).plan(request)
    print(json.dumps([plan.to_dict() for plan in plans], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

