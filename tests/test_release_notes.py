"""The GitHub release text: what's new from CHANGELOG.md, then the download help."""

import importlib.util
from pathlib import Path

import pytest

from ticketdepot import __version__

ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("release_notes", ROOT / "packaging" / "release_notes.py")
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)


def test_the_current_version_has_its_changes_written_down():
    # bump __version__ only together with a CHANGELOG section: the tag build runs this test
    notes = release_notes.notes(__version__)
    assert notes.startswith(f"## Neu in {__version__}\n\n- ")
    assert f"Ticketdepot-{__version__}-windows.exe" in notes and "VERSION" not in notes
    news = notes.split("\n\n")[1]
    assert all(line.startswith("- ") for line in news.splitlines())  # one line per bullet


def test_a_version_without_changes_stops_the_release():
    changelog = "## Unveröffentlicht\n\n- etwas\n\n## 9.9.9 – 2030-01-01\n\n## 9.9.8 – 2029-01-01\n\n- alt\n"
    with pytest.raises(SystemExit, match="9.9.9"):
        release_notes.changes(changelog, "9.9.9")
    with pytest.raises(SystemExit):
        release_notes.changes(changelog, "9.9.7")
    assert release_notes.changes(changelog, "9.9.8") == "- alt"
