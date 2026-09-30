from datetime import datetime, timedelta

import pytest

from ticketdepot import rules
from ticketdepot.delays import LegDelay
from ticketdepot.models import Journey, Leg
from ticketdepot.rules import band_for, evaluate

NOW = datetime(2026, 9, 28, 12, 0)
DEP, ARR = datetime(2026, 8, 1, 15, 51), datetime(2026, 8, 1, 17, 51)
JOURNEY = Journey("Einfache Fahrt", [Leg("ICE 725", "Essen Hbf", "Frankfurt(Main)Hbf", DEP, ARR)])


def delayed(minutes: int, cancelled: bool = False, journey: Journey = JOURNEY) -> list[LegDelay]:
    leg = journey.legs[-1]
    actual = leg.arrival + timedelta(minutes=minutes)
    return [
        LegDelay(
            leg.train, "ok", "monthly",
            dep_planned=leg.departure.isoformat(), dep_actual=leg.departure.isoformat(),
            arr_planned=leg.arrival.isoformat(), arr_actual=actual.isoformat(),
            arr_cancelled=cancelled,
        )
    ]  # fmt: skip


def run(minutes, price=29.99, cancelled=False, now=NOW, **kw):
    return evaluate(JOURNEY, price, delayed(minutes, cancelled), now=now, **kw)


# --- thresholds 20 / 60 / 120 and the 4 € floor


@pytest.mark.parametrize(
    ("minutes", "state"),
    [(0, "no_action"), (19, "no_action"), (20, "ask"), (59, "ask"), (60, "ask"), (120, "ask")],
)
def test_question_only_when_an_answer_changes_something(minutes, state):
    assert run(minutes).state == state


@pytest.mark.parametrize(
    ("minutes", "kind", "label"),
    [
        (20, "kein_anspruch", "Kein Anspruch (unter 60 min)"),
        (59, "kein_anspruch", "Kein Anspruch (unter 60 min)"),
        (60, "entschaedigung", "7,50 €"),
        (119, "entschaedigung", "7,50 €"),
        (120, "entschaedigung", "15,00 €"),
    ],
)
def test_ridden_answer_by_threshold(minutes, kind, label):
    ja = run(minutes).answers["ja"]
    assert (ja["kind"], ja["label"]) == (kind, label)
    assert ja["force_majeure"] is (kind == "entschaedigung")


@pytest.mark.parametrize(
    ("minutes", "kind"),
    [(20, "vorrat"), (59, "vorrat"), (60, "erstattung"), (120, "erstattung")],
)
def test_not_ridden_answer_by_threshold(minutes, kind):
    assert run(minutes).answers["nein"]["kind"] == kind


@pytest.mark.parametrize(("price", "state"), [(15.96, "none"), (16.00, "claim")])  # 25 % = 3.99 € / 4.00 €
def test_four_euro_floor(price, state):
    v = run(75, price=price, ridden="ja")
    assert v.state == state
    if state == "none":
        assert v.headline == "Kein Anspruch (unter 4 €)" and "3,99 €" in v.detail and v.rule == "mindestbetrag"
    else:
        assert v.amount_eur == 4.00


@pytest.mark.parametrize(
    ("minutes", "band"),
    [(19, None), (20, "d20"), (59, "d20"), (60, "d60"), (119, "d60"), (120, "d120"), (300, "d120")],
)
def test_bands_lower_inclusive_upper_exclusive(minutes, band):
    assert band_for(minutes, False) == band
    assert run(minutes).band == band


def test_cancelled_train_is_only_in_the_ausfall_band():
    assert run(0, cancelled=True).band == "ausfall"


# --- the acceptance tickets


def test_ice_619_return_ticket_half_basis_and_travel_date_before_midnight():
    # Rückfahrt of a Sparpreis Hin/Rück for 59,98 €: departs 14.08. 23:28, arrives 15.08. 01:17
    leg = Leg("ICE 619", "Düsseldorf Hbf", "Frankfurt(Main)Hbf", datetime(2026, 8, 14, 23, 28), datetime(2026, 8, 15, 1, 17))
    journey = Journey("Rückfahrt", [leg])
    v = evaluate(journey, 29.99, delayed(63, journey=journey), now=NOW)
    assert v.state == "ask" and v.delay_min == 63
    assert v.answers["ja"]["label"] == "7,50 €" and v.answers["ja"]["force_majeure"]
    assert v.answers["nein"]["label"] == "29,99 € zurück" and not v.answers["nein"]["force_majeure"]
    assert v.reuse_limit == "2027-08-14" and v.claim_deadline == "2026-11-14"
    assert v.due == "2026-11-14" and v.action_date == "2026-10-24" and not v.due_soon


def test_ice_2466_under_four_euros_still_asks_because_not_ridden_pays():
    leg = Leg("ICE 2466", "Hamm(Westf)Hbf", "Köln Hbf", datetime(2026, 8, 14, 19, 48), datetime(2026, 8, 14, 21, 23))
    journey = Journey("Einfache Fahrt", [leg])
    v = evaluate(journey, 12.99, delayed(75, journey=journey), now=NOW)
    assert v.state == "ask"
    assert v.answers["ja"]["label"] == "Kein Anspruch (unter 4 €)" and "3,25 €" in v.answers["ja"]["note"]
    assert v.answers["nein"]["label"] == "12,99 € zurück"
    ridden = evaluate(journey, 12.99, delayed(75, journey=journey), ridden="ja", now=NOW)
    assert ridden.state == "none" and ridden.outcomes == ["kein_anspruch"]


# --- after answering


