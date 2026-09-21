from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TransportMode(str, Enum):
    TRAIN = "train"
    FLIGHT = "flight"


class Preference(str, Enum):
    CHEAPEST = "cheapest"
    BALANCED = "balanced"
    FASTEST = "fastest"


@dataclass(frozen=True)
class TransportSegment:
    mode: TransportMode
    number: str
    origin: str
    destination: str
    departure_at: datetime
    arrival_at: datetime
    price: float
    departure_station: str = ""
    arrival_station: str = ""
    seat_or_cabin: str = ""
    source: str = ""

    @property
    def duration_minutes(self) -> int:
        return max(0, int((self.arrival_at - self.departure_at).total_seconds() // 60))


@dataclass(frozen=True)
class JourneyRequest:
    origin: str
    destination: str
    outbound_after: datetime
    outbound_before: datetime
    return_after: datetime | None = None
    return_before: datetime | None = None
    budget: float | None = None
    preference: Preference = Preference.BALANCED
    allowed_modes: tuple[TransportMode, ...] = (
        TransportMode.TRAIN,
        TransportMode.FLIGHT,
    )
    max_transfers: int = 1
    min_transfer_minutes: int = 90
    dorm_deadline: datetime | None = None
    include_accommodation: bool = True
    accommodation_cost: float = 200

    @property
    def is_round_trip(self) -> bool:
        return self.return_after is not None and self.return_before is not None


@dataclass
class RoutePlan:
    outbound: list[TransportSegment]
    inbound: list[TransportSegment] = field(default_factory=list)
    accommodation_cost: float = 0
    local_transfer_cost: float = 0
    risk_penalty: float = 0
    warnings: list[str] = field(default_factory=list)
    score: float = 0

    @property
    def segments(self) -> list[TransportSegment]:
        return [*self.outbound, *self.inbound]

    @property
    def ticket_cost(self) -> float:
        return sum(segment.price for segment in self.segments)

    @property
    def total_cost(self) -> float:
        return self.ticket_cost + self.accommodation_cost + self.local_transfer_cost

    @property
    def total_duration_minutes(self) -> int:
        groups = [group for group in (self.outbound, self.inbound) if group]
        return sum(
            int((group[-1].arrival_at - group[0].departure_at).total_seconds() // 60)
            for group in groups
        )

    def to_dict(self) -> dict[str, Any]:
        def encode(segment: TransportSegment) -> dict[str, Any]:
            data = asdict(segment)
            data["mode"] = segment.mode.value
            data["departure_at"] = segment.departure_at.isoformat()
            data["arrival_at"] = segment.arrival_at.isoformat()
            data["duration_minutes"] = segment.duration_minutes
            return data

        return {
            "outbound": [encode(item) for item in self.outbound],
            "inbound": [encode(item) for item in self.inbound],
            "ticket_cost": self.ticket_cost,
            "accommodation_cost": self.accommodation_cost,
            "local_transfer_cost": self.local_transfer_cost,
            "total_cost": self.total_cost,
            "total_duration_minutes": self.total_duration_minutes,
            "risk_penalty": self.risk_penalty,
            "warnings": self.warnings,
            "score": self.score,
        }

