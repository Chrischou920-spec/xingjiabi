from __future__ import annotations

from datetime import timedelta
from itertools import product

from .domestic import validate_mainland_city
from .models import JourneyRequest, Preference, RoutePlan, TransportSegment
from .providers import TicketProvider


class DomesticTripPlanner:
    """从上游项目的“程序计算、AI解释”原则重构的纯计算内核。"""

    def __init__(self, providers: list[TicketProvider], transfer_hubs: tuple[str, ...] = ()):
        self.providers = {provider.mode: provider for provider in providers}
        self.transfer_hubs = transfer_hubs

    def plan(self, request: JourneyRequest, limit: int = 3) -> list[RoutePlan]:
        origin = validate_mainland_city(request.origin)
        destination = validate_mainland_city(request.destination)
        if origin == destination:
            raise ValueError("出发地和目的地不能相同")
        if request.outbound_after >= request.outbound_before:
            raise ValueError("去程时间范围无效")
        if request.is_round_trip and request.return_after >= request.return_before:
            raise ValueError("返程时间范围无效")

        outward = self._search_routes(
            origin, destination, request.outbound_after, request.outbound_before, request
        )
        if not outward:
            return []
        inward: list[list[TransportSegment]] = [[]]
        if request.is_round_trip:
            inward = self._search_routes(
                destination, origin, request.return_after, request.return_before, request
            )
            if not inward:
                return []

        plans = [self._evaluate(list(out), list(back), request) for out, back in product(outward, inward)]
        plans = [plan for plan in plans if request.budget is None or plan.total_cost <= request.budget]
        self._score(plans, request.preference)
        return sorted(plans, key=lambda item: item.score)[:limit]

    def _search_routes(self, origin, destination, earliest, latest, request):
        routes = []
        for mode in request.allowed_modes:
            provider = self.providers.get(mode)
            if provider:
                routes.extend([item] for item in provider.search(origin, destination, earliest, latest))
        if request.max_transfers >= 1:
            for hub in self.transfer_hubs:
                if hub in (origin, destination):
                    continue
                first_legs: list[TransportSegment] = []
                second_legs: list[TransportSegment] = []
                for mode in request.allowed_modes:
                    provider = self.providers.get(mode)
                    if not provider:
                        continue
                    first_legs.extend(provider.search(origin, hub, earliest, latest))
                    second_legs.extend(
                        provider.search(hub, destination, earliest, latest + timedelta(hours=18))
                    )
                for first, second in product(first_legs, second_legs):
                    wait = int((second.departure_at - first.arrival_at).total_seconds() // 60)
                    if request.min_transfer_minutes <= wait <= 8 * 60:
                        routes.append([first, second])
        return routes

    def _evaluate(self, outbound, inbound, request):
        plan = RoutePlan(outbound=outbound, inbound=inbound)
        for group in (outbound, inbound):
            if not group:
                continue
            if group[0].departure_at.hour < 6 or group[-1].arrival_at.hour >= 23:
                plan.warnings.append("包含深夜或凌晨出行")
                plan.risk_penalty += 15
            if request.include_accommodation and group[-1].arrival_at.date() > group[0].departure_at.date():
                plan.accommodation_cost += request.accommodation_cost
                plan.warnings.append("跨夜行程已计入住宿成本")
            if len(group) > 1:
                plan.warnings.append("中转方案，请预留换乘时间")
                if group[0].arrival_station and group[1].departure_station and group[0].arrival_station != group[1].departure_station:
                    plan.local_transfer_cost += 50
                    plan.risk_penalty += 10
                    plan.warnings.append("可能涉及异站换乘，暂按 ¥50 计入市内交通")
        if request.dorm_deadline and inbound and inbound[-1].arrival_at > request.dorm_deadline:
            plan.warnings.append("晚于返校/门禁时间")
            plan.risk_penalty += 100
        return plan

    @staticmethod
    def _score(plans: list[RoutePlan], preference: Preference) -> None:
        if not plans:
            return
        max_cost = max(plan.total_cost for plan in plans) or 1
        max_duration = max(plan.total_duration_minutes for plan in plans) or 1
        weights = {
            Preference.CHEAPEST: (1.00, 0.00),
            Preference.BALANCED: (0.55, 0.45),
            Preference.FASTEST: (0.00, 1.00),
        }
        cost_weight, time_weight = weights[preference]
        for plan in plans:
            plan.score = round(
                100 * (cost_weight * plan.total_cost / max_cost
                       + time_weight * plan.total_duration_minutes / max_duration)
                + plan.risk_penalty,
                2,
            )
