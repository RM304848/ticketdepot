"""Workflow tests through the Api, offline: delays are stored directly, the clock is fixed."""

import base64
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pymupdf
import pytest
from pypdf import PdfReader

from ticketdepot import api as api_module
from ticketdepot.delays import LegDelay
from ticketdepot.store import Store
from ticketdepot.ticket_pdf import parse_ticket_pdf

TESTDATEN = Path(__file__).parent.parent / "testdaten"
ICE_619 = TESTDATEN / "Ticket_900000000808_14.08.2026__TEST_08_hin_und_rueck.pdf"
ICE_2466 = TESTDATEN / "Ticket_900000000909_14.08.2026__TEST_09_unter_4_euro.pdf"
NOW = datetime(2026, 9, 30, 12, 0)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKETDEPOT_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(api_module, "_now", lambda: NOW)
    api = api_module.Api()
    for pdf in (ICE_619, ICE_2466):
        assert api.import_pdf(pdf.name, base64.b64encode(pdf.read_bytes()).decode())["ok"]
    _set_delay(api, "ICE 619", 63)
    _set_delay(api, "ICE 726", 3)
    _set_delay(api, "ICE 2466", 75)
    return api


def _set_delay(api, train, minutes):
    j = _find(api, train)
    planned = datetime.fromisoformat(j["arrival"])
    api._store.save_delays(j["id"], [LegDelay(
        train, "ok", "monthly", arr_planned=planned.isoformat(),
        arr_actual=(planned + timedelta(minutes=minutes)).isoformat(),
    )])  # fmt: skip


def _find(api, train):
    return next(j for j in api.overview()["journeys"] if j["legs"][0]["train"] == train)


def test_acceptance_ice_619(api):
    v = _find(api, "ICE 619")["verdict"]
    assert v["state"] == "ask" and v["delay_min"] == 63
    assert v["answers"]["ja"]["label"] == "7,50 €" and v["answers"]["ja"]["force_majeure"]
    assert v["answers"]["nein"]["label"] == "29,99 € zurück"
    assert v["reuse_limit"] == "2027-08-14" and v["claim_deadline"] == "2026-11-14"


def test_acceptance_ice_2466(api):
    v = _find(api, "ICE 2466")["verdict"]
    assert v["answers"]["ja"]["label"] == "Kein Anspruch (unter 4 €)"
    assert v["answers"]["nein"]["label"] == "12,99 € zurück"
    assert v["reuse_limit"] == "2027-08-14" and v["claim_deadline"] == "2026-11-14"


def test_hinfahrt_on_time_needs_nothing(api):
    assert _find(api, "ICE 726")["verdict"]["state"] == "no_action"


def test_summary_tiles(api):
    s = api.overview()["summary"]
    assert s == {"count": 3, "open_eur": 0, "open_count": 0, "needs_input": 2, "due_soon": 0}
    api.update(_find(api, "ICE 619")["id"], {"ridden": "ja"})
    s = api.overview()["summary"]
    assert s["open_eur"] == 7.50 and s["needs_input"] == 1


def test_new_answer_resets_the_choice(api):
    jid = _find(api, "ICE 619")["id"]
    assert api.update(jid, {"ridden": "nein", "choice": "vorrat"})["verdict"]["state"] == "reuse"
    assert api.update(jid, {"ridden": "nein"})["verdict"]["state"] == "choose"
    assert api.reset_answer(jid)["verdict"]["state"] == "ask"


def test_claim_dialog_and_mark_claimed(api):
    jid = _find(api, "ICE 619")["id"]
    api.update(jid, {"ridden": "nein", "choice": "erstattung"})
    fields = {f["label"]: f["value"] for f in api.claim_info(jid)["fields"]}
    assert fields["Auftragsnummer"] == "900000000808"
    assert fields["Anspruch"] == "Erstattung des Fahrpreises: 29,99 €"
    assert "Basis 29,99 €" in fields["Fahrpreis"]
    view = api.mark_claimed(jid)
    assert view["claim_status"] == "beantragt" and view["claim_date"] == "2026-09-30"
    assert view["verdict"]["state"] == "claimed"


def test_travelled_claim_fields(api):
    jid = _find(api, "ICE 619")["id"]
    api.update(jid, {"ridden": "ja", "controlled": "nein"})
    fields = {f["label"]: f["value"] for f in api.claim_info(jid)["fields"]}
    assert fields["Tatsächliche Ankunft am Ziel"] == "15.08.2026 02:20"
    assert fields["Anspruch"] == "25 % Entschädigung: 7,50 €"


