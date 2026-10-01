"""Zugausfall, Teilausfall, Haltausfall, missed connections and early departures."""

from datetime import datetime, timedelta

from ticketdepot import delays
from ticketdepot.delays import LegDelay
from ticketdepot.models import Journey, Leg
from ticketdepot.rules import cancellation_text, evaluate

NOW = datetime(2026, 9, 28, 12, 0)
D = datetime(2026, 8, 14)


def t(hm: str) -> datetime:
    h, m = map(int, hm.split(":"))
    return D.replace(hour=h, minute=m)


def stop(station, arr=None, dep=None, arr_c=False, dep_c=False, eva=None):
    return {
        "type": "ICE", "number": "24", "line": None, "station": station, "xml_station": station, "eva": eva,
        "arr_pt": t(arr) if arr else None, "arr_ct": None, "arr_cancel": arr_c,
        "dep_pt": t(dep) if dep else None, "dep_ct": None, "dep_cancel": dep_c,
    }  # fmt: skip


# The real run of ICE 24 on 14.08.2026: ended in Frankfurt, everything after it cancelled.
ICE_24 = [
    stop("Würzburg Hbf", "18:24", "18:26"),
    stop("Hanau Hbf", "19:17", "19:18"),
    stop("Frankfurt (Main) Hbf", "19:37", "19:43", dep_c=True),
    stop("Mainz Hbf", "20:18", "20:19", True, True),
    stop("Koblenz Hbf", "21:10", "21:12", True, True),
    stop("Bonn Hbf", "21:43", "21:44", True, True),
    stop("Köln Hbf", "22:06", "22:11", True, True),
    stop("Dortmund Hbf", "23:30", None, True),
]


def leg(origin, dep, dest, arr):
    return Leg("ICE 24", origin, dest, t(dep), t(arr))


def classify(stops, origin, dep, dest, arr):
    lg = leg(origin, dep, dest, arr)
    return lg, delays._leg_from_stops(lg, stops)


def test_real_ice_24_is_a_teilausfall_that_ended_in_frankfurt():
    lg, d = classify(ICE_24, "Hanau Hbf", "19:18", "Bonn Hbf", "21:43")
    assert (d.cancel_kind, d.arr_note, d.ended_at, d.dep_cancelled) == ("teilausfall", "end", "Frankfurt (Main) Hbf", False)
    assert cancellation_text(lg, d) == "ICE 24 am 14.08.2026: endete vorzeitig in Frankfurt (Main) Hbf."


def test_haltausfall_train_ran_through_the_destination():
    stops = [stop("A", None, "10:00"), stop("B", "11:00", "11:01", True, True), stop("C", "12:00")]
    lg, d = classify(stops, "A", "10:00", "B", "11:00")
    assert (d.cancel_kind, d.arr_note) == ("haltausfall", "halt")
    assert cancellation_text(lg, d) == "ICE 24 am 14.08.2026: hielt nicht in B."


def test_zugausfall_on_the_whole_stretch():
    stops = [stop("A", None, "10:00", dep_c=True), stop("B", "11:00", "11:01", True, True), stop("C", "12:00", None, True)]
    lg, d = classify(stops, "A", "10:00", "C", "12:00")
    assert d.cancel_kind == "zugausfall"
    assert cancellation_text(lg, d) == "ICE 24 fiel zwischen A und C aus."


def test_started_late():
    stops = [stop("A", None, "10:00", dep_c=True), stop("B", "11:00", "11:01", True), stop("C", "12:00")]
    lg, d = classify(stops, "A", "10:00", "C", "12:00")
    assert (d.cancel_kind, d.dep_note, d.started_at) == ("teilausfall", "start", "B")


def test_raw_data_without_the_run_stays_factual_per_stop():
    lg = leg("A", "10:00", "C", "12:00")
    d = LegDelay("ICE 24", "ok", "raw", arr_planned=lg.arrival.isoformat(), arr_actual=lg.arrival.isoformat(), arr_cancelled=True)
    assert cancellation_text(lg, d) == "ICE 24 am 14.08.2026: Ankunft in C entfiel."


def test_old_stored_delays_without_the_new_fields_still_load():
    assert LegDelay.from_dict({"train": "ICE 1", "status": "ok", "unknown_future_field": 1}).cancel_kind is None


