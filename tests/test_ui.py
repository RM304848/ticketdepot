"""Static checks on the UI files."""

import re
from pathlib import Path

UI = Path(__file__).parent.parent / "ticketdepot" / "ui"
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def test_hex_colors_only_in_the_root_block():
    css = (UI / "style.css").read_text(encoding="utf-8")
    root = re.search(r":root\s*\{.*?\n\}", css, re.S)
    assert root and HEX.search(root[0])
    assert not HEX.search(css.replace(root[0], ""))
    for name in ("app.js", "index.html"):
        text = (UI / name).read_text(encoding="utf-8")
        text = re.sub(r"&#\w+;", "", text)  # HTML entities are not colors
        assert not HEX.search(text), name


def test_palette_is_shades_of_teal():
    css = (UI / "style.css").read_text(encoding="utf-8")
    for token, value in {"--teal-100": "#b2d8d8", "--teal-300": "#66b2b2", "--teal-500": "#008080", "--teal-700": "#006666", "--teal-900": "#004c4c"}.items():
        assert f"{token}: {value};" in css


def test_single_light_theme_and_no_db_logo():
    css = (UI / "style.css").read_text(encoding="utf-8")
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert "prefers-color-scheme" not in css and "color-scheme: light;" in css
    assert ">DB<" not in html


def test_external_links_open_safely():
    for name in ("app.js", "index.html"):
        text = (UI / name).read_text(encoding="utf-8")
        for m in re.finditer(r'target[:=]\s*"_blank"', text):
            assert "noopener" in text[m.start() : m.start() + 120], name
