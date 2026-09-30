"""What a journey is worth after the fact, and what to do next (DB Fahrgastrechte).

Everything policy-related lives here: thresholds, percentages, deadlines, the texts
the UI and the proof PDF show, and the bahn.de page behind each rule. A policy
change is an edit to this file only.

- Expected delay ≥ 20 min at the destination (or a cancelled train / missed
  connection): Zugbindung lifted. The journey may be made later, up to one year
  after the original travel date.
- Expected delay ≥ 60 min and the journey is not made: the unused journey's fare
  is refunded. Refund and later use are alternatives.
- Travelled and arrived ≥ 60 / ≥ 120 min late: 25 % / 50 % of the fare. A Hin- und
  Rückfahrt priced as one is compensated on half the price. Below 4 € nothing is paid.
- Deadlines count from the travel date (departure of the first leg).

The one question per journey is "Bist du gefahren?" (`ridden`). After "nein", when
both refund and later use are possible, `choice` records which one the user takes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .delays import LegDelay
from .models import Journey

LAST_VERIFIED = "2026-09-30"

LIFT_MIN = 20  # Zugbindung aufgehoben
COMP_25_MIN = 60
COMP_50_MIN = 120
REFUND_MIN = 60
MIN_PAYOUT_EUR = 4.0
REUSE_MONTHS = 12  # "bis zu einem Jahr nach ursprünglichem Reisedatum"
CLAIM_DEADLINE_MONTHS = 3  # the app's own, early deadline for claims
DB_CLAIM_LIMIT_MONTHS = 12  # what bahn.de states for passenger-rights claims
CLAIM_LEAD_DAYS = 21  # a claim counts as "Frist bald" this long before its deadline
VORRAT_LEAD_DAYS = 30  # a Vorrat ticket counts as "Frist bald" this long before it expires
MIN_TRANSFER = timedelta(minutes=2)

FAQ = "https://www.bahn.de/faq/"


@dataclass(frozen=True)
class Rule:
    title: str
    text: str
    source_url: str  # empty if no official page could be verified


RULES = {
    "zugbindung": Rule(
        "Zugbindung aufgehoben",
        f"Ab {LIFT_MIN} min erwarteter Verspätung am Ziel (oder bei Zugausfall) ist die Zugbindung aufgehoben. "
        "Die Fahrt darf bis zu einem Jahr nach dem ursprünglichen Reisedatum nachgeholt werden, auch über eine "
        "andere Strecke. Gilt nicht für erheblich ermäßigte Fahrkarten (z. B. Deutschland-Ticket, Länder-Tickets).",
        FAQ + "zugbindung-aufgehoben-bedeutung",
    ),
    "entschaedigung": Rule(
        "Entschädigung",
        f"Ab {COMP_25_MIN} min Verspätung am Ziel gibt es 25 %, ab {COMP_50_MIN} min 50 % des Fahrpreises der "
        "einfachen Fahrt. Bei Hin- und Rückfahrt zu einem Gesamtpreis zählt der halbe Preis.",
        FAQ + "welche-entschaedigung-erhalte-ich-wenn-mein-zug-verspaetet-am-zielbahnhof-ankommt",
    ),
    "mindestbetrag": Rule(
        "Mindestbetrag",
        "Entschädigungsbeträge unter 4 € zahlt die DB nicht aus.",
        FAQ + "welche-entschaedigung-erhalte-ich-wenn-mein-zug-verspaetet-am-zielbahnhof-ankommt",
    ),
    "erstattung": Rule(
        "Erstattung",
        f"Bei einer erwarteten Verspätung am Ziel von {REFUND_MIN} min oder mehr kannst du von der Reise "
        "zurücktreten und bekommst den Fahrpreis des nicht genutzten Teils zurück. Entweder Geld zurück oder "
        "später fahren – nicht beides.",
        "https://www.bahn.de/service/informationen-buchung/fahrgastrechte/rechtliche-regelungen",
    ),
    "frist": Rule(
        "Frist",
        f"Die App setzt dir {CLAIM_DEADLINE_MONTHS} Monate ab Reisedatum, damit nichts liegen bleibt. "
        f"Laut bahn.de gilt für Fahrgastrechte-Ansprüche eine Frist von {DB_CLAIM_LIMIT_MONTHS} Monaten nach dem Vorfall.",
        FAQ + "innerhalb-welcher-frist-kann-ich-meine-fahrgastrechtsansprueche-geltend-machen",
    ),
    "hoehere_gewalt": Rule(
        "Ausnahmen",
        "Bei außergewöhnlichen Umständen (z. B. große Naturkatastrophen) oder Ursachen durch Dritte (z. B. Personen "
        "im Gleis, Kabeldiebstahl, Polizeieinsatz) kann die DB die Entschädigung verweigern (EU-Verordnung 2021/782, "
        "Art. 19 Abs. 10). Ein gewöhnliches Unwetter zählt laut DB nicht dazu. Gilt nur für die Entschädigung, "
        "nicht für Erstattung oder spätere Nutzung.",
        FAQ + "gibt-es-auch-faelle-in-denen-ich-keine-verspaetungsentschaedigung-erhalte",
    ),
    "pdf_ticket": Rule(
        "Ticket als PDF",
        "Online-Tickets dürfen als PDF auf Laptop, Tablet oder Smartphone vorgezeigt werden.",
        FAQ + "ist-mein-online-ticket-auch-gueltig-wenn-es-als-pdf-auf-dem-laptop-vorgezeigt-wird",
    ),
}

FORCE_MAJEURE_LINE = "Ausnahme möglich bei höherer Gewalt (z. B. Naturkatastrophe, Polizeieinsatz)"
RULE_LINK_LABEL = "Regel bei bahn.de ↗"

CONTROLLED = {"": "Unbekannt", "ja": "Ja, kontrolliert", "nein": "Nein, nicht kontrolliert"}
CLAIM = {
    "": "Nicht beantragt",
    "beantragt": "Beantragt",
    "ausgezahlt": "Ausgezahlt",
    "abgelehnt": "Abgelehnt",
    "verzichtet": "Verzichtet",
}
OUTCOMES = {
    "entschaedigung": "Entschädigung möglich",
    "erstattung": "Erstattung möglich",
    "wiederverwendbar": "Wiederverwendbar",
    "kein_anspruch": "Kein Anspruch",
    "beantragt": "Beantragt",
    "ausgezahlt": "Ausgezahlt",
}


@dataclass(frozen=True)
class Band:
    key: str
    label: str
    low: int | None  # inclusive
    high: int | None  # exclusive
    explain: str


BANDS = [
    Band("d20", f"{LIFT_MIN}–{COMP_25_MIN - 1} min", LIFT_MIN, COMP_25_MIN,
         "Gefahren → kein Anspruch · Nicht gefahren → später fahren"),
    Band("d60", f"{COMP_25_MIN}–{COMP_50_MIN - 1} min", COMP_25_MIN, COMP_50_MIN,
         "Gefahren → 25 % · Nicht gefahren → Geld zurück oder später fahren"),
    Band("d120", f"≥ {COMP_50_MIN} min", COMP_50_MIN, None,
         "Gefahren → 50 % · Nicht gefahren → Geld zurück oder später fahren"),
    Band("ausfall", "Ausfall / Anschluss verpasst", None, None,
         "Gefahren → hängt von deiner Ankunft ab · Nicht gefahren → Geld zurück oder später fahren"),
]  # fmt: skip


def band_for(delay_min: int | None, disrupted: bool) -> str | None:
    if disrupted:
        return "ausfall"
    if delay_min is None:
        return None
    for b in BANDS:
        if b.low is not None and delay_min >= b.low and (b.high is None or delay_min < b.high):
            return b.key
    return None


def config() -> dict:
    """The rules as the UI needs them: labels, bands, sources."""
    return {
        "last_verified": LAST_VERIFIED,
        "rules": {k: asdict(r) for k, r in RULES.items()},
        "bands": [asdict(b) for b in BANDS],
        "outcomes": OUTCOMES,
        "claim": CLAIM,
        "controlled": CONTROLLED,
        "force_majeure_line": FORCE_MAJEURE_LINE,
        "rule_link_label": RULE_LINK_LABEL,
    }


# --- evaluation --------------------------------------------------------------------


@dataclass
class Outcome:
    """How the booked journey actually ran, according to the IRIS data."""

    known: bool
    delay_min: int | None  # at the final destination; None if cancelled/missed
    cancelled: bool = False
    missed_connection: bool = False

    @property
    def disrupted(self) -> bool:
        return self.cancelled or self.missed_connection


@dataclass
class Answer:
    """What one answer (or option) leads to."""

    kind: str  # entschaedigung | erstattung | vorrat | kein_anspruch | ankunft
    label: str  # "7,50 €", "29,99 € zurück", "Kein Anspruch (unter 4 €)", ...
    amount_eur: float | None = None
    note: str = ""
    rule: str = ""  # key into RULES
    force_majeure: bool = False


@dataclass
class Verdict:
    state: str  # future | waiting | no_action | ask | needs_arrival | choose | claim | claimed | reuse | none | done
    headline: str
    detail: str = ""
    travel_date: str | None = None
    delay_min: int | None = None
    cancelled: bool = False
    missed_connection: bool = False
    zugbindung_aufgehoben: bool | None = None
    claim_deadline: str | None = None  # the app's deadline (3 months)
    claim_limit: str | None = None  # DB's limit (12 months)
    reuse_limit: str | None = None  # last day a lifted ticket may be used
    reuse_until: str | None = None  # set only while the ticket is in the Vorrat
    claim_kind: str | None = None  # entschaedigung | erstattung
    pct: int | None = None
    amount_eur: float | None = None
    answers: dict | None = None  # state "ask": {"ja": Answer, "nein": Answer}
    options: list | None = None  # state "choose": [erstattung, vorrat]
    rule: str | None = None  # the rule behind the current recommendation
    force_majeure: bool = False
    due: str | None = None  # the date that matters now (claim deadline or Vorrat expiry)
    due_kind: str | None = None  # claim | vorrat
    action_date: str | None = None  # from here on the item is "Frist bald"
    due_soon: bool = False
    band: str | None = None
    outcomes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    evidence: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def journey_outcome(journey: Journey, delays: list[LegDelay] | None) -> Outcome:
    if not delays or any(d.status != "ok" for d in delays):
        return Outcome(False, None)
    cancelled = any(d.cancelled for d in delays)
    missed = False
    for leg, d, nxt, nd in zip(journey.legs, delays, journey.legs[1:], delays[1:]):
        arrived = datetime.fromisoformat(d.arr_actual) if d.arr_actual else leg.arrival
        leaves = datetime.fromisoformat(nd.dep_actual) if nd.dep_actual else nxt.departure
        if arrived + MIN_TRANSFER > leaves:
            missed = True
    if cancelled or missed:
        # the real arrival depends on the replacement train: unknown without the user's input
        return Outcome(True, None, cancelled=cancelled, missed_connection=missed)
    return Outcome(True, delays[-1].arrival_delay_min)


def evaluate(
    journey: Journey,
    price_basis: float,
    delays: list[LegDelay] | None,
    ridden: str = "",
    choice: str = "",
    vorrat_used_on: str | None = None,
    controlled: str = "",
    claim_status: str = "",
    manual_arrival: datetime | None = None,
    now: datetime | None = None,
) -> Verdict:
    now = now or datetime.now()
    today = now.date()
    travel = journey.departure.date()
    iris = journey_outcome(journey, delays)
    manual_delay = _minutes(manual_arrival - journey.arrival) if manual_arrival else None
    v = Verdict(
        "waiting",
        "",
        travel_date=travel.isoformat(),
        delay_min=manual_delay if manual_delay is not None else iris.delay_min,
        cancelled=iris.cancelled,
        missed_connection=iris.missed_connection,
        claim_deadline=_add_months(travel, CLAIM_DEADLINE_MONTHS).isoformat(),
        claim_limit=_add_months(travel, DB_CLAIM_LIMIT_MONTHS).isoformat(),
    )
    if controlled == "ja" and ridden == "nein":
        v.warnings.append("Als kontrolliert notiert, aber „nicht gefahren“ angegeben – ein kontrolliertes Ticket gilt als genutzt.")

    if journey.arrival > now and manual_arrival is None:
        v.state, v.headline = "future", "Reise steht noch an"
        return v
    if not iris.known and manual_delay is None:
        v.headline = "Verspätung noch nicht abgerufen"
        v.detail = "Die Daten kommen einige Stunden nach der Fahrt. Oder trag deine Ankunft selbst ein."
        return v

    expected = iris.delay_min if iris.known else manual_delay  # what the booked train did
    disrupted = iris.disrupted
    lifted = disrupted or (expected or 0) >= LIFT_MIN
    refund_possible = disrupted or (expected or 0) >= REFUND_MIN
    what = _describe(iris, expected)
    v.zugbindung_aufgehoben = lifted
    v.band = band_for(expected, disrupted)
    if not lifted:
        v.state, v.headline = "no_action", "Kein Handlungsbedarf"
        v.detail = f"{what} – unter {LIFT_MIN} min gibt es weder Entschädigung noch Erstattung."
        v.outcomes = ["kein_anspruch"]
        return _apply_claim_status(v, claim_status)

    v.reuse_limit = _add_months(travel, REUSE_MONTHS).isoformat()
    v.evidence = _evidence(journey, delays, iris, manual_delay if not iris.known else None)
    ja = _ja_answer(iris, manual_delay, price_basis)
    refund = Answer("erstattung", f"{_eur(price_basis)} zurück", price_basis,
                    f"Rücktritt wegen ≥ {REFUND_MIN} min erwarteter Verspätung", "erstattung")  # fmt: skip
    vorrat = Answer("vorrat", f"später fahren bis {_de(v.reuse_limit)}", None,
                    "Zugbindung aufgehoben – Fahrt später nachholen", "zugbindung")  # fmt: skip
    v.sources = ["zugbindung"] + (["erstattung"] if refund_possible else [])
    if ja.kind in ("entschaedigung", "kein_anspruch", "ankunft"):
        v.sources += ["entschaedigung"] + (["mindestbetrag"] if ja.rule == "mindestbetrag" else [])
    if ja.kind == "entschaedigung" or refund_possible:
        v.sources += ["frist"]
    if ja.kind == "entschaedigung":
        v.sources += ["hoehere_gewalt"]

    if ridden == "ja":
        _ridden(v, ja)
    elif ridden == "nein":
        _not_ridden(v, refund_possible, choice, refund, vorrat, vorrat_used_on, today)
    else:
        nein = refund if refund_possible else vorrat
        v.state, v.headline = "ask", "Bist du gefahren?"
        v.detail = what
        v.answers = {"ja": asdict(ja), "nein": asdict(nein)}
        v.outcomes = [o for o in (
            "entschaedigung" if ja.kind == "entschaedigung" else "kein_anspruch" if ja.kind == "kein_anspruch" else None,
            "erstattung" if refund_possible else None,
            "wiederverwendbar",
        ) if o]  # fmt: skip
        money = ja.kind in ("entschaedigung", "ankunft") or refund_possible
        _due(v, "claim" if money else "vorrat")

    v = _apply_claim_status(v, claim_status)
    _expire(v, today)
    if v.due:
        lead = CLAIM_LEAD_DAYS if v.due_kind == "claim" else VORRAT_LEAD_DAYS
        action = date.fromisoformat(v.due) - timedelta(days=lead)
        v.action_date = action.isoformat()
        v.due_soon = action <= today
    return v


def _ja_answer(iris: Outcome, manual_delay: int | None, basis: float) -> Answer:
    if manual_delay is None and iris.disrupted:
        why = "Zug ausgefallen" if iris.cancelled else "Anschluss verpasst"
        return Answer("ankunft", "Ankunft eintragen", note=f"{why} – deine Ankunft am Ziel ist nicht bekannt.", rule="entschaedigung")
    delay = manual_delay if manual_delay is not None else iris.delay_min
    pct = _pct(delay)
    if pct == 0:
        return Answer("kein_anspruch", f"Kein Anspruch (unter {COMP_25_MIN} min)",
                      note=f"Entschädigung gibt es erst ab {COMP_25_MIN} min am Ziel.", rule="entschaedigung")  # fmt: skip
    amount = _money(basis * pct / 100)
    if amount < MIN_PAYOUT_EUR:
        return Answer("kein_anspruch", f"Kein Anspruch (unter {_eur(MIN_PAYOUT_EUR, cents=False)})",
                      note=f"{pct} % von {_eur(basis)} wären {_eur(amount)}.", rule="mindestbetrag")  # fmt: skip
    return Answer("entschaedigung", _eur(amount), amount, f"{pct} % von {_eur(basis)}", "entschaedigung", True)


def _ridden(v: Verdict, ja: Answer) -> None:
    if ja.kind == "ankunft":
        v.state, v.headline, v.detail, v.rule = "needs_arrival", "Wann bist du angekommen?", ja.note, ja.rule
        _due(v, "claim")
    elif ja.kind == "entschaedigung":
        v.state, v.headline, v.detail = "claim", f"Entschädigung: {ja.label}", ja.note
        v.claim_kind, v.amount_eur, v.pct = "entschaedigung", ja.amount_eur, _pct(v.delay_min)
        v.rule, v.force_majeure, v.outcomes = "entschaedigung", True, ["entschaedigung"]
        _due(v, "claim")
    else:
        v.state, v.headline, v.detail, v.rule = "none", ja.label, ja.note, ja.rule
        v.outcomes = ["kein_anspruch"]


def _not_ridden(v: Verdict, refund_possible: bool, choice: str, refund: Answer, vorrat: Answer, used_on: str | None, today: date) -> None:
    if refund_possible and choice == "":
        v.state, v.headline = "choose", "Geld zurück oder später fahren?"
        v.detail = "Beides geht nicht – such dir eins aus."
        v.options = [asdict(refund), asdict(vorrat)]
        v.outcomes = ["erstattung", "wiederverwendbar"]
        _due(v, "claim")
    elif refund_possible and choice == "erstattung":
        v.state, v.headline, v.detail = "claim", f"Erstattung: {_eur(refund.amount_eur)}", refund.note
        v.claim_kind, v.amount_eur, v.rule, v.outcomes = "erstattung", refund.amount_eur, "erstattung", ["erstattung"]
        _due(v, "claim")
    else:
        v.rule = "zugbindung"
        if "pdf_ticket" not in v.sources:
            v.sources.append("pdf_ticket")
        if used_on:
            v.state, v.headline = "done", "Später genutzt"
            v.detail = f"Aufgehobene Zugbindung eingelöst am {_de(used_on)}."
        else:
            v.state, v.headline = "reuse", f"Im Vorrat · gültig bis {_de(v.reuse_limit)}"
            v.detail = "Die Fahrt darf später nachgeholt werden. Bei der Kontrolle das Nachweis-PDF zeigen."
            v.reuse_until = v.reuse_limit
            v.outcomes = ["wiederverwendbar"]
            _due(v, "vorrat")


def _due(v: Verdict, kind: str) -> None:
    v.due_kind = kind
    v.due = v.claim_deadline if kind == "claim" else v.reuse_limit


def _apply_claim_status(v: Verdict, claim_status: str) -> Verdict:
    if claim_status == "beantragt" and v.state == "claim":
        v.state, v.headline = "claimed", f"Beantragt · {v.headline}"
        v.outcomes, v.due, v.due_kind = ["beantragt"], None, None
    elif claim_status in ("ausgezahlt", "abgelehnt", "verzichtet"):
        v.state, v.headline = "done", f"{CLAIM[claim_status]} · {v.headline}"
        v.outcomes = ["ausgezahlt"] if claim_status == "ausgezahlt" else []
        v.due, v.due_kind, v.reuse_until = None, None, None
    return v


def _expire(v: Verdict, today: date) -> None:
    """Past DB's 12-month limit nothing can be claimed or used any more."""
    if v.state in ("ask", "needs_arrival", "choose", "claim", "reuse") and v.reuse_limit and v.reuse_limit < today.isoformat():
        v.state, v.headline = "done", "Abgelaufen"
        v.detail = f"Frist und Gültigkeit endeten am {_de(v.reuse_limit)}."
        v.reuse_until, v.due, v.due_kind, v.answers, v.options = None, None, None, None, None
        v.outcomes = []


