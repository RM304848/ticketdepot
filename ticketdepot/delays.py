"""Actual departure/arrival times for the legs of a ticket.

Source: the public HuggingFace dataset piebro/deutsche-bahn-data (DB IRIS timetable
data, CC BY 4.0) — the same data DelayBahn builds on. Only the legs of imported
tickets are looked up; DuckDB reads the remote parquet files with HTTP range
requests, so nothing is mirrored locally.

- Finished months: monthly_processed_data/data-YYYY-MM.parquet, already joined into
  planned + changed times per stop. The file is sorted by time, so a time filter
  touches only a few row groups (~20 s per ticket).
- The current month: raw_data/year=/month=/day=, the raw IRIS plan/fchg XML
  responses. Filtered to the ticket's stations by EVA in the request URL.
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from .models import Leg
from .stations import evas_for, fold

HF = "https://huggingface.co/datasets/piebro/deutsche-bahn-data/resolve/main/"
HF_TREE = "https://huggingface.co/api/datasets/piebro/deutsche-bahn-data/tree/main/"
BERLIN = ZoneInfo("Europe/Berlin")


@dataclass
class LegDelay:
    train: str
    status: str  # "ok" | "pending" (not reported yet) | "not_found"
    source: str | None = None  # "monthly" | "raw"
    dep_planned: str | None = None
    dep_actual: str | None = None
    dep_cancelled: bool = False
    arr_planned: str | None = None
    arr_actual: str | None = None
    arr_cancelled: bool = False
    message: str | None = None

    @property
    def cancelled(self) -> bool:
        return self.dep_cancelled or self.arr_cancelled

    @property
    def arrival_delay_min(self) -> int | None:
        if not (self.arr_planned and self.arr_actual):
            return None
        delta = datetime.fromisoformat(self.arr_actual) - datetime.fromisoformat(self.arr_planned)
        return round(delta.total_seconds() / 60)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> LegDelay:
        return cls(**d)


def split_train(train: str) -> tuple[str, str]:
    """"ICE 725" → ("ICE", "725"); "S 1" → ("S", "1")."""
    m = re.match(r"\s*([A-Za-zÄÖÜäöü]+)\s*(\d+)", train)
    return (m[1].upper(), m[2]) if m else (train.strip().upper(), "")


def check_legs(legs: list[Leg], now: datetime | None = None) -> list[LegDelay]:
    now = now or datetime.now(BERLIN).replace(tzinfo=None)
    results: dict[int, LegDelay] = {}
    for i, leg in enumerate(legs):
        if leg.arrival > now:
            results[i] = LegDelay(leg.train, "pending", message="Zug ist noch nicht angekommen.")

    todo = [i for i in range(len(legs)) if i not in results]
    by_month: dict[str, list[int]] = {}
    for i in todo:
        by_month.setdefault(legs[i].departure.strftime("%Y-%m"), []).append(i)

    for month, idx in by_month.items():
        if month in monthly_files_available():
            found = _from_monthly(month, [legs[i] for i in idx])
        else:
            found = _from_raw([legs[i] for i in idx], now)
        results.update(zip(idx, found))
    return [results[i] for i in range(len(legs))]


# --- monthly files ----------------------------------------------------------


@cache
def monthly_files_available() -> frozenset[str]:
    names = {e["path"] for e in _tree("monthly_processed_data")}
    return frozenset(m[1] for n in names if (m := re.search(r"data-(\d{4}-\d{2})\.parquet$", n)))


def _from_monthly(month: str, legs: list[Leg]) -> list[LegDelay]:
    numbers = sorted({split_train(leg.train)[1] for leg in legs})
    start = min(leg.departure for leg in legs) - timedelta(hours=2)
    end = max(leg.arrival for leg in legs) + timedelta(hours=12)
    rows = _duck().cursor().execute(
        f"""
        SELECT train_type, train_number, line_number, station_name, xml_station_name, eva,
               arrival_planned_time, arrival_change_time, arrival_is_canceled,
               departure_planned_time, departure_change_time, departure_is_canceled
        FROM read_parquet('{HF}monthly_processed_data/data-{month}.parquet')
        WHERE time BETWEEN ? AND ?
          AND (train_number IN ({",".join("?" * len(numbers))})
               OR line_number IN ({",".join("?" * len(numbers))}))
        """,
        [start, end, *numbers, *numbers],
    ).fetchall()
    cols = [
        "type", "number", "line", "station", "xml_station", "eva",
        "arr_pt", "arr_ct", "arr_cancel", "dep_pt", "dep_ct", "dep_cancel",
    ]  # fmt: skip
    stops = [dict(zip(cols, r)) for r in rows]
    return [_leg_from_stops(leg, stops) for leg in legs]


def _leg_from_stops(leg: Leg, stops: list[dict]) -> LegDelay:
    kind, number = split_train(leg.train)

    def find(station: str, key: str, planned: datetime) -> dict | None:
        evas = set(evas_for(station))
        for s in stops:
            same_train = s["number"] == number or (s["line"] or "").upper() in (number, kind + number)
            same_station = s["eva"] in evas or fold(station) in (fold(s["station"] or ""), fold(s["xml_station"] or ""))
            if same_train and same_station and s[key] == planned:
                return s
        return None

    dep = find(leg.origin, "dep_pt", leg.departure)
    arr = find(leg.destination, "arr_pt", leg.arrival)
    if not arr:
        return LegDelay(leg.train, "not_found", "monthly", message=f"{leg.train} nicht in den Daten gefunden.")
    return LegDelay(
        leg.train,
        "ok",
        "monthly",
        dep_planned=_iso(leg.departure),
        dep_actual=_iso(dep["dep_ct"] or dep["dep_pt"]) if dep else None,
        dep_cancelled=bool(dep and dep["dep_cancel"]),
        arr_planned=_iso(leg.arrival),
        arr_actual=_iso(arr["arr_ct"] or arr["arr_pt"]),
        arr_cancelled=bool(arr["arr_cancel"]),
    )


# --- raw IRIS responses (current month) -------------------------------------


def _from_raw(legs: list[Leg], now: datetime) -> list[LegDelay]:
    files = sorted({f for leg in legs for f in _raw_files_for(leg)})
    evas = sorted({e for leg in legs for st in (leg.origin, leg.destination) for e in evas_for(st)[:3]})
    if not files or not evas:
        msg = "Noch keine Rohdaten für diesen Tag." if not files else "Bahnhof nicht in der Stationsliste."
        return [LegDelay(leg.train, "pending" if not files else "not_found", "raw", message=msg) for leg in legs]

    url_filter = " OR ".join(["url LIKE ?"] * (2 * len(evas)))
    params = [p for e in evas for p in (f"%/plan/{e}/%", f"%/fchg/{e}")]
    file_list = "[" + ",".join(f"'{HF}{f}'" for f in files) + "]"
    rows = _duck().cursor().execute(
        f"""SELECT timestamp, api_name, url, response_data FROM read_parquet({file_list}, union_by_name=true)
            WHERE status_code = '200' AND ({url_filter})""",
        params,
    ).fetchall()

    plans: dict[str, list[ET.Element]] = {}  # eva → stops
    fchg: dict[str, list[tuple[datetime, ET.Element]]] = {}  # eva → (fetched at, stop)
    last_fchg: dict[str, datetime] = {}
    for ts, api, url, xml in rows:
        eva = re.search(r"/(?:plan|fchg)/(\d+)", url)[1]
        fetched = ts.replace(tzinfo=ZoneInfo("UTC")).astimezone(BERLIN).replace(tzinfo=None)
        stops = ET.fromstring(xml).findall("s") if xml else []
        if api.endswith("plan"):
            plans.setdefault(eva, []).extend(stops)
        else:
            fchg.setdefault(eva, []).extend((fetched, s) for s in stops)
            last_fchg[eva] = max(last_fchg.get(eva, fetched), fetched)

    results = []
    for leg in legs:
        dep = _raw_stop(leg, leg.origin, "dp", leg.departure, plans, fchg, last_fchg)
        arr = _raw_stop(leg, leg.destination, "ar", leg.arrival, plans, fchg, last_fchg)
        if arr is None:
            results.append(LegDelay(leg.train, "not_found", "raw", message=f"{leg.train} nicht im Fahrplan gefunden."))
        elif arr == "pending":
            results.append(LegDelay(leg.train, "pending", "raw", message="Ankunft noch nicht gemeldet – später erneut prüfen."))
        else:
            results.append(
                LegDelay(
                    leg.train,
                    "ok",
                    "raw",
                    dep_planned=_iso(leg.departure),
                    dep_actual=_iso(dep[0]) if isinstance(dep, tuple) else None,
                    dep_cancelled=isinstance(dep, tuple) and dep[1],
                    arr_planned=_iso(leg.arrival),
                    arr_actual=_iso(arr[0]),
                    arr_cancelled=arr[1],
                )
            )
    return results


def _raw_stop(leg, station, tag, planned, plans, fchg, last_fchg):
    """(actual time, cancelled) for one stop, "pending" if not reported yet, None if unknown."""
    kind, number = split_train(leg.train)
    pt = planned.strftime("%y%m%d%H%M")
    for eva in evas_for(station)[:3]:
        for s in plans.get(eva, []):
            tl, ev = s.find("tl"), s.find(tag)
            if tl is None or ev is None or ev.get("pt") != pt:
                continue
            line = (ev.get("l") or "").upper()
            if tl.get("n") != number and line not in (number, kind + number):
                continue
            changes = [(t, c) for t, c in fchg.get(eva, []) if c.get("id") == s.get("id")]
            if changes:
                change = max(changes, key=lambda tc: tc[0])[1].find(tag)
                if change is not None:
                    actual = _iris_time(change.get("ct")) or planned
                    return actual, change.get("clt") is not None or change.get("cs") == "c"
            if last_fchg.get(eva, datetime.min) > planned + timedelta(minutes=15):
                return planned, False  # reported after the stop and never changed: on time
            return "pending"
    return None


def _raw_files_for(leg: Leg) -> list[str]:
    days = [leg.departure.date()]
    if leg.departure.hour < 7:
        days.insert(0, leg.departure.date() - timedelta(days=1))  # plan fetched the evening before
    if leg.arrival.hour >= 20 or leg.arrival.date() != leg.departure.date():
        days.append(leg.arrival.date() + timedelta(days=1))  # changes reported after midnight
    files = []
    for d in days:
        files.extend(sorted(e["path"] for e in _raw_day(d) if e["path"].endswith(".parquet")))
    return files


def _raw_day(d: date) -> list[dict]:
    return _tree(f"raw_data/year={d.year}/month={d.month}/day={d.day}")


# --- helpers ----------------------------------------------------------------


def _tree(path: str) -> list[dict]:
    try:
        with urllib.request.urlopen(HF_TREE + path, timeout=30, context=_tls()) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise


@cache
def _tls() -> ssl.SSLContext:
    """Verify HTTPS against the operating system's trusted certificates (macOS Keychain,
    Windows certificate store). The packaged app's own OpenSSL only knows the CA paths of
    the build machine, so on other computers every request failed verification."""
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # noqa: BLE001 - fall back to Python's defaults
        return ssl.create_default_context()


@cache
def _duck() -> duckdb.DuckDBPyConnection:
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "duckdb_extensions.zip"
    if getattr(sys, "frozen", False) and bundled.is_file():
        # the packaged app ships httpfs, so a fresh machine needs no extension download
        from .store import data_dir

        target = data_dir() / "duckdb_extensions"
        with zipfile.ZipFile(bundled) as z:
            if any(not (target / name).exists() for name in z.namelist()):
                z.extractall(target)
        con = duckdb.connect(config={"extension_directory": str(target), "autoinstall_known_extensions": False})
    else:
        con = duckdb.connect()
        con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    return con


def _iris_time(value: str | None) -> datetime | None:
    return datetime.strptime(value, "%y%m%d%H%M") if value else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
