"""Parser tests on a generated ticket that copies the layout of a real DB online ticket
(same column positions, 10 pt row spacing), so no personal ticket needs to be in the repo.
Put real tickets into tests/fixtures/private/ (git-ignored) to test them too."""

from datetime import datetime
from pathlib import Path

import pymupdf
import pytest

from ticketdepot.ticket_pdf import TicketParseError, parse_ticket_pdf

COLS = {"Halt": 43, "Datum": 170, "Zeit": 210, "Gleis": 249, "Produkte": 283, "Reservierung": 340}


def _ticket_pdf(tmp_path: Path, sections: list[tuple[str, list[tuple]]], fare_line: str, price: str, space: str = " ") -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 60

    def line(text, x=43, size=9):
        nonlocal y
        page.insert_text((x, y), text.replace(" ", space), fontsize=size)
        y += 10

    line("Online-Ticket")
    line("Gültigkeit: 12.10.2026 00:00 Uhr bis 13.10.2026 10:00 Uhr")
    line(fare_line)
    line("Klasse")
    line("2. Klasse")
    line("Reisender")
    line("1 Person (27-64 Jahre)")
    line("Zugbindung")
    line("IC 2023, 08:02 Uhr am 12.10.2026")
    line(f"Gesamtpreis {price} €. Gebucht am 01.09.2026 um 09:15 Uhr.")
    line("Auftragsnummer: 999000111222", x=369)
    y += 20
    for title, rows in sections:
        line(f"Ihre Reiseverbindung und Reservierung - {title}")
        for col, x in COLS.items():
            page.insert_text((x, y), col, fontsize=9)
        y += 13
        for station, date, time, platform, product, note in rows:
            for col, value in zip(COLS, (station, date, time, platform, product, note)):
                if value:
                    page.insert_text((COLS[col], y), value, fontsize=9)
            y += 10
        y += 20
        line("Wichtige Nutzungshinweise:")
        y += 20
    line("Ticketcode: ABC123")
    path = tmp_path / "ticket.pdf"
    doc.save(path)
    return path


def test_single_leg(tmp_path):
    pdf = _ticket_pdf(
        tmp_path,
        [("Einfache Fahrt am 12.10.2026", [
            ("Köln Hbf", "12.10.", "ab 08:02", "4", "IC 2023", None),
            ("Mainz Hbf", "12.10.", "an 09:51", "3a", None, None),
        ])],
        "Sparpreis (Einfache Fahrt)", "19,99",
    )  # fmt: skip
    t = parse_ticket_pdf(pdf)
    assert t.order_number == "999000111222"
    assert (t.fare, t.trip_kind, t.price_eur, t.travel_class) == ("Sparpreis", "Einfache Fahrt", 19.99, "2")
    assert t.valid_to == datetime(2026, 10, 13, 10, 0)
    assert t.zugbindung == ["IC 2023, 08:02 Uhr am 12.10.2026"]
    (leg,) = t.journeys[0].legs
    assert (leg.train, leg.origin, leg.destination) == ("IC 2023", "Köln Hbf", "Mainz Hbf")
    assert (leg.departure, leg.arrival) == (datetime(2026, 10, 12, 8, 2), datetime(2026, 10, 12, 9, 51))
    assert leg.arr_platform == "3a"


def test_transfer_and_round_trip(tmp_path):
    pdf = _ticket_pdf(
        tmp_path,
        [
            ("Hinfahrt am 12.10.2026", [
                ("Köln Hbf", "12.10.", "ab 08:02", "4", "IC 2023", "Wg. 7, Pl. 45"),
                ("Mainz Hbf", "12.10.", "an 09:51", "3a", None, None),
                ("Mainz Hbf", "12.10.", "ab 10:05", "5", "RE 4", None),
                ("Worms Hbf", "12.10.", "an 10:40", "2", None, None),
            ]),
            ("Rückfahrt am 31.12.2026", [
                ("Worms Hbf", "31.12.", "ab 23:30", "1", "ICE 1234", None),
                ("Köln Hbf", "01.01.", "an 01:10", "5", None, None),
            ]),
        ],
        "Super Sparpreis (Hin- und Rückfahrt)", "1.049,00",
    )  # fmt: skip
    t = parse_ticket_pdf(pdf)
    assert t.trip_kind == "Hin- und Rückfahrt" and t.price_eur == 1049.0
    assert t.price_basis_per_journey == 524.5
    out, back = t.journeys
    assert out.label == "Hinfahrt" and [leg.train for leg in out.legs] == ["IC 2023", "RE 4"]
    assert out.legs[0].notes == "Wg. 7, Pl. 45"
    assert (out.origin, out.destination) == ("Köln Hbf", "Worms Hbf")
    assert back.label == "Rückfahrt"
    assert back.arrival == datetime(2027, 1, 1, 1, 10)  # across New Year


def test_non_breaking_spaces(tmp_path):
    # some fonts extract every space as U+00A0 — header fields must still be found
    pdf = _ticket_pdf(
        tmp_path,
        [("Einfache Fahrt am 12.10.2026", [
            ("Köln Hbf", "12.10.", "ab 08:02", "4", "IC 2023", None),
            ("Mainz Hbf", "12.10.", "an 09:51", "3a", None, None),
        ])],
        "Sparpreis (Einfache Fahrt)", "19,99", space="\u00a0",
    )  # fmt: skip
    t = parse_ticket_pdf(pdf)
    assert t.booked_at == datetime(2026, 9, 1, 9, 15)
    assert t.valid_to == datetime(2026, 10, 13, 10, 0)
    assert (t.fare, t.travel_class, t.zugbindung) == ("Sparpreis", "2", ["IC 2023, 08:02 Uhr am 12.10.2026"])
    assert t.journeys[0].label == "Einfache Fahrt"


def test_not_a_ticket(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "Rechnung")
    doc.save(tmp_path / "x.pdf")
    with pytest.raises(TicketParseError):
        parse_ticket_pdf(tmp_path / "x.pdf")


PRIVATE = sorted((Path(__file__).parent / "fixtures" / "private").glob("*.pdf"))


@pytest.mark.parametrize("pdf", PRIVATE, ids=[p.name for p in PRIVATE])
def test_private_real_tickets(pdf):
    t = parse_ticket_pdf(pdf)
    assert t.order_number and t.price_eur > 0 and t.journeys
    for journey in t.journeys:
        for leg in journey.legs:
            assert leg.arrival > leg.departure and leg.train != "?"
