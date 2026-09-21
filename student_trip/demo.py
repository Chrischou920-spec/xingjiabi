from datetime import datetime

from .models import TransportMode, TransportSegment
from .providers import InMemoryProvider


def demo_providers() -> list[InMemoryProvider]:
    rows = [
        TransportSegment(TransportMode.TRAIN, "G10", "上海", "北京", datetime(2026, 10, 1, 8), datetime(2026, 10, 1, 12, 36), 553, "上海虹桥", "北京南", "二等座", "demo"),
        TransportSegment(TransportMode.FLIGHT, "MU5101", "上海", "北京", datetime(2026, 10, 1, 9), datetime(2026, 10, 1, 11, 20), 680, "虹桥机场", "首都机场", "经济舱", "demo"),
        TransportSegment(TransportMode.TRAIN, "G21", "北京", "上海", datetime(2026, 10, 3, 17), datetime(2026, 10, 3, 21, 37), 553, "北京南", "上海虹桥", "二等座", "demo"),
        TransportSegment(TransportMode.FLIGHT, "CA1501", "北京", "上海", datetime(2026, 10, 3, 19), datetime(2026, 10, 3, 21, 15), 620, "首都机场", "虹桥机场", "经济舱", "demo"),
    ]
    return [
        InMemoryProvider(TransportMode.TRAIN, rows),
        InMemoryProvider(TransportMode.FLIGHT, rows),
    ]

