import xml.etree.ElementTree as ET
from datetime import datetime

import truststore

from ticketdepot import delays
from ticketdepot.models import Leg


def test_https_uses_the_os_certificate_store():
    # the packaged app has no CA bundle of its own; the OS store must be used
    assert isinstance(delays._tls(), truststore.SSLContext)


# The real ICE 799 on 03.09.2026: the ticket says Kassel-Wilhelmshöhe 14:10 → Karlsruhe Hbf 17:16,
# the timetable on the day said 14:13 → 17:05.
ICE_799 = Leg("ICE 799", "Kassel-Wilhelmshöhe", "Karlsruhe Hbf", datetime(2026, 9, 3, 14, 10), datetime(2026, 9, 3, 17, 16))


def _stop(station, eva, arr=None, dep=None, arr_ct=None, number="799"):
    return {
        "type": "ICE", "number": number, "line": None, "station": station, "xml_station": station, "eva": eva,
        "arr_pt": arr, "arr_ct": arr_ct, "arr_cancel": False, "dep_pt": dep, "dep_ct": None, "dep_cancel": False,
    }  # fmt: skip


def test_monthly_matches_a_train_whose_timetable_changed_after_booking():
    day = datetime(2026, 9, 3)
    stops = [
        _stop("Kassel-Wilhelmshöhe", "08003200", day.replace(hour=14, minute=11), day.replace(hour=14, minute=13)),
        _stop("Karlsruhe Hbf", "08000191", day.replace(hour=17, minute=5), arr_ct=day.replace(hour=17, minute=40)),
        _stop("Karlsruhe Hbf", "08000191", day.replace(hour=19, minute=5), number="799"),  # too far off
    ]
    d = delays._leg_from_stops(ICE_799, stops)
    assert (d.status, d.dep_actual, d.arr_actual) == ("ok", "2026-09-03T14:13:00", "2026-09-03T17:40:00")
    assert d.arrival_delay_min == 24  # against the ticket's 17:16
    assert d.early_departure_min == 0


def test_monthly_ignores_a_run_more_than_an_hour_off():
    stops = [_stop("Karlsruhe Hbf", "08000191", datetime(2026, 9, 3, 18, 30))]
    assert delays._leg_from_stops(ICE_799, stops).status == "not_found"


def test_raw_matches_a_train_whose_timetable_changed_after_booking():
    plan = ET.fromstring(
        '<s id="x-1"><tl c="ICE" n="799"/><ar pt="2609031705" l=""/></s>'
    )  # fmt: skip
    change = ET.fromstring('<s id="x-1"><ar ct="2609031712"/></s>')
    fetched = datetime(2026, 9, 3, 17, 30)
    found = delays._raw_stop(
        ICE_799, "Karlsruhe Hbf", "ar", ICE_799.arrival, {"08000191": [plan]}, {"08000191": [(fetched, change)]}, {"08000191": fetched}
    )
    assert found == (datetime(2026, 9, 3, 17, 12), False)


def test_raw_without_changes_uses_the_timetable_of_the_day():
    plan = ET.fromstring('<s id="x-1"><tl c="ICE" n="799"/><ar pt="2609031705"/></s>')
    later = datetime(2026, 9, 3, 18, 0)
    found = delays._raw_stop(ICE_799, "Karlsruhe Hbf", "ar", ICE_799.arrival, {"08000191": [plan]}, {}, {"08000191": later})
    assert found == (datetime(2026, 9, 3, 17, 5), False)
