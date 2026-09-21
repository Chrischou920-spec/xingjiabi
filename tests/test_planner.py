from datetime import datetime
import unittest

from student_trip.demo import demo_providers
from student_trip.models import JourneyRequest, Preference, TransportMode, TransportSegment
from student_trip.providers import InMemoryProvider
from student_trip.planner import DomesticTripPlanner


def request(**changes):
    values = dict(
        origin="上海",
        destination="北京",
        outbound_after=datetime(2026, 10, 1),
        outbound_before=datetime(2026, 10, 1, 23, 59),
        return_after=datetime(2026, 10, 3),
        return_before=datetime(2026, 10, 3, 23, 59),
    )
    values.update(changes)
    return JourneyRequest(**values)


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = DomesticTripPlanner(demo_providers())

    def test_round_trip_is_jointly_combined(self):
        plans = self.planner.plan(request(), limit=10)
        self.assertEqual(len(plans), 4)
        self.assertTrue(all(plan.outbound and plan.inbound for plan in plans))

    def test_cheapest_prefers_low_total_cost(self):
        plans = self.planner.plan(request(preference=Preference.CHEAPEST), limit=4)
        self.assertEqual(plans[0].total_cost, min(plan.total_cost for plan in plans))

    def test_budget_filters_complete_round_trip(self):
        plans = self.planner.plan(request(budget=1150), limit=10)
        self.assertTrue(plans)
        self.assertTrue(all(plan.total_cost <= 1150 for plan in plans))

    def test_international_city_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "仅支持.*中国大陆城市"):
            self.planner.plan(request(destination="东京"))

    def test_one_transfer_can_mix_train_and_flight(self):
        inventory = [
            TransportSegment(TransportMode.TRAIN, "G1", "上海", "武汉", datetime(2026, 10, 1, 7), datetime(2026, 10, 1, 11), 300, arrival_station="武汉站"),
            TransportSegment(TransportMode.FLIGHT, "CZ1", "武汉", "北京", datetime(2026, 10, 1, 13), datetime(2026, 10, 1, 15), 400, departure_station="天河机场"),
        ]
        planner = DomesticTripPlanner(
            [
                InMemoryProvider(TransportMode.TRAIN, inventory),
                InMemoryProvider(TransportMode.FLIGHT, inventory),
            ],
            transfer_hubs=("武汉",),
        )
        plans = planner.plan(
            JourneyRequest(
                origin="上海",
                destination="北京",
                outbound_after=datetime(2026, 10, 1),
                outbound_before=datetime(2026, 10, 1, 23, 59),
            )
        )
        self.assertEqual(len(plans), 1)
        self.assertEqual([item.mode for item in plans[0].outbound], [TransportMode.TRAIN, TransportMode.FLIGHT])
        self.assertEqual(plans[0].local_transfer_cost, 50)


if __name__ == "__main__":
    unittest.main()