# --- rules


DEP, ARR = datetime(2026, 8, 1, 15, 0), datetime(2026, 8, 1, 17, 0)
SINGLE = Journey("Einfache Fahrt", [Leg("ICE 1", "A", "C", DEP, ARR)])
TWO = Journey("Einfache Fahrt", [
    Leg("RE 1", "A", "B", DEP, DEP + timedelta(minutes=50)),
    Leg("ICE 2", "B", "C", DEP + timedelta(minutes=60), ARR),
])  # fmt: skip


def ok(lg, arr_delay=0, dep_delay=0, **kw):
    return LegDelay(
        lg.train, "ok", "monthly",
        dep_planned=lg.departure.isoformat(), dep_actual=(lg.departure + timedelta(minutes=dep_delay)).isoformat(),
        arr_planned=lg.arrival.isoformat(), arr_actual=(lg.arrival + timedelta(minutes=arr_delay)).isoformat(), **kw,
    )  # fmt: skip


def test_teilausfall_labels_and_conditional_refund():
    d = ok(SINGLE.legs[0], arr_cancelled=True, cancel_kind="teilausfall", arr_note="end", ended_at="B")
    v = evaluate(SINGLE, 29.99, [d], now=NOW)
    assert v.disruption == "Teilausfall" and v.band == "ausfall" and v.zugbindung_aufgehoben
    assert v.answers["nein"]["kind"] == "erstattung" and "60 min" in v.answers["nein"]["condition"]
    assert "endete vorzeitig in B" in v.evidence and "ausgefallen" not in v.evidence


def test_refund_after_a_plain_delay_has_no_condition():
    assert run_single(75).answers["nein"]["condition"] == ""


def run_single(arr_delay, **kw):
    return evaluate(SINGLE, 29.99, [ok(SINGLE.legs[0], arr_delay)], **{"now": NOW, **kw})


def test_missed_connection_can_be_reported_only_with_a_transfer():
    assert not run_single(5).can_report_missed
    v = evaluate(TWO, 29.99, [ok(TWO.legs[0], 3), ok(TWO.legs[1], 4)], now=NOW)
    assert v.state == "no_action" and v.can_report_missed


def test_reported_missed_connection_lifts_zugbindung_and_asks_for_the_arrival():
    data = [ok(TWO.legs[0], 3), ok(TWO.legs[1], 4)]
    v = evaluate(TWO, 29.99, data, reported="anschluss", now=NOW)
    assert v.state == "ask" and v.zugbindung_aufgehoben and v.disruption == "Anschluss verpasst (eigene Angabe)"
    assert v.answers["ja"]["kind"] == "ankunft" and v.answers["nein"]["kind"] == "erstattung"
    assert "Anschluss in B laut eigener Angabe verpasst." in v.evidence and "anschluss" in v.sources
    assert not v.can_report_missed
    vorrat = evaluate(TWO, 29.99, data, reported="anschluss", ridden="nein", choice="vorrat", now=NOW)
    assert vorrat.state == "reuse" and vorrat.reuse_until == "2027-08-01"


def test_detected_missed_connection_is_not_labelled_as_own_statement():
    v = evaluate(TWO, 29.99, [ok(TWO.legs[0], 15), ok(TWO.legs[1], 0)], now=NOW)
    assert v.disruption == "Anschluss verpasst" and "Anschluss in B verpasst." in v.evidence


def test_train_missing_from_final_data_can_be_reported_as_cancelled():
    missing = [LegDelay("ICE 1", "not_found", "monthly")]
    v = evaluate(SINGLE, 29.99, missing, now=NOW)
    assert v.state == "missing"
    v = evaluate(SINGLE, 29.99, missing, reported="ausfall", now=NOW)
    assert v.state == "ask" and v.disruption == "Ausfall (eigene Angabe)" and "laut eigener Angabe ausgefallen" in v.evidence


def test_early_departure_lifts_zugbindung():
    v = evaluate(SINGLE, 29.99, [ok(SINGLE.legs[0], 2, dep_delay=-4)], now=NOW)
    assert v.zugbindung_aufgehoben and v.state == "ask" and v.early_departure
    assert v.answers["nein"]["kind"] == "vorrat" and v.answers["ja"]["kind"] == "kein_anspruch"
    assert "4 min zu früh" in v.evidence


