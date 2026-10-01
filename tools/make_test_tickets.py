"""Generate dummy DB ticket PDFs for trying the app (python tools/make_test_tickets.py).

The PDFs copy the layout of a real DB online ticket (same column positions and row
spacing, so the parser reads them like real ones) but are clearly marked as samples
and carry a fictitious passenger and order numbers.

The trains are real: they ran on the listed days with the listed delays (DB IRIS
data via piebro/deutsche-bahn-data), so "Verspätung prüfen" finds them and every
case of the rules shows up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pymupdf

OUT = Path(__file__).resolve().parent.parent / "testdaten"
PASSENGER = "Erika Mustermann"
BANNER = "MUSTER · TESTDATEN · KEIN GÜLTIGER FAHRSCHEIN"
FONT_DIRS = [Path("/System/Library/Fonts/Supplemental"), Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/msttcorefonts")]
COLS = {"Halt": 43, "Datum": 170, "Zeit": 210, "Gleis": 249, "Produkte": 283, "Reservierung": 340}


@dataclass
class L:  # one leg
    train: str
    origin: str
    dep: str  # "14.08.2026 06:22"
    dest: str
    arr: str
    dep_pl: str = "5"
    arr_pl: str = "7"


@dataclass
class T:  # one ticket
    key: str
    order: str
    fare: str
    price: str
    journeys: list[tuple[str, list[L]]]  # (label, legs)
    expected: str  # what the app should show, for testdaten/README.md
    kind: str = "Einfache Fahrt"


TICKETS = [
    T("01_puenktlich", "900000000101", "Super Sparpreis", "24,99",
      [("Einfache Fahrt", [L("ICE 525", "Düsseldorf Hbf", "14.08.2026 06:22", "Würzburg Hbf", "14.08.2026 09:03")])],
      "ICE 525 kam +3 min an → „Kein Handlungsbedarf“, keine Frage."),
    T("02_wiederverwendbar", "900000000202", "Sparpreis", "39,99",
      [("Einfache Fahrt", [L("ICE 518", "Ulm Hbf", "14.08.2026 12:47", "Dortmund Hbf", "14.08.2026 17:21")])],
      "+33 min → Zugbindung aufgehoben. „Ja“ → kein Anspruch (unter 60 min); „Nein“ → direkt in den Vorrat bis "
      "14.08.2027 (Reiter „Vorrat“, PDF herunterladen, In Kalender). Danach „Ticket genutzt“ → erledigt."),
    T("03_25prozent_oder_erstattung", "900000000303", "Sparpreis", "49,99",
      [("Einfache Fahrt", [L("ICE 857", "Hagen Hbf", "14.08.2026 09:39", "Berlin Hbf", "14.08.2026 14:12")])],
      "+93 min. „Ja“ → 25 % = 12,50 €. „Nein“ → Wahl: 49,99 € zurück oder später fahren. "
      "In Details „Kontrolliert: Ja“ bei „Nein“ → Hinweis."),
    T("04_50prozent", "900000000404", "Super Sparpreis", "34,99",
      [("Einfache Fahrt", [L("ICE 28", "Würzburg Hbf", "14.08.2026 14:26", "Köln Hbf", "14.08.2026 18:06")])],
      "+134 min. „Ja“ → 50 % = 17,50 €. „Entschädigung beantragen“ → „Antrag abgeschickt“ → Reiter „Beantragt“; "
      "dort „Ausgezahlt“ → erledigt."),
    T("05_ausfall", "900000000505", "Sparpreis", "29,99",
      [("Einfache Fahrt", [L("ICE 24", "Hanau Hbf", "14.08.2026 19:18", "Bonn Hbf", "14.08.2026 21:43")])],
      "ICE 24 endete vorzeitig in Frankfurt → „Teilausfall“. „Nein“ → später fahren, oder 29,99 € zurück, "
      "wenn du dadurch ≥ 60 min später angekommen wärst. "
      "„Ja“ → „Wann bist du angekommen?“ (z. B. 23:10 → +87 min → 25 %)."),
    T("06_anschluss_verpasst", "900000000606", "Super Sparpreis", "27,99",
      [("Einfache Fahrt", [
          L("ICE 517", "Stuttgart Hbf", "14.08.2026 14:17", "München Hbf", "14.08.2026 16:29", "9", "14"),
          L("ICE 2822", "München Hbf", "14.08.2026 16:47", "Nürnberg Hbf", "14.08.2026 18:02", "19", "8"),
      ])],
      "ICE 517 +40 min in München, ICE 2822 fuhr pünktlich ab → Anschluss verpasst. "
      "„Ja“ → „Wann bist du angekommen?“, z. B. 19:10 → +68 min → 25 %."),
    T("07_umstieg_74min", "900000000707", "Sparpreis", "45,99",
      [("Einfache Fahrt", [
          L("IC 2431", "Bremen Hbf", "14.08.2026 14:09", "Hannover Hbf", "14.08.2026 15:13", "8", "4"),
          L("ICE 549", "Hannover Hbf", "14.08.2026 15:31", "Berlin Hbf", "14.08.2026 17:10", "11", "13"),
      ])],
      "Umstieg klappt (ICE 549 fuhr selbst 57 min später ab), Ankunft Berlin +74 min. "
      "„Ja“ → 25 % = 11,50 €."),
    T("08_hin_und_rueck", "900000000808", "Sparpreis", "59,98",
      [("Hinfahrt", [L("ICE 726", "Frankfurt(Main)Hbf", "14.08.2026 11:08", "Düsseldorf Hbf", "14.08.2026 12:40")]),
       ("Rückfahrt", [L("ICE 619", "Düsseldorf Hbf", "14.08.2026 23:28", "Frankfurt(Main)Hbf", "15.08.2026 01:17")])],
      "Zwei Karten, Basis je 29,99 € (halber Preis). Hinfahrt +3 → kein Handlungsbedarf. Rückfahrt ICE 619 +63 "
      "(Ankunft nach Mitternacht): „Ja“ → 7,50 €, „Nein“ → 29,99 € zurück oder später fahren bis 14.08.2027; Frist 14.11.2026.",
      kind="Hin- und Rückfahrt"),
    T("09_unter_4_euro", "900000000909", "Super Sparpreis", "12,99",
      [("Einfache Fahrt", [L("ICE 2466", "Hamm(Westf)Hbf", "14.08.2026 19:48", "Köln Hbf", "14.08.2026 21:23")])],
      "+75 min, aber 25 % von 12,99 € = 3,25 € → „Ja“ → Kein Anspruch (unter 4 €); „Nein“ → 12,99 € zurück."),
    T("10_september_rohdaten", "900000001010", "Super Sparpreis", "21,99",
      [("Einfache Fahrt", [L("ICE 725", "Düsseldorf Hbf", "20.09.2026 16:22", "Frankfurt(Main)Hbf", "20.09.2026 17:51")])],
      "Abruf aus den Roh-IRIS-Daten, solange der Monat läuft (ca. 1 min). +5 min → „Kein Handlungsbedarf“."),
    T("11_zukunft", "900000001111", "Super Sparpreis", "19,99",
      [("Einfache Fahrt", [L("ICE 725", "Essen Hbf", "15.10.2026 15:51", "Frankfurt(Main)Hbf", "15.10.2026 17:51", "2", "8")])],
      "Reise in der Zukunft → Reiter „Anstehend“, kein Abruf."),
]  # fmt: skip


def _fonts(page: pymupdf.Page) -> tuple[str, str]:
    """Arial where the OS has it (for the € sign), else the built-in Helvetica."""
    for d in FONT_DIRS:
        if (d / "Arial.ttf").exists() and (d / "Arial Bold.ttf").exists():
            page.insert_font(fontname="arial", fontfile=str(d / "Arial.ttf"))
            page.insert_font(fontname="arialbd", fontfile=str(d / "Arial Bold.ttf"))
            return "arial", "arialbd"
        if (d / "arial.ttf").exists() and (d / "arialbd.ttf").exists():
            page.insert_font(fontname="arial", fontfile=str(d / "arial.ttf"))
            page.insert_font(fontname="arialbd", fontfile=str(d / "arialbd.ttf"))
            return "arial", "arialbd"
    return "helv", "hebo"


def _dt(s: str) -> datetime:
    return datetime.strptime(s, "%d.%m.%Y %H:%M")


def render(t: T) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    red = (0.8, 0, 0.1)

    regular, bold_font = _fonts(page)

    def text(x, y, s, size=9, bold=False, color=(0, 0, 0)):
        if regular == "helv":  # base-14 Helvetica has no € glyph
            s = s.replace("€", "EUR")
        page.insert_text((x, y), s, fontsize=size, fontname=bold_font if bold else regular, color=color)

    legs = [leg for _, js in t.journeys for leg in js]
    first, last = _dt(legs[0].dep), _dt(legs[-1].arr)
    main = t.journeys[0][1]

    text(43, 22, BANNER, 10, True, red)
    text(43, 44, "CIV 1080", 8)
    text(43, 58, "Online-Ticket", 13, True)
    text(43, 72, f"{'ICE' if any(l.train.startswith('ICE') for l in legs) else 'IC/EC'} Fahrkarte", 9)
    valid_to = last.date() + timedelta(days=1)  # like real tickets: until 10:00 the next day
    text(43, 84, f"Gültigkeit: {first:%d.%m.%Y} 00:00 Uhr bis {valid_to:%d.%m.%Y} 10:00 Uhr", 8)
    text(43, 96, "Sie können alle Züge nutzen, die auf Ihrer Fahrkarte angegeben sind. Für Züge des Nahverkehrs", 7)
    text(43, 104, "(z.B. RE, RB, S) besteht keine Zugbindung.", 7)
    text(43, 118, f"{t.fare} ({t.kind})", 10, True)
    text(43, 132, "Klasse", 7)
    text(43, 142, "2. Klasse", 9)
    text(43, 154, "Reisender", 7)
    text(43, 164, "1 Person (27-64 Jahre)", 9)
    text(43, 178, f"{t.kind} {main[0].origin}", 9, True)
    text(43, 188, f" {main[-1].dest}", 9, True)
    text(43, 202, "Zugbindung", 7)
    y = 212
    for leg in legs:
        d = _dt(leg.dep)
        text(43, y, f"{leg.train}, {d:%H:%M} Uhr am {d:%d.%m.%Y}", 9)
        y += 10
    text(43, y + 4, "Eine Stornierung Ihrer Fahrkarte ist ausgeschlossen.", 8)
    text(43, y + 16, f"Gesamtpreis {t.price} €. Gebucht am 21.07.2026 um 07:22 Uhr.", 9, True)
    text(369, 240, PASSENGER, 10, True)
    text(369, 290, f"Auftragsnummer: {t.order}", 9, True)

    y = max(y + 50, 320)
    for label, js in t.journeys:
        day = _dt(js[0].dep)
        text(43, y, f"Ihre Reiseverbindung und Reservierung - {label} am {day:%d.%m.%Y}", 10, True)
        y += 15
        for col, x in COLS.items():
            text(x, y, "Reservierung / Hinweise" if col == "Reservierung" else col, 8, True)
        y += 13
        for leg in js:
            d, a = _dt(leg.dep), _dt(leg.arr)
            for station, when, kind, pl, product in (
                (leg.origin, d, "ab", leg.dep_pl, leg.train),
                (leg.dest, a, "an", leg.arr_pl, None),
            ):
                text(COLS["Halt"], y, station)
                text(COLS["Datum"], y, f"{when:%d.%m.}")
                text(COLS["Zeit"], y, f"{kind} {when:%H:%M}")
                text(COLS["Gleis"], y, pl)
                if product:
                    text(COLS["Produkte"], y, product)
                y += 10
        y += 22

    text(43, y, "Wichtige Nutzungshinweise:", 8, True)
    text(43, y + 12, "- Bei einer zu erwartenden Verspätung ab 20 Minuten am Zielbahnhof Ihrer Fahrkarte ist die Zugbindung", 7)
    text(49, y + 21, "Ihrer Fahrt ohne besondere Bescheinigung aufgehoben.", 7)
    text(43, 800, "Ticketcode: TEST" + t.order[-4:], 8)
    text(43, 820, BANNER, 10, True, red)

    OUT.mkdir(exist_ok=True)
    path = OUT / f"Ticket_{t.order}_{first:%d.%m.%Y}__TEST_{t.key}.pdf"
    doc.set_metadata({"title": "MUSTER – Testticket (kein gültiger Fahrschein)"})
    doc.subset_fonts()
    doc.save(path, garbage=3, deflate=True)
    return path


def main() -> None:
    lines = [
        "# Testtickets",
        "",
        "Erzeugt mit `python tools/make_test_tickets.py`. Muster-PDFs mit fiktivem Namen und erfundenen "
        "Auftragsnummern; die Züge und Verspätungen sind echt (DB-IRIS-Daten).",
        "",
        "Starten mit `Ticketdepot-Test.command` (Doppelklick) oder "
        "`python -m ticketdepot --data testdaten/appdata --import testdaten`: eigene Testdatenbank, die PDFs hier "
        "werden beim Start importiert, die Verspätungen danach automatisch abgerufen.",
        "",
        "| Datei | Was du sehen solltest |",
        "|---|---|",
    ]
    for t in TICKETS:
        path = render(t)
        lines.append(f"| `{path.name}` | {t.expected} |")
        print(path.relative_to(OUT.parent))
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
