"""The macOS menu-bar item: its menu, and the fallback without AppKit."""

from __future__ import annotations

import sys

import pytest

from ticketdepot import menubar


def test_without_appkit_there_is_no_native_menu_bar(monkeypatch):
    """Windows, or a Python without pyobjc: pystray (or no tray) as before."""
    monkeypatch.setitem(sys.modules, "AppKit", None)
    assert menubar.available() is False


@pytest.mark.skipif(not menubar.available(), reason="macOS with pyobjc only")
def test_the_menu_opens_and_quits(monkeypatch):
    """The menu itself, without putting an icon into the menu bar on every run."""
    import threading

    import AppKit

    stopped = threading.Event()

    class Server:
        def shutdown(self):
            stopped.set()

    opened = []
    monkeypatch.setattr(menubar.webbrowser, "open", opened.append)
    target = menubar._target().alloc().init()
    target.url, target.server = "http://127.0.0.1:1/", Server()
    menu = menubar._menu(target, "Ticketdepot")

    titles = [menu.itemAtIndex_(i).title() for i in range(menu.numberOfItems())]
    assert titles == ["Öffnen", "", "Beenden"]
    for i in (0, 2):
        item = menu.itemAtIndex_(i)
        AppKit.NSApplication.sharedApplication().sendAction_to_from_(
            item.action(), item.target(), item)
    assert opened == ["http://127.0.0.1:1/"] and stopped.wait(2)
    # An SF Symbol this system knows -- otherwise only the fallback text shows.
    assert AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
        menubar.SYMBOL, None) is not None