def test_ridden_with_compensation_is_a_claim_with_force_majeure():
    v = run(125, ridden="ja")
    assert v.state == "claim" and v.claim_kind == "entschaedigung" and v.pct == 50 and v.amount_eur == 15.00
    assert v.force_majeure and "hoehere_gewalt" in v.sources


def test_not_ridden_over_60_offers_refund_or_vorrat_as_alternatives():
    v = run(61, ridden="nein")
    assert v.state == "choose" and [o["kind"] for o in v.options] == ["erstattung", "vorrat"]
    assert v.options[0]["label"] == "29,99 € zurück" and v.options[1]["label"] == "später fahren bis 01.08.2027"
    assert not any(o["force_majeure"] for o in v.options)
    assert v.reuse_until is None  # not in the Vorrat until chosen


def test_choice_refund():
    v = run(61, ridden="nein", choice="erstattung")
    assert v.state == "claim" and v.claim_kind == "erstattung" and v.amount_eur == 29.99 and not v.force_majeure
    assert v.reuse_until is None


def test_choice_vorrat():
    v = run(61, ridden="nein", choice="vorrat")
    assert v.state == "reuse" and v.reuse_until == "2027-08-01" and v.due_kind == "vorrat"
    assert v.action_date == "2027-07-02" and not v.force_majeure


def test_not_ridden_20_to_59_goes_straight_to_the_vorrat():
    v = run(24, ridden="nein")
    assert v.state == "reuse" and v.reuse_until == "2027-08-01"
    assert "ICE 725 kam am 01.08.2026 um 18:15 statt 17:51" in v.evidence


def test_used_later():
    v = run(30, ridden="nein", vorrat_used_on="2026-09-01")
    assert v.state == "done" and v.reuse_until is None


def test_vorrat_expires_after_one_year():
    v = run(30, ridden="nein", now=datetime(2027, 8, 2))
    assert v.state == "done" and v.reuse_until is None and v.headline == "Abgelaufen"


def test_vorrat_due_soon_30_days_before_expiry():
    assert not run(30, ridden="nein", now=datetime(2027, 7, 1)).due_soon
    assert run(30, ridden="nein", now=datetime(2027, 7, 2)).due_soon


def test_claim_due_soon_21_days_before_deadline():
    assert not run(75, ridden="ja", now=datetime(2026, 10, 10)).due_soon
    assert run(75, ridden="ja", now=datetime(2026, 10, 11)).due_soon  # deadline 01.11.2026


def test_claimed_and_paid():
    v = run(61, ridden="nein", choice="erstattung", claim_status="beantragt")
    assert v.state == "claimed" and v.outcomes == ["beantragt"] and v.due is None
    v = run(75, ridden="ja", claim_status="ausgezahlt")
    assert v.state == "done" and v.outcomes == ["ausgezahlt"]


# --- outcomes for the filter chips


def test_unanswered_matches_every_reachable_outcome():
    assert run(75).outcomes == ["entschaedigung", "erstattung", "wiederverwendbar"]
    assert run(30).outcomes == ["kein_anspruch", "wiederverwendbar"]
    assert run(5).outcomes == ["kein_anspruch"]


# --- arrival, disruptions, data


def test_cancelled_train_asks_for_the_arrival_when_ridden():
    v = run(0, cancelled=True)
    assert v.answers["ja"]["kind"] == "ankunft" and v.answers["nein"]["kind"] == "erstattung"
    v = run(0, cancelled=True, ridden="ja")
    assert v.state == "needs_arrival" and "ausgefallen" in v.detail
    v = run(0, cancelled=True, ridden="ja", manual_arrival=ARR + timedelta(minutes=87))
    assert v.state == "claim" and v.amount_eur == 7.50 and v.band == "ausfall"


def test_other_train_arrival_overrides_the_booked_train():
    v = run(40, ridden="ja", manual_arrival=ARR + timedelta(minutes=124))
    assert v.delay_min == 124 and v.amount_eur == 15.00


def test_missed_connection_detected():
    t1 = Leg("RE 1", "A", "B", datetime(2026, 8, 1, 10), datetime(2026, 8, 1, 11))
    t2 = Leg("ICE 1", "B", "C", datetime(2026, 8, 1, 11, 10), datetime(2026, 8, 1, 13))
    journey = Journey("Einfache Fahrt", [t1, t2])
    delays = [
        LegDelay("RE 1", "ok", arr_planned=t1.arrival.isoformat(), arr_actual="2026-08-01T11:15:00"),
        LegDelay("ICE 1", "ok", dep_actual="2026-08-01T11:10:00", arr_planned=t2.arrival.isoformat(), arr_actual=t2.arrival.isoformat()),
    ]
    v = evaluate(journey, 50, delays, ridden="ja", now=NOW)
    assert v.missed_connection and v.zugbindung_aufgehoben and v.state == "needs_arrival"


def test_future_and_waiting():
    assert evaluate(JOURNEY, 29.99, None, now=datetime(2026, 7, 30)).state == "future"
    assert evaluate(JOURNEY, 29.99, None, now=NOW).state == "waiting"


def test_evidence_uses_the_actual_arrival_day():
    v = run(24 * 60 - 60 * 17 - 51 + 25, ridden="nein")  # arrives 00:25 the next day
    assert "kam am 02.08.2026 um 00:25 statt 17:51" in v.evidence


def test_controlled_is_only_a_hint():
    v = run(24, ridden="nein", controlled="ja")
    assert v.state == "reuse" and v.warnings


# --- the rules module itself


def test_every_rule_has_a_verified_source():
    for key, rule in rules.RULES.items():
        assert rule.source_url.startswith("https://www.bahn.de/"), key


def test_force_majeure_text_lives_in_rules():
    assert rules.config()["force_majeure_line"] == rules.FORCE_MAJEURE_LINE
