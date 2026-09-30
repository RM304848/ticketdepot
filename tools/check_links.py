"""Check that every official source linked from the rules still answers.

Run by hand (python tools/check_links.py), not on app start. bahn.de answers
scripts without a browser User-Agent with errors, so one is sent; 403, 429 and
timeouts are reported as "manuell prüfen" rather than broken.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ticketdepot.rules import RULES  # noqa: E402

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
UNSURE = {403, 429}


def check(url: str) -> tuple[str, str]:
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept-Language": "de-DE,de"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                final = resp.geturl()
                if "404" in final:  # bahn.de redirects missing pages to /404page
                    return "kaputt", f"weitergeleitet auf {final}"
                return "ok", str(resp.status)
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (405, 501, *UNSURE):
                continue  # some servers refuse HEAD; try GET
            return ("manuell prüfen" if e.code in UNSURE else "kaputt"), str(e.code)
        except (urllib.error.URLError, TimeoutError) as e:
            reason = getattr(e, "reason", e)
            return ("manuell prüfen" if isinstance(reason, TimeoutError) or "timed out" in str(reason) else "kaputt"), str(reason)
    return "manuell prüfen", "keine Antwort"


def main() -> int:
    urls: dict[str, list[str]] = {}
    for key, rule in RULES.items():
        if rule.source_url:
            urls.setdefault(rule.source_url, []).append(key)
        else:
            print(f"LEER            {key}: keine Quelle hinterlegt")
    broken = 0
    for url, keys in urls.items():
        status, info = check(url)
        broken += status == "kaputt"
        print(f"{status.upper():<15} {', '.join(keys)}: {url} ({info})")
    print(f"\n{len(urls)} Links geprüft, {broken} kaputt.")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
