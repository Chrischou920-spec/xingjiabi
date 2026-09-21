from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable

from .models import TransportMode, TransportSegment


class TicketProvider(ABC):
    mode: TransportMode

    @abstractmethod
    def search(
        self,
        origin: str,
        destination: str,
        earliest: datetime,
        latest: datetime,
    ) -> Iterable[TransportSegment]:
        """返回已经标准化的国内单段票务结果。"""


class InMemoryProvider(TicketProvider):
    """无需网络即可演示和测试的票务源；真实 MCP 适配器遵循同一接口。"""

    def __init__(self, mode: TransportMode, inventory: Iterable[TransportSegment]):
        self.mode = mode
        self._inventory = list(inventory)

    def search(self, origin, destination, earliest, latest):
        return [
            item
            for item in self._inventory
            if item.mode == self.mode
            and item.origin == origin
            and item.destination == destination
            and earliest <= item.departure_at <= latest
        ]

