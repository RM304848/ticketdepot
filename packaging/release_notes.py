"""Release notes for one version: "Neu in <version>" from CHANGELOG.md, then the
download and first-start text from packaging/RELEASE_NOTES.md.

    python packaging/release_notes.py 0.1.5 > notes.md

Fails without a non-empty CHANGELOG section for the version, so a release never
goes out with download instructions only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def changes(changelog: str, version: str) -> str:
    """The body of "## <version> – <date>" (or "## <version>"), up to the next "## "."""
    m = re.search(rf"^## {re.escape(version)}(?: – [^\n]*)?\n(.*?)(?=^## |\Z)", changelog, re.S | re.M)
    body = m[1].strip() if m else ""
    if not body:
        raise SystemExit(f"CHANGELOG.md: kein Abschnitt „## {version}“ mit Inhalt – erst die Änderungen eintragen.")
    return body


def notes(version: str) -> str:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    static = (ROOT / "packaging" / "RELEASE_NOTES.md").read_text(encoding="utf-8").replace("VERSION", version)
    body = re.sub(r"\n +", " ", changes(changelog, version))  # GitHub shows every line break; one line per bullet
    return f"## Neu in {version}\n\n{body}\n\n{static}"


if __name__ == "__main__":
    sys.stdout.write(notes(sys.argv[1]))