def test_proof_pdf_keeps_the_original_bytes(api):
    jid = _find(api, "ICE 619")["id"]
    api.update(jid, {"ridden": "nein", "choice": "vorrat", "controlled": "ja", "notes": "GEHEIME NOTIZ"})
    name, body = api.proof(jid)
    assert name == "DB_2026-08-14_ICE619_gueltig-bis-2027-08-14.pdf"
    original = ICE_619.read_bytes()
    assert body.startswith(original)  # incremental update: nothing of the ticket is rewritten
    with pymupdf.open(stream=body) as doc, pymupdf.open(ICE_619) as src:
        assert doc.page_count == src.page_count + 1
        assert doc[0].get_text() == src[0].get_text()
        proof = doc[-1].get_text().replace("\xa0", " ").replace("\xad", "-")
    assert "Zugbindung aufgehoben" in proof and "gültig bis 14.08.2027" in proof and "+63 min" in proof
    assert "900000000808" in proof and "Quelle: DB-Echtzeitdaten (IRIS)" in proof
    assert "GEHEIME" not in proof and "ontrolliert" not in proof and "unbenutzt" not in proof
    assert len(PdfReader(__import__("io").BytesIO(body)).pages) == 2


def test_no_proof_outside_the_vorrat(api):
    assert api.proof(_find(api, "ICE 619")["id"]) is None


def test_route_data_for_the_lookup(api):
    jid = _find(api, "ICE 619")["id"]
    api.update(jid, {"ridden": "nein", "choice": "vorrat"})
    vorrat = [j for j in api.overview()["journeys"] if j["verdict"]["reuse_until"]]
    assert [(j["origin"], j["destination"]) for j in vorrat] == [("Düsseldorf Hbf", "Frankfurt(Main)Hbf")]


def test_calendar_single_and_bulk(api):
    jid = _find(api, "ICE 619")["id"]
    name, _ = api.calendar(jid)  # undecided: the claim deadline is what matters
    assert name == "Frist_900000000808-1-claim.ics"
    api.update(jid, {"ridden": "nein", "choice": "vorrat"})
    name, body = api.calendar(jid)
    text = body.decode()
    assert name == "Frist_900000000808-1-vorrat.ics"
    assert "DTSTART;VALUE=DATE:20270715" in text and "UID:900000000808-1-vorrat@ticketdepot.local" in text
    assert _find(api, "ICE 619")["google_calendar_url"].startswith("https://calendar.google.com/calendar/render?action=TEMPLATE")
    _, bulk = api.calendar()
    assert bulk.decode().count("BEGIN:VEVENT") == 2  # ICE 619 Vorrat + ICE 2466 still open


def test_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKETDEPOT_DATA", str(tmp_path / "empty"))
    data = api_module.Api().overview()
    assert data["journeys"] == [] and data["summary"]["count"] == 0
    assert "bands" in data["config"] and data["config"]["version"]


def test_migration_from_usage(tmp_path):
    db = tmp_path / "old.sqlite"
    con = sqlite3.connect(db)
    con.executescript(
        """CREATE TABLE tickets (order_number TEXT PRIMARY KEY, data TEXT NOT NULL, pdf_path TEXT, imported_at TEXT NOT NULL);
           CREATE TABLE journeys (id INTEGER PRIMARY KEY, order_number TEXT NOT NULL, idx INTEGER NOT NULL, data TEXT NOT NULL,
             usage TEXT NOT NULL DEFAULT '', controlled TEXT NOT NULL DEFAULT '', claim_status TEXT NOT NULL DEFAULT '',
             claim_date TEXT, claim_amount REAL, manual_arrival TEXT, notes TEXT, delays TEXT, delays_checked TEXT,
             UNIQUE (order_number, idx));"""
    )
    rows = [("gefahren", ""), ("anderer_zug", ""), ("nicht_gefahren", ""), ("nicht_gefahren", "beantragt"), ("spaeter", ""), ("", "")]
    for i, (usage, claim) in enumerate(rows):
        con.execute("INSERT INTO journeys (order_number, idx, data, usage, claim_status) VALUES ('x', ?, '{}', ?, ?)", (i, usage, claim))
    con.commit()
    con.close()
    Store(db)
    got = sqlite3.connect(db).execute("SELECT ridden, choice, vorrat_used_on IS NOT NULL FROM journeys ORDER BY idx").fetchall()
    assert got == [("ja", "", 0), ("ja", "", 0), ("nein", "", 0), ("nein", "erstattung", 0), ("nein", "vorrat", 1), ("", "", 0)]
    Store(db)  # idempotent


def test_data_from_the_old_app_name_is_taken_over(tmp_path, monkeypatch):
    from ticketdepot import store

    monkeypatch.delenv("TICKETDEPOT_DATA", raising=False)
    monkeypatch.setattr(store.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    old = store.data_dir().parent / "Bahntickets"
    (old / "pdfs").mkdir(parents=True)
    legacy_store = Store(old / "bahntickets.sqlite")
    legacy_store.save_ticket(parse_ticket_pdf(ICE_2466), str(old / "pdfs" / "900000000909.pdf"))
    legacy_store._db.close()  # Windows cannot rename a folder with an open file in it
    (old / "pdfs" / "900000000909.pdf").write_bytes(ICE_2466.read_bytes())
    store.data_dir().rmdir()  # simulate a fresh install of the renamed app

    new = store.data_dir()
    assert new.name in ("Ticketdepot", "ticketdepot") and not old.exists()
    (row,) = Store().journeys()
    assert Path(row["pdf_path"]) == new / "pdfs" / "900000000909.pdf"