def _evidence(journey: Journey, delays: list[LegDelay] | None, iris: Outcome, manual_delay: int | None) -> str:
    if manual_delay is not None:
        return f"Ankunft {journey.destination} laut eigener Angabe {manual_delay} min später als geplant."
    parts = []
    for leg, d in zip(journey.legs, delays or []):
        day = leg.departure.strftime("%d.%m.%Y")
        if d.cancelled:
            parts.append(f"{leg.train} ({leg.origin} → {leg.destination}) am {day} ausgefallen.")
        elif (d.arrival_delay_min or 0) > 0:
            actual = datetime.fromisoformat(d.arr_actual)
            parts.append(
                f"{leg.train} kam am {actual:%d.%m.%Y} um {actual:%H:%M} statt {leg.arrival:%H:%M} "
                f"in {leg.destination} an (+{d.arrival_delay_min} min)."
            )
    if iris.missed_connection:
        parts.append("Anschluss verpasst.")
    return " ".join(parts) + " Quelle: DB-Echtzeitdaten (IRIS)."


def _describe(iris: Outcome, delay: int | None) -> str:
    if iris.cancelled:
        return "Zug ausgefallen"
    if iris.missed_connection:
        return "Anschluss verpasst"
    return f"{delay} min Verspätung" if delay and delay > 0 else "Pünktlich"


def _de(iso: str | None) -> str:
    return date.fromisoformat(iso).strftime("%d.%m.%Y") if iso else "?"


def _eur(value: float, cents: bool = True) -> str:
    return (f"{value:.2f} €" if cents else f"{value:.0f} €").replace(".", ",")


def _money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _pct(delay: int | None) -> int:
    if delay is None:
        return 0
    return 50 if delay >= COMP_50_MIN else 25 if delay >= COMP_25_MIN else 0


def _minutes(delta: timedelta) -> int:
    return round(delta.total_seconds() / 60)


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise AssertionError("unreachable")
