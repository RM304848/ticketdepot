"""Nachweis-PDF for a Vorrat ticket: the original DB ticket, unchanged, plus one proof page,
plus the user's own proof image (if any) on a page of its own.

The proof page is appended as an incremental update, so the original file's bytes are
a literal prefix of the output — the pages and the signed Aztec barcode are never
re-rendered, recompressed or re-encoded. PyMuPDF only draws the new page.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime
from pathlib import Path

import pymupdf
from pypdf import PdfReader, PdfWriter

from . import rules

PAGE = pymupdf.Rect(0, 0, 360, 640)  # phone-shaped: readable without zooming
MARGIN = 24
FONT_DIRS = [Path("/System/Library/Fonts/Supplemental"), Path("C:/Windows/Fonts")]
BLACK, MUTED, ACCENT = (0, 0, 0), (0.38, 0.4, 0.4), (0, 0.4, 0.4)


def filename(view: dict) -> str:
    train = re.sub(r"\s+", "", view["legs"][0]["train"])
    return f"DB_{view['departure'][:10]}_{train}_gueltig-bis-{view['verdict']['reuse_until']}.pdf"


def build(original: Path, view: dict, evidence: bytes | None = None) -> bytes:
    writer = PdfWriter(str(original), incremental=True)  # clones the file, appends on write
    for page in PdfReader(io.BytesIO(_proof_pages(view, evidence))).pages:
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _proof_pages(v: dict, evidence: bytes | None) -> bytes:
    verdict = v["verdict"]
    doc = pymupdf.open()
    p = _Page(doc)
    p.text("Zugbindung aufgehoben", 22, True, ACCENT, gap=0)
    p.text(f"gültig bis {_d(verdict['reuse_until'])}", 22, True, ACCENT, gap=6)
    p.text(_delay(v), 30, True, gap=14)
    p.rule()
    last = v["legs"][-1]
    p.row("Zug", " · ".join(leg["train"] for leg in v["legs"]))
    p.row("Datum", _d(v["departure"]))
    p.row("Strecke", f"{v['origin']} → {v['destination']}")
    p.row("Ankunft geplant", _dt(v["arrival"]))
    p.row("Ankunft tatsächlich", _actual(v, last))
    p.row("Auftragsnummer", v["order_number"])
    p.rule()
    if verdict.get("evidence"):
        p.text(verdict["evidence"], 9.5, gap=8)
    if evidence:
        p.text("Eigener Nachweis (Bild): nächste Seite.", 9.5, True, gap=8)
    p.text(rules.RULES["zugbindung"].text, 8.5, color=MUTED, gap=4)
    p.text(rules.RULES["zugbindung"].source_url, 7.5, color=MUTED, gap=10)
    checked = v.get("delays_checked")
    fetched = f", abgerufen am {_d(checked)}" if checked else ""
    p.footer(f"Quelle: DB-Echtzeitdaten (IRIS) via piebro/deutsche-bahn-data (CC BY 4.0){fetched}")
    if evidence:
        _evidence_page(doc, v, evidence)
    doc.set_metadata({"title": "Nachweis Zugbindung aufgehoben", "creator": "Ticketdepot"})
    doc.subset_fonts()  # the proof page only; the original ticket is never touched
    return doc.tobytes(garbage=3, deflate=True)


def _evidence_page(doc: pymupdf.Document, v: dict, image: bytes) -> None:
    p = _Page(doc)
    p.text("Eigener Nachweis", 18, True, ACCENT, gap=2)
    added = f" am {_d(v['evidence_added'])}" if v.get("evidence_added") else ""
    p.text(f"Vom Fahrgast hinzugefügt{added} · {v['legs'][0]['train']}, {_d(v['departure'])}", 8.5, color=MUTED, gap=10)
    pix = pymupdf.Pixmap(image)
    box = pymupdf.Rect(MARGIN, p.y, PAGE.width - MARGIN, PAGE.height - MARGIN)
    scale = min(box.width / pix.width, box.height / pix.height)
    w, h = pix.width * scale, pix.height * scale
    rect = pymupdf.Rect(box.x0 + (box.width - w) / 2, box.y0, box.x0 + (box.width + w) / 2, box.y0 + h)
    p.page.insert_image(rect, stream=image)
    p.page.draw_rect(rect, color=(0.8, 0.8, 0.8), width=0.6)  # screenshots are often white on white


class _Page:
    def __init__(self, doc: pymupdf.Document):
        self.page = doc.new_page(width=PAGE.width, height=PAGE.height)
        self.regular, self.bold = _fonts(self.page)
        self.y = MARGIN

    def text(self, s: str, size=11, bold=False, color=BLACK, gap=4, x=MARGIN):
        rect = pymupdf.Rect(x, self.y, PAGE.width - MARGIN, PAGE.height - MARGIN)
        font = self.bold if bold else self.regular
        if font in ("helv", "hebo"):
            s = s.replace("€", "EUR").replace("→", "->")
        used = self.page.insert_textbox(rect, s, fontsize=size, fontname=font, color=color)
        # insert_textbox returns the unused height; convert it into the height consumed
        self.y = PAGE.height - MARGIN - used + gap if used >= 0 else self.y + size * 1.4
        return self

    def row(self, label: str, value: str):
        self.text(label, 8.5, color=MUTED, gap=0)
        return self.text(value, 12.5, True, gap=7)

    def rule(self):
        self.page.draw_line((MARGIN, self.y), (PAGE.width - MARGIN, self.y), color=(0.8, 0.8, 0.8), width=0.6)
        self.y += 10
        return self

    def footer(self, s: str):
        self.y = max(self.y, PAGE.height - MARGIN - 22)
        return self.text(s, 7.5, color=MUTED, gap=0)


def _delay(v: dict) -> str:
    verdict = v["verdict"]
    if verdict["disruption"]:
        return verdict["disruption"]
    if verdict["early_departure"] and (verdict["delay_min"] or 0) < rules.LIFT_MIN:
        return "Abfahrt zu früh"
    if v.get("reported") == "zugbindung" and (verdict["delay_min"] or 0) < rules.LIFT_MIN:
        return f"Prognose ab {rules.LIFT_MIN} min"  # the forecast lifted it, the train made up the delay later
    return f"+{verdict['delay_min']} min"


def _actual(v: dict, last_leg: dict) -> str:
    if v.get("manual_arrival"):
        return f"{_dt(v['manual_arrival'])} (eigene Angabe)"
    d = last_leg.get("delay") or {}
    if d.get("arr_cancelled"):
        return "entfallen (siehe unten)"
    if d.get("arr_actual"):
        return _dt(d["arr_actual"])
    return "keine Daten"


def _fonts(page: pymupdf.Page) -> tuple[str, str]:
    """Arial where the OS has it (for € and →), else the built-in Helvetica."""
    for d in FONT_DIRS:
        for regular, bold in (("Arial.ttf", "Arial Bold.ttf"), ("arial.ttf", "arialbd.ttf")):
            if (d / regular).exists() and (d / bold).exists():
                page.insert_font(fontname="arial", fontfile=str(d / regular))
                page.insert_font(fontname="arialbd", fontfile=str(d / bold))
                return "arial", "arialbd"
    return "helv", "hebo"


def _d(iso: str) -> str:
    return date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")


def _dt(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
