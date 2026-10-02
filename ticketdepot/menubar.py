"""The macOS menu-bar item: reopen the page, quit the app.

pystray draws the tray icon on Windows, but on macOS it can only show a
coloured bitmap, and a coloured square stands out next to the system's own
monochrome symbols. Here the icon is an SF Symbol drawn as a template image,
so macOS tints it for light and dark menu bars like everything around it.

AppKit needs the main thread; the HTTP server runs on a second one.
"""

from __future__ import annotations

import functools
import signal
import sys
import threading
import webbrowser

#: SF Symbol of a ticket (macOS 13+).
SYMBOL = "ticket"
#: Shown instead when the system does not know the symbol.
FALLBACK = "TD"


def available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import AppKit  # noqa: F401
        from PyObjCTools import AppHelper  # noqa: F401
    except ImportError:
        return False
    return True


@functools.cache
def _target():
    """The class the menu reports to -- created once per process.

    An Objective-C class cannot be registered twice under the same name.
    """
    from Foundation import NSObject

    class TicketdepotMenuBar(NSObject):
        def open_(self, _sender) -> None:
            webbrowser.open(self.url)

        def quit_(self, _sender) -> None:
            # shutdown() waits for serve_forever to notice; not on the UI thread.
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    return TicketdepotMenuBar


def _menu(target, name: str):
    import AppKit

    menu = AppKit.NSMenu.alloc().init()
    for title, action in (("Öffnen", "open:"), (None, None), ("Beenden", "quit:")):
        if title is None:
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            continue
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        item.setTarget_(target)
        menu.addItem_(item)
    return menu


def _wake_event():
    import AppKit

    return AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(  # noqa: E501
        AppKit.NSEventTypeApplicationDefined, (0, 0), 0, 0, 0, None, 0, 0, 0)


def run(server, name: str = "Ticketdepot") -> None:
    """Serve in the background, show the icon. Returns once the server stops.

    "Beenden" in the menu and in the page do the same: the server shuts down,
    and the event loop ends with it.
    """
    import AppKit
    from PyObjCTools import AppHelper, MachSignals

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    target = _target().alloc().init()
    target.url, target.server = server.url, server

    item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
        AppKit.NSVariableStatusItemLength)
    button = item.button()
    image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(SYMBOL, name)
    if image is not None:
        image.setTemplate_(True)
        button.setImage_(image)
    else:
        button.setTitle_(FALLBACK)
    button.setToolTip_(name)
    item.setMenu_(_menu(target, name))

    def stop(*_) -> None:
        # Not AppHelper.stopEventLoop: that calls NSApp.terminate_, which exits
        # the process from C -- no `finally`, so the launcher could not remove
        # its port file. stop_ takes effect with the next event, hence one more.
        app.stop_(None)
        app.postEvent_atStart_(_wake_event(), True)

    def serve() -> None:
        try:
            server.serve_forever()
        finally:
            AppHelper.callAfter(stop)

    # Ctrl+C in a terminal: a Python signal handler never gets a turn inside
    # AppKit's loop, a Mach signal does.
    MachSignals.signal(signal.SIGINT, lambda *_: threading.Thread(
        target=server.shutdown, daemon=True).start())
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        app.run()
    finally:
        thread.join(timeout=5)
        AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(item)
