"""Station name → EVA number, for the raw IRIS data whose URLs are keyed by EVA.

Tickets print "Frankfurt(Main)Hbf", the station list says "Frankfurt (Main) Hbf";
both fold to the same key once spaces and punctuation are dropped.
The list is config/eva_to_station_name.json from piebro/deutsche-bahn-data.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

_DATA = Path(__file__).parent / "data" / "eva_to_station_name.json"


def fold(name: str) -> str:
    name = name.lower().replace("ß", "ss")
    return re.sub(r"[^0-9a-zäöü]", "", name)


@cache
def _index() -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for eva, name in json.loads(_DATA.read_text(encoding="utf-8")).items():
        index.setdefault(fold(name), []).append(eva)
    for evas in index.values():
        # main EVAs (0800xxxx) before the sub-platform ones (0809xxxx)
        evas.sort(key=lambda e: (not e.startswith("0800"), e))
    return index


def evas_for(name: str) -> list[str]:
    return _index().get(fold(name), [])