def test_ask_card_shows_the_vorrat_behind_the_refund():
    v = run_single(75)
    assert v.question == "Bist du gefahren?" and v.answer_keys == {"ja": "Ja", "nein": "Nein"}
    assert v.answers["nein"]["kind"] == "erstattung" and v.answers["nein"]["also"] == "oder später fahren bis 01.08.2027"
    assert run_single(30).answers["nein"]["also"] == ""  # Vorrat only: nothing behind it


def test_missed_connection_asks_whether_the_trip_was_abandoned():
    v = evaluate(TWO, 29.99, [ok(TWO.legs[0], 15), ok(TWO.legs[1], 0)], now=NOW)
    assert v.question == "Bist du trotzdem ans Ziel gefahren?"
    assert v.answer_keys == {"ja": "Ja, später angekommen", "nein": "Nein, Reise abgebrochen"}


def test_reported_missed_connection_keeps_the_delay_from_the_data():
    # real case: ICE 2582 on 22.06.2026 was +88 at the destination anyway
    late = evaluate(TWO, 14.99, [ok(TWO.legs[0], 6), ok(TWO.legs[1], 88)], reported="anschluss", now=NOW)
    assert late.delay_min == 88 and late.answers["ja"]["kind"] == "ankunft"
    assert late.answers["nein"]["condition"] == ""  # ≥ 60 min was to be expected in any case
    on_time = evaluate(TWO, 14.99, [ok(TWO.legs[0], 6), ok(TWO.legs[1], 4)], reported="anschluss", now=NOW)
    assert "60 min" in on_time.answers["nein"]["condition"]


def test_past_the_apps_deadline_points_to_dbs_limit():
    # travelled 01.08., the app's 3-month deadline is 01.11.2026, DB's limit 01.08.2027
    before = run_single(75, now=datetime(2026, 10, 20, 12, 0))
    assert (before.due, before.overdue, before.due_soon) == ("2026-11-01", False, True)
    after = run_single(75, now=datetime(2026, 11, 5, 12, 0))
    assert (after.due, after.overdue, after.due_soon, after.action_date) == ("2027-08-01", True, True, "2026-11-05")
    vorrat = run_single(30, ridden="nein", now=datetime(2026, 11, 5, 12, 0))
    assert (vorrat.due, vorrat.overdue) == ("2027-08-01", False)


def test_forecast_lifted_zugbindung_although_the_train_made_up_the_delay():
    on_time = run_single(5)
    assert on_time.state == "no_action" and not on_time.zugbindung_aufgehoben
    v = run_single(5, reported="zugbindung", ridden="nein", choice="vorrat")
    assert v.state == "reuse" and v.zugbindung_aufgehoben and v.reuse_until == "2027-08-01"
    assert v.evidence.startswith("Zugbindung für ICE 1 am 01.08.2026 laut eigener Angabe aufgehoben")
    assert "(+5 min)" in v.evidence and "Quelle: DB-Echtzeitdaten (IRIS)" in v.evidence
    asked = run_single(5, reported="zugbindung")
    assert asked.state == "ask" and asked.answers["nein"]["kind"] == "vorrat"
    assert asked.answers["ja"]["kind"] == "kein_anspruch" and asked.detail.startswith("Zugbindung aufgehoben (eigene Angabe)")
    assert run_single(75, reported="zugbindung").answers["nein"]["kind"] == "erstattung"  # the data says more


def test_stated_zugbindung_without_any_data():
    missing = [LegDelay("ICE 1", "not_found", "monthly")]
    v = evaluate(SINGLE, 29.99, missing, reported="zugbindung", ridden="nein", choice="vorrat", now=NOW)
    assert v.state == "reuse" and "IRIS" not in v.evidence
    asked = evaluate(SINGLE, 29.99, None, reported="zugbindung", now=NOW)
    assert asked.state == "ask" and asked.answers["ja"]["kind"] == "ankunft"
    on_the_day = evaluate(SINGLE, 29.99, None, reported="zugbindung", ridden="nein", choice="vorrat", now=DEP - timedelta(hours=1))
    assert on_the_day.state == "reuse"
