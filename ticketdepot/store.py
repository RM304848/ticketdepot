"""SQLite store: one row per ticket, one row per journey (direction) of a ticket.

User input (ridden, choice, inspection, claim) lives on the journey row, so re-importing a
PDF refreshes the parsed ticket without touching it.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

from .delays import LegDelay
from .models import Journey, Ticket

USER_FIELDS = (
    "ridden", "choice", "vorrat_used_on", "controlled", "claim_status",
    "claim_date", "claim_amount", "manual_arrival", "notes",
)  # fmt: skip
TEXT_FIELDS = ("ridden", "choice", "controlled", "claim_status")  # '' is a value, not "unset"
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    order_number TEXT PRIMARY KEY,
    data         TEXT NOT NULL,
    pdf_path     TEXT,
    imported_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journeys (
    id               INTEGER PRIMARY KEY,
    order_number     TEXT NOT NULL REFERENCES tickets(order_number) ON DELETE CASCADE,
    idx              INTEGER NOT NULL,
    data             TEXT NOT NULL,
    ridden           TEXT NOT NULL DEFAULT '',
    choice           TEXT NOT NULL DEFAULT '',
    vorrat_used_on   TEXT,
    controlled       TEXT NOT NULL DEFAULT '',
    claim_status     TEXT NOT NULL DEFAULT '',
    claim_date       TEXT,
    claim_amount     REAL,
    manual_arrival   TEXT,
    notes            TEXT,
    delays           TEXT,
    delays_checked   TEXT,
    UNIQUE (order_number, idx)
);
"""


LEGACY_NAME = "Bahntickets"  # the app's name before 0.1.0; its data folder is taken over once


def data_dir() -> Path:
    if env := os.environ.get("TICKETDEPOT_DATA"):
        path = Path(env)
    else:
        if sys.platform == "darwin":
            base, name = Path.home() / "Library" / "Application Support", "Ticketdepot"
        elif sys.platform == "win32":
            base, name = Path(os.environ.get("APPDATA", Path.home())), "Ticketdepot"
        else:
            base, name = Path.home() / ".local" / "share", "ticketdepot"
        path = base / name
        legacy = base / (LEGACY_NAME if name[0].isupper() else LEGACY_NAME.lower())
        if not path.exists() and legacy.is_dir():
            legacy.rename(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "ticketdepot.sqlite"
        legacy = self.path.with_name("bahntickets.sqlite")
        if not self.path.exists() and legacy.exists():
            legacy.rename(self.path)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Schema 0 → 1: the `usage` dropdown became `ridden` + `choice` + `vorrat_used_on`."""
        if self._db.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
            return
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(journeys)")}
        with self._db:
            for name, decl in (("ridden", "TEXT NOT NULL DEFAULT ''"), ("choice", "TEXT NOT NULL DEFAULT ''"), ("vorrat_used_on", "TEXT")):
                if name not in cols:
                    self._db.execute(f"ALTER TABLE journeys ADD COLUMN {name} {decl}")
            if "usage" in cols:
                today = date.today().isoformat()
                self._db.execute("UPDATE journeys SET ridden = 'ja' WHERE usage IN ('gefahren', 'anderer_zug')")
                self._db.execute(
                    """UPDATE journeys SET ridden = 'nein',
                       choice = CASE WHEN claim_status IN ('beantragt', 'ausgezahlt') THEN 'erstattung' ELSE '' END
                       WHERE usage = 'nicht_gefahren'"""
                )
                self._db.execute(
                    "UPDATE journeys SET ridden = 'nein', choice = 'vorrat', vorrat_used_on = ? WHERE usage = 'spaeter'", (today,)
                )
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def save_ticket(self, ticket: Ticket, pdf_path: str | None = None) -> bool:
        """Insert or refresh a ticket. Returns True if it was new."""
        new = self._db.execute("SELECT 1 FROM tickets WHERE order_number = ?", (ticket.order_number,)).fetchone() is None
        with self._db:
            self._db.execute(
                """INSERT INTO tickets (order_number, data, pdf_path, imported_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT (order_number) DO UPDATE SET data = excluded.data,
                       pdf_path = COALESCE(excluded.pdf_path, tickets.pdf_path)""",
                (ticket.order_number, json.dumps(ticket.to_dict()), pdf_path, datetime.now().isoformat()),
            )
            for idx, journey in enumerate(ticket.journeys):
                self._db.execute(
                    """INSERT INTO journeys (order_number, idx, data) VALUES (?, ?, ?)
                       ON CONFLICT (order_number, idx) DO UPDATE SET data = excluded.data""",
                    (ticket.order_number, idx, json.dumps(journey.to_dict())),
                )
        return new

    def journeys(self) -> list[dict]:
        rows = self._db.execute(
            """SELECT j.*, t.data AS ticket_data, t.pdf_path FROM journeys j
               JOIN tickets t USING (order_number)"""
        ).fetchall()
        return [self._row(r) for r in rows]

    def journey(self, journey_id: int) -> dict:
        row = self._db.execute(
            """SELECT j.*, t.data AS ticket_data, t.pdf_path FROM journeys j
               JOIN tickets t USING (order_number) WHERE j.id = ?""",
            (journey_id,),
        ).fetchone()
        if row is None:
            raise KeyError(journey_id)
        return self._row(row)

    def update_journey(self, journey_id: int, fields: dict) -> None:
        fields = {k: (v if v != "" or k in TEXT_FIELDS else None) for k, v in fields.items() if k in USER_FIELDS}
        if not fields:
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self._db:
            self._db.execute(f"UPDATE journeys SET {assignments} WHERE id = ?", (*fields.values(), journey_id))

    def save_delays(self, journey_id: int, delays: list[LegDelay]) -> None:
        with self._db:
            self._db.execute(
                "UPDATE journeys SET delays = ?, delays_checked = ? WHERE id = ?",
                (json.dumps([d.to_dict() for d in delays]), datetime.now().isoformat(timespec="seconds"), journey_id),
            )

    def delete_ticket(self, order_number: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM tickets WHERE order_number = ?", (order_number,))

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["ticket"] = Ticket.from_dict(json.loads(d.pop("ticket_data")))
        d["journey"] = Journey.from_dict(json.loads(d.pop("data")))
        d["delays"] = [LegDelay.from_dict(x) for x in json.loads(d["delays"])] if d["delays"] else None
        if d["pdf_path"] and not Path(d["pdf_path"]).exists():
            # stored absolute; the data folder may have moved (renamed app, copied data)
            moved = data_dir() / "pdfs" / Path(d["pdf_path"]).name
            d["pdf_path"] = str(moved) if moved.exists() else d["pdf_path"]
        return d
