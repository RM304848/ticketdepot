"""Static checks on the UI files."""

import re
from pathlib import Path

import pytest

UI = Path(__file__).parent.parent / "ticketdepot" / "ui"
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


CSS = (UI / "style.css").read_text(encoding="utf-8")
THEMES = CSS[: CSS.index("* { box-sizing")]  # the token blocks at the top
DEVICE_DARK = re.search(r':root:not\(\[data-theme="light"\]\) \{(.*?)\}', THEMES, re.S)[1]
CHOSEN_DARK = re.search(r':root\[data-theme="dark"\] \{(.*?)\}', THEMES, re.S)[1]


def _tokens(block: str) -> dict:
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", block))


def _theme(dark: bool) -> dict:
    tokens = _tokens(re.search(r":root \{(.*?)\n\}", THEMES, re.S)[1]) | (_tokens(CHOSEN_DARK) if dark else {})
    while any(v.startswith("var(") for v in tokens.values()):
        tokens = {k: tokens[v[4:-1]] if v.startswith("var(--") and v.endswith(")") else v for k, v in tokens.items()}
    return tokens


def _contrast(a: str, b: str) -> float:
    def lum(h):
        c = [int(h.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_hex_colors_only_in_the_theme_blocks():
    assert HEX.search(THEMES) and not HEX.search(CSS.replace(THEMES, ""))
    for name in ("app.js", "index.html"):
        text = (UI / name).read_text(encoding="utf-8")
        text = re.sub(r"&#\w+;", "", text)  # HTML entities are not colors
        assert not HEX.search(text), name


def test_palette_is_shades_of_teal():
    for token, value in {"--teal-100": "#b2d8d8", "--teal-300": "#66b2b2", "--teal-500": "#008080", "--teal-700": "#006666", "--teal-900": "#004c4c"}.items():
        assert f"{token}: {value};" in CSS


def test_dark_theme_is_the_same_whether_chosen_or_inherited():
    assert _tokens(DEVICE_DARK) == _tokens(CHOSEN_DARK) and "color-scheme: dark;" in CHOSEN_DARK
    assert "color-scheme: light dark;" in THEMES and ':root[data-theme="light"] { color-scheme: light; }' in THEMES


def test_dark_theme_is_the_original_one():
    dark = _theme(dark=True)
    assert (dark["--bg"], dark["--surface"], dark["--text"], dark["--accent"], dark["--emphasis"]) == ("#0e1717", "#142121", "#e6f0f0", "#66b2b2", "#b2d8d8")


@pytest.mark.parametrize("dark", [False, True], ids=["hell", "dunkel"])
def test_text_contrast_holds_in_both_themes(dark):
    t = _theme(dark)
    for ground in ("--bg", "--surface"):  # page and cards, as in finctl
        for ink in ("--text", "--muted", "--accent", "--emphasis", "--amber", "--red"):
            assert _contrast(t[ink], t[ground]) >= 4.5, (ink, ground)
        assert _contrast(t["--field"], t[ground]) >= 3.0, ("--field", ground)
    assert _contrast(t["--white"], t["--teal-500"]) >= 4.5  # primary buttons, both themes


def test_theme_is_applied_before_the_stylesheet_and_no_db_logo():
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert html.index('localStorage.getItem("theme")') < html.index('href="style.css"')
    assert 'id="theme"' in html and ">DB<" not in html


def test_external_links_open_safely():
    for name in ("app.js", "index.html"):
        text = (UI / name).read_text(encoding="utf-8")
        for m in re.finditer(r'target[:=]\s*"_blank"', text):
            assert "noopener" in text[m.start() : m.start() + 120], name
