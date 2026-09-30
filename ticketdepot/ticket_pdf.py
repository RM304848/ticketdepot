"""Read a DB online ticket PDF (the one bahn.de mails and DB Navigator exports).

Header facts (order number, fare, price, validity, Zugbindung) come from the plain
text. The connection table ("Ihre Reiseverbindung und Reservierung") is read from
word coordinates: its columns are aligned under the header words Halt / Datum /
Zeit / Gleis / Produkte / Reservierung, and each stop is one row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pymupdf

from .models import Journey, Leg, Ticket


class TicketParseError(ValueError):
    pass


_COLUMNS = ("Halt", "Datum", "Zeit", "Gleis", "Produkte", "Reservierung")
_ROW_TOLERANCE = 3  # points; words of one table row share y0 within this
_MAX_LINE_GAP = 14  # points; table rows are 10 apart, the next paragraph 20


@dataclass
class _Word:
    x0: float
    y0: float
    text: str


@dataclass
class _Row:
    station: str
    date: str  # "01.08."
    kind: str  # "ab" or "an"
    time: str  # "15:51"
    platform: str | None
    product: str | None
    note: str | None


def parse_ticket_pdf(path: str | Path) -> Ticket:
    with pymupdf.open(path) as doc:
        text = _plain("\n".join(page.get_text("text") for page in doc))
        pages = [
            [_Word(w[0], w[1], _plain(w[4])) for w in page.get_text("words")] for page in doc
        ]
    return parse_ticket(text, pages)


def _plain(s: str) -> str:
    # some PDF fonts extract spaces as U+00A0 and hyphens as soft hyphens
    return s.replace(" ", " ").replace("­", "-")


def parse_ticket(text: str, pages: list[list[_Word]]) -> Ticket:
    order = _search(r"Auftragsnummer:\s*(\d+)", text)
    if not order:
        raise TicketParseError("Keine Auftragsnummer gefunden – ist das ein DB Online-Ticket?")

    fare, trip_kind = _fare_and_kind(text)
    journeys = [j for words in pages for j in _journeys_on_page(words)]
    if not journeys:
        raise TicketParseError(f"Auftrag {order}: keine Reiseverbindung im PDF gefunden.")

    price = _search(r"Gesamtpreis\s+([\d.]+,\d{2})", text)
    booked = re.search(r"Gebucht am (\d\d\.\d\d\.\d{4}) um (\d\d:\d\d) Uhr", text)
    valid = re.search(
        r"Gültigkeit:\s*(\d\d\.\d\d\.\d{4}) (\d\d:\d\d) Uhr bis (\d\d\.\d\d\.\d{4}) (\d\d:\d\d) Uhr",
        text,
    )
    return Ticket(
        order_number=order,
        fare=fare,
        trip_kind=trip_kind,
        price_eur=float(price.replace(".", "").replace(",", ".")) if price else 0.0,
        journeys=journeys,
        travel_class=_search(r"\b([12])\. Klasse", text),
        travellers=_line_after("Reisender", text),
        ticket_code=_search(r"Ticketcode:\s*(\w+)", text),
        booked_at=_datetime(*booked.groups()) if booked else None,
        valid_from=_datetime(valid[1], valid[2]) if valid else None,
        valid_to=_datetime(valid[3], valid[4]) if valid else None,
        zugbindung=[
            m[0]
            for m in re.finditer(r"([A-Z]{1,4} ?\d+), (\d\d:\d\d) Uhr am (\d\d\.\d\d\.\d{4})", text)
        ],
    )


def _fare_and_kind(text: str) -> tuple[str, str]:
    m = re.search(r"^(.*?preis.*?) \((.+?)\)\s*$", text, re.MULTILINE | re.IGNORECASE)
    if m:
        return m[1].strip(), m[2].strip()
    return "Unbekannt", "Unbekannt"


def _journeys_on_page(words: list[_Word]) -> list[Journey]:
    lines = _group_lines(words)
    journeys = []
    i = 0
    while i < len(lines):
        title = " ".join(w.text for w in lines[i])
        m = re.search(r"Reiseverbindung.*?[-–—\u00ad]\s*(.+?) am (\d\d\.\d\d\.(\d{4}))", title)
        if not m or i + 1 >= len(lines):
            i += 1
            continue
        header = lines[i + 1]
        columns = _column_starts(header)
        if columns is None:
            i += 1
            continue
        rows, i = _read_rows(lines, i + 2, columns)
        legs = _rows_to_legs(rows, year=int(m[3]), title_month=int(m[2][3:5]))
        if legs:
            journeys.append(Journey(label=m[1].strip(), legs=legs))
    return journeys


def _group_lines(words: list[_Word]) -> list[list[_Word]]:
    lines: list[list[_Word]] = []
    for w in sorted(words, key=lambda w: (w.y0, w.x0)):
        if lines and abs(lines[-1][0].y0 - w.y0) <= _ROW_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def _column_starts(header: list[_Word]) -> dict[str, float] | None:
    starts = {w.text: w.x0 for w in header if w.text in _COLUMNS}
    return starts if all(c in starts for c in _COLUMNS[:5]) else None


def _read_rows(lines, start: int, columns: dict[str, float]) -> tuple[list[_Row], int]:
    order = sorted(columns.items(), key=lambda kv: kv[1])

    def column_of(word: _Word) -> str:
        name = order[0][0]
        for col, x in order:
            if word.x0 >= x - 2:
                name = col
        return name

    rows: list[_Row] = []
    i = start
    while i < len(lines):
        cells: dict[str, list[str]] = {}
        for w in lines[i]:
            cells.setdefault(column_of(w), []).append(w.text)
        get = lambda c: " ".join(cells.get(c, [])) or None  # noqa: E731
        time = re.match(r"(ab|an)\s+(\d\d:\d\d)", get("Zeit") or "")
        if time and get("Halt"):
            rows.append(
                _Row(
                    station=get("Halt"),
                    date=get("Datum") or "",
                    kind=time[1],
                    time=time[2],
                    platform=get("Gleis"),
                    product=get("Produkte"),
                    note=get("Reservierung"),
                )
            )
        elif (
            rows
            and lines[i][0].y0 - lines[i - 1][0].y0 <= _MAX_LINE_GAP
            and set(cells) <= {"Halt", "Reservierung", "Produkte"}
        ):
            # continuation line: wrapped station name or a reservation note
            last = rows[-1]
            if cells.get("Halt"):
                last.station += " " + get("Halt")
            if cells.get("Reservierung"):
                last.note = " ".join(filter(None, [last.note, get("Reservierung")]))
        else:
            break
        i += 1
    return rows, i


def _rows_to_legs(rows: list[_Row], year: int, title_month: int) -> list[Leg]:
    legs = []
    for dep, arr in zip(rows, rows[1:]):
        if dep.kind != "ab" or arr.kind != "an":
            continue
        legs.append(
            Leg(
                train=dep.product or "?",
                origin=dep.station,
                destination=arr.station,
                departure=_row_datetime(dep, year, title_month),
                arrival=_row_datetime(arr, year, title_month),
                dep_platform=dep.platform,
                arr_platform=arr.platform,
                notes=dep.note,
            )
        )
    return legs


def _row_datetime(row: _Row, year: int, title_month: int) -> datetime:
    day, month = (int(x) for x in row.date.strip(".").split(".")[:2])
    if month < title_month:  # journey across New Year
        year += 1
    hour, minute = (int(x) for x in row.time.split(":"))
    return datetime(year, month, day, hour, minute)


def _datetime(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")


def _search(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m[1] if m else None


def _line_after(label: str, text: str) -> str | None:
    m = re.search(rf"^{label}\s*\n(.+)$", text, re.MULTILINE)
    return m[1].strip() if m else None
