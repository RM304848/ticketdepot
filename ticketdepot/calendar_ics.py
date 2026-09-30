"""Calendar reminders for claim deadlines and Vorrat expiries, as .ics (RFC 5545) or a
Google Calendar link.

Google ignores alarms in imported files, so the event itself is the reminder: an
all-day event on the day to act (the "Bald fällig" date), with the real deadline in
the title. Apple and Outlook additionally get an alarm at 09:00 that day.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from . import proof_pdf

PRODID = "-//Ticketdepot//Fristen//DE"


def event(view: dict) -> dict | None:
    """The reminder for one journey, or None if nothing is due."""
    v = view["verdict"]
    if not v.get("due") or not v.get("action_date") or v["state"] not in ("claim", "reuse", "ask", "choose", "needs_arrival"):
        return None
    trains = ", ".join(leg["train"] for leg in view["legs"])
    route = f"{view['origin']} → {view['destination']}"
    due = _de(v["due"])
    lines = [
        f"Strecke: {route}",
        f"Zug: {trains}",
        f"Reisedatum: {_de(view['departure'])}",
        f"Auftragsnummer: {view['order_number']}",
    ]
    if v["due_kind"] == "vorrat":
        kind = "vorrat"
        title = f"DB-Ticket nutzen – gültig bis {due}: {route} ({trains})"
        lines.append(f"Gültig bis: {due}")
        if v.get("reuse_until"):
            lines.append(f"Nachweis-PDF: {proof_pdf.filename(view)}")
    else:
        kind = "claim"
        what = {"entschaedigung": "Entschädigung", "erstattung": "Erstattung"}.get(v.get("claim_kind"), "DB-Anspruch")
        title = f"{what} beantragen – Frist {due} ({trains})"
        lines.append(f"Frist: {due} (DB akzeptiert bis {_de(v['claim_limit'])})")
    return {
        "uid": f"{view['order_number']}-{view['idx']}-{kind}@ticketdepot.local",
        "kind": kind,
        "date": date.fromisoformat(v["action_date"]),
        "title": title,
        "description": "\n".join(lines),
    }


def ics(events: list[dict], now: datetime | None = None) -> bytes:
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for e in events:
        out += [
            "BEGIN:VEVENT",
            f"UID:{e['uid']}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{e['date']:%Y%m%d}",
            f"DTEND;VALUE=DATE:{e['date'] + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_escape(e['title'])}",
            f"DESCRIPTION:{_escape(e['description'])}",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escape(e['title'])}",
            "TRIGGER:PT9H",  # 09:00 on the (all-day) event's day
            "END:VALARM",
            "END:VEVENT",
        ]
    out.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in out).encode("utf-8")


def filename(e: dict) -> str:
    return f"Frist_{e['uid'].split('@')[0]}.ics"


def google_url(e: dict) -> str:
    end = e["date"] + timedelta(days=1)
    query = {"action": "TEMPLATE", "text": e["title"], "dates": f"{e['date']:%Y%m%d}/{end:%Y%m%d}", "details": e["description"]}
    return "https://calendar.google.com/calendar/render?" + urlencode(query)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Lines longer than 75 octets continue on the next line after CRLF + space,
    never splitting a UTF-8 character."""
    parts, current, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        limit = 75 if not parts else 74  # continuation lines start with a space
        if size + n > limit:
            parts.append(current)
            current, size = "", 0
        current += ch
        size += n
    parts.append(current)
    return "\r\n ".join(parts)


def _de(iso: str) -> str:
    return date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")
