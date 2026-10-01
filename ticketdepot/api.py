"""The calls the UI makes, as POST /api/<method> (see server.py), plus the
downloads served by GET (original ticket, Nachweis-PDF, calendar files)."""

from __future__ import annotations

import base64
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from . import __version__, calendar_ics, proof_pdf, rules
from .delays import BERLIN, check_legs
from .store import Store, data_dir
from .ticket_pdf import TicketParseError, parse_ticket_pdf

CLAIM_URL = "https://www.bahn.de/buchung/meine-reisen"
FORM_URL = "https://www.bahn.de/service/informationen-buchung/fahrgastrechte"
FINAL_AFTER = timedelta(days=2)  # raw IRIS data can still be revised shortly after the trip
INPUT_STATES = ("ask", "needs_arrival", "choose")


def _now() -> datetime:
    return datetime.now(BERLIN).replace(tzinfo=None)


class Api:
    def __init__(self, store: Store | None = None):
        self._store = store or Store()
        self._lock = threading.Lock()
        self._pdf_dir = data_dir() / "pdfs"
        self._pdf_dir.mkdir(exist_ok=True)

    # --- reading -------------------------------------------------------------

    def ping(self) -> dict:
        return {"app": "ticketdepot", "version": __version__}

    def overview(self) -> dict:
        views = self._views(_now())
        return {"journeys": views, "summary": _summary(views), "config": rules.config() | {"version": __version__}}

    def due_checks(self) -> list[int]:
        """Journeys whose delays should be (re)fetched: arrived, and data not final yet."""
        now = _now()
        with self._lock:
            rows = self._store.journeys()
        return [r["id"] for r in rows if r["journey"].arrival + timedelta(minutes=30) < now and not _final(r)]

    # --- import ----------------------------------------------------------------

    def import_pdf(self, filename: str, content_b64: str) -> dict:
        tmp = self._pdf_dir / f".upload-{os.getpid()}-{threading.get_ident()}.pdf"
        tmp.write_bytes(base64.b64decode(content_b64))
        try:
            return self._import_file(tmp, display_name=filename)
        finally:
            tmp.unlink(missing_ok=True)

    def import_downloads(self) -> dict:
        # bahn.de names its downloads "Ticket_<Auftrag>_<Datum>__<Name>.pdf" or "DB_Ticket_<Auftrag>.pdf"
        return self.import_folder(str(Path.home() / "Downloads"), "Ticket_*.pdf", "DB_Ticket_*.pdf")

    def import_folder(self, folder: str, *patterns: str) -> dict:
        path = Path(folder)
        files = sorted({p for pattern in patterns or ("*.pdf",) for p in path.glob(pattern)})
        results = [self._import_file(p) for p in files]
        new = sum(1 for r in results if r.get("new"))
        errors = [r["message"] for r in results if not r["ok"]]
        return {
            "ok": not errors,
            "message": f"{len(results)} Ticket-PDFs in {path.name} gefunden, {new} neu importiert."
            + (f" Fehler: {'; '.join(errors)}" if errors else ""),
        }

    def _import_file(self, path: Path, display_name: str | None = None) -> dict:
        name = display_name or path.name
        try:
            ticket = parse_ticket_pdf(path)
        except (TicketParseError, RuntimeError, ValueError) as e:
            return {"ok": False, "message": f"{name}: {e}"}
        copy = self._pdf_dir / f"{ticket.order_number}.pdf"
        copy.write_bytes(path.read_bytes())
        with self._lock:
            new = self._store.save_ticket(ticket, str(copy))
        route = f"{ticket.journeys[0].origin} → {ticket.journeys[0].destination}"
        verb = "importiert" if new else "aktualisiert"
        return {"ok": True, "new": new, "message": f"Auftrag {ticket.order_number} ({route}) {verb}."}

    # --- user input --------------------------------------------------------------

    def update(self, journey_id: int, fields: dict) -> dict:
        if "ridden" in fields:
            fields = {"choice": "", **fields}  # a new answer means a new choice
        with self._lock:
            self._store.update_journey(journey_id, fields)
            return self._view(self._store.journey(journey_id), _now())

    def mark_claimed(self, journey_id: int) -> dict:
        """The user confirmed in the claim dialog that the claim was sent."""
        return self.update(journey_id, {"claim_status": "beantragt", "claim_date": _now().date().isoformat()})

    def mark_used(self, journey_id: int) -> dict:
        return self.update(journey_id, {"vorrat_used_on": _now().date().isoformat()})

    def reset_answer(self, journey_id: int) -> dict:
        fields = {"ridden": "", "choice": "", "vorrat_used_on": None, "manual_arrival": None, "reported": ""}
        return self.update(journey_id, fields)

    def report(self, journey_id: int, what: str) -> dict:
        """The user's own statement: "anschluss" (connection missed) or "ausfall" (train not in the data)."""
        if what not in ("anschluss", "ausfall", ""):
            raise ValueError(what)
        return self.update(journey_id, {"reported": what})

    def delete_ticket(self, order_number: str) -> bool:
        with self._lock:
            self._store.delete_ticket(order_number)
        return True

    # --- delays -------------------------------------------------------------------

    def check(self, journey_id: int) -> dict:
        with self._lock:
            row = self._store.journey(journey_id)
        delays = check_legs(row["journey"].legs, _now())  # network, outside the lock
        with self._lock:
            self._store.save_delays(journey_id, delays)
            return self._view(self._store.journey(journey_id), _now())

    # --- claim assistant ------------------------------------------------------------

    def claim_info(self, journey_id: int) -> dict:
        """Everything the DB claim form asks for, ready to copy."""
        with self._lock:
            row = self._store.journey(journey_id)
            view = self._view(row, _now())
        ticket, journey, v = row["ticket"], row["journey"], view["verdict"]
        dep, arr = journey.departure, journey.arrival
        trains = "; ".join(
            f"{leg.train} ({leg.origin} {leg.departure:%H:%M} → {leg.destination} {leg.arrival:%H:%M})" for leg in journey.legs
        )
        fields = [
            ("Auftragsnummer", ticket.order_number),
            ("Reisedatum", f"{dep:%d.%m.%Y}"),
            ("Startbahnhof", journey.origin),
            ("Zielbahnhof", journey.destination),
            ("Geplante Abfahrt", f"{dep:%H:%M}"),
            ("Geplante Ankunft", f"{arr:%d.%m.%Y %H:%M}"),
            ("Gebuchte Züge", trains),
        ]
        reason = v["disruption"] or "Verspätung"
        if v["claim_kind"] == "entschaedigung":
            actual = row["manual_arrival"] or (row["delays"][-1].arr_actual if row["delays"] else None)
            fields += [
                ("Tatsächliche Ankunft am Ziel", f"{datetime.fromisoformat(actual):%d.%m.%Y %H:%M}" if actual else "–"),
                ("Verspätung am Ziel", f"{v['delay_min']} min"),
                ("Anlass", reason),
                ("Anspruch", f"{v['pct']} % Entschädigung: {rules._eur(v['amount_eur'])}"),
            ]
        elif v["claim_kind"] == "erstattung":
            expected = f"{v['delay_min']} min" if v["delay_min"] is not None else reason
            fields += [
                ("Anlass", f"Fahrt nicht angetreten wegen {reason} (erwartet: {expected})"),
                ("Anspruch", f"Erstattung des Fahrpreises: {rules._eur(v['amount_eur'])}"),
            ]
        price = rules._eur(ticket.price_eur)
        if len(ticket.journeys) > 1:
            price += f" (Hin- und Rückfahrt, Basis {rules._eur(view['price_basis'])})"
        fields.append(("Fahrpreis", price))
        return {
            "title": f"{journey.origin} → {journey.destination}, {dep:%d.%m.%Y}",
            "headline": v["headline"],
            "kind": v["claim_kind"],
            "fields": [{"label": k, "value": val} for k, val in fields],
            "all_text": "\n".join(f"{k}: {val}" for k, val in fields),
            "order_number": ticket.order_number,
            "claim_url": CLAIM_URL,
            "form_url": FORM_URL,
        }

    # --- downloads (GET, see server.py) ---------------------------------------------

    def ticket_pdf(self, order_number: str) -> Path | None:
        with self._lock:
            rows = [r for r in self._store.journeys() if r["order_number"] == order_number]
        path = Path(rows[0]["pdf_path"]) if rows and rows[0]["pdf_path"] else None
        return path if path and path.exists() else None

    def proof(self, journey_id: int) -> tuple[str, bytes] | None:
        with self._lock:
            row = self._store.journey(journey_id)
            view = self._view(row, _now())
        if not view["verdict"]["reuse_until"] or not row["pdf_path"] or not Path(row["pdf_path"]).exists():
            return None
        return proof_pdf.filename(view), proof_pdf.build(Path(row["pdf_path"]), view)

    def calendar(self, journey_id: int | None = None) -> tuple[str, bytes] | None:
        """One journey's reminder, or (journey_id None) all open deadlines in one file."""
        if journey_id is None:
            events = [e for v in self._views(_now()) if (e := calendar_ics.event(v))]
            events.sort(key=lambda e: e["date"])
            return f"Ticketdepot_Fristen_{date.today():%Y-%m-%d}.ics", calendar_ics.ics(events)
        with self._lock:
            view = self._view(self._store.journey(journey_id), _now())
        e = calendar_ics.event(view)
        return (calendar_ics.filename(e), calendar_ics.ics([e])) if e else None

    # --- view model ----------------------------------------------------------------

    def _views(self, now: datetime) -> list[dict]:
        with self._lock:
            rows = self._store.journeys()
        return sorted((self._view(r, now) for r in rows), key=lambda v: v["departure"], reverse=True)

    def _view(self, row: dict, now: datetime) -> dict:
        ticket, journey, delays = row["ticket"], row["journey"], row["delays"]
        manual = datetime.fromisoformat(row["manual_arrival"]) if row["manual_arrival"] else None
        verdict = rules.evaluate(
            journey,
            ticket.price_basis_per_journey,
            delays,
            ridden=row["ridden"],
            choice=row["choice"],
            vorrat_used_on=row["vorrat_used_on"],
            controlled=row["controlled"],
            claim_status=row["claim_status"],
            manual_arrival=manual,
            now=now,
            reported=row["reported"],
        )
        view = {
            "id": row["id"],
            "idx": row["idx"],
            "order_number": ticket.order_number,
            "label": journey.label,
            "fare": ticket.fare,
            "trip_kind": ticket.trip_kind,
            "travel_class": ticket.travel_class,
            "price": ticket.price_eur,
            "price_basis": ticket.price_basis_per_journey,
            "origin": journey.origin,
            "destination": journey.destination,
            "departure": journey.departure.isoformat(),
            "arrival": journey.arrival.isoformat(),
            "zugbindung": ticket.zugbindung,
            "legs": [
                {**leg.to_dict(), "delay": delays[i].to_dict() | {"delay_min": delays[i].arrival_delay_min} if delays else None}
                for i, leg in enumerate(journey.legs)
            ],
            "has_pdf": bool(row["pdf_path"]),
            "delays_checked": row["delays_checked"],
            "delays_final": _final(row),
            **{k: row[k] for k in ("ridden", "choice", "vorrat_used_on", "reported", "controlled", "claim_status", "claim_date", "claim_amount", "manual_arrival", "notes")},
            "verdict": verdict.to_dict(),
        }
        if verdict.state in ("claim", "reuse"):
            e = calendar_ics.event(view)
            view["google_calendar_url"] = calendar_ics.google_url(e) if e else None
        if verdict.reuse_until:
            view["proof_filename"] = proof_pdf.filename(view)
        return view


def _final(row: dict) -> bool:
    delays = row["delays"]
    if not delays or any(d.status == "pending" for d in delays):
        return False
    if all(d.source == "monthly" for d in delays):
        return True
    return _now() - row["journey"].arrival > FINAL_AFTER


def _summary(views: list[dict]) -> dict:
    open_claims = [v for v in views if v["verdict"]["state"] == "claim"]
    return {
        "count": len(views),
        "open_eur": round(sum(v["verdict"]["amount_eur"] or 0 for v in open_claims), 2),
        "open_count": len(open_claims),
        "needs_input": sum(1 for v in views if v["verdict"]["state"] in INPUT_STATES),
        "due_soon": sum(1 for v in views if v["verdict"]["due_soon"]),
    }
