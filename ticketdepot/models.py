"""Plain data objects shared by the parser, the store and the rules.

All times are naive Europe/Berlin local times, the way tickets and IRIS print them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass
class Leg:
    train: str  # as printed on the ticket, e.g. "ICE 725"
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    dep_platform: str | None = None
    arr_platform: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["departure"] = self.departure.isoformat()
        d["arrival"] = self.arrival.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Leg:
        return cls(**{**d, "departure": _dt(d["departure"]), "arrival": _dt(d["arrival"])})


@dataclass
class Journey:
    """One direction of a ticket (a Hin- und Rückfahrt ticket has two)."""

    label: str  # "Einfache Fahrt", "Hinfahrt", "Rückfahrt"
    legs: list[Leg]

    @property
    def origin(self) -> str:
        return self.legs[0].origin

    @property
    def destination(self) -> str:
        return self.legs[-1].destination

    @property
    def departure(self) -> datetime:
        return self.legs[0].departure

    @property
    def arrival(self) -> datetime:
        return self.legs[-1].arrival

    def to_dict(self) -> dict:
        return {"label": self.label, "legs": [leg.to_dict() for leg in self.legs]}

    @classmethod
    def from_dict(cls, d: dict) -> Journey:
        return cls(label=d["label"], legs=[Leg.from_dict(leg) for leg in d["legs"]])


@dataclass
class Ticket:
    order_number: str
    fare: str  # "Super Sparpreis", "Sparpreis", "Flexpreis", ...
    trip_kind: str  # "Einfache Fahrt", "Hin- und Rückfahrt"
    price_eur: float
    journeys: list[Journey]
    travel_class: str | None = None
    travellers: str | None = None
    ticket_code: str | None = None
    booked_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    zugbindung: list[str] = field(default_factory=list)

    @property
    def price_basis_per_journey(self) -> float:
        # DB: a Hin- und Rückfahrt on one ticket is compensated on half the price.
        return round(self.price_eur / max(len(self.journeys), 1), 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["journeys"] = [j.to_dict() for j in self.journeys]
        for key in ("booked_at", "valid_from", "valid_to"):
            value = getattr(self, key)
            d[key] = value.isoformat() if value else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Ticket:
        return cls(
            **{
                **d,
                "journeys": [Journey.from_dict(j) for j in d["journeys"]],
                "booked_at": _dt(d.get("booked_at")),
                "valid_from": _dt(d.get("valid_from")),
                "valid_to": _dt(d.get("valid_to")),
            }
        )
