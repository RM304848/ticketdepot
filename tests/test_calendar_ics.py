from datetime import date, datetime, timezone

from ticketdepot import calendar_ics

VIEW = {
    "idx": 1,
    "order_number": "900000000808",
    "origin": "Düsseldorf Hbf",
    "destination": "Frankfurt(Main)Hbf",
    "departure": "2026-08-14T23:28:00",
    "legs": [{"train": "ICE 619"}],
    "verdict": {
        "state": "reuse", "due": "2027-08-14", "due_kind": "vorrat", "action_date": "2027-07-15",
        "reuse_until": "2027-08-14", "claim_limit": "2027-08-14", "claim_kind": None,
    },
}  # fmt: skip


def test_vorrat_event_is_all_day_on_the_action_date():
    e = calendar_ics.event(VIEW)
    assert e["date"] == date(2027, 7, 15)
    assert e["uid"] == "900000000808-1-vorrat@ticketdepot.local"
    assert e["title"] == "DB-Ticket nutzen – gültig bis 14.08.2027: Düsseldorf Hbf → Frankfurt(Main)Hbf (ICE 619)"
    assert "Nachweis-PDF: DB_2026-08-14_ICE619_gueltig-bis-2027-08-14.pdf" in e["description"]
    assert "localhost" not in e["description"] and "127.0.0.1" not in e["description"]


def test_ics_format():
    raw = calendar_ics.ics([calendar_ics.event(VIEW)], now=datetime(2026, 9, 30, tzinfo=timezone.utc))
    text = raw.decode("utf-8")
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    for line in raw.split(b"\r\n"):
        assert len(line) <= 75
    unfolded = text.replace("\r\n ", "")
    assert "DTSTART;VALUE=DATE:20270715\r\n" in unfolded and "DTEND;VALUE=DATE:20270716\r\n" in unfolded
    assert "TRIGGER:PT9H" in unfolded and "UID:900000000808-1-vorrat@ticketdepot.local" in unfolded
    assert "SUMMARY:DB-Ticket nutzen – gültig bis 14.08.2027: Düsseldorf Hbf → Frankfurt(Main)Hbf (ICE 619)" in unfolded
    assert "Auftragsnummer: 900000000808\\nGültig bis: 14.08.2027" in unfolded


def test_claim_event():
    view = {**VIEW, "verdict": {**VIEW["verdict"], "state": "claim", "due": "2026-11-14", "due_kind": "claim",
                                "action_date": "2026-10-24", "claim_kind": "entschaedigung", "reuse_until": None}}  # fmt: skip
    e = calendar_ics.event(view)
    assert e["date"] == date(2026, 10, 24) and e["uid"].endswith("-claim@ticketdepot.local")
    assert e["title"] == "Entschädigung beantragen – Frist 14.11.2026 (ICE 619)"


def test_nothing_due_no_event():
    assert calendar_ics.event({**VIEW, "verdict": {**VIEW["verdict"], "state": "done", "due": None}}) is None


def test_google_link():
    url = calendar_ics.google_url(calendar_ics.event(VIEW))
    assert url.startswith("https://calendar.google.com/calendar/render?action=TEMPLATE&")
    assert "dates=20270715%2F20270716" in url
