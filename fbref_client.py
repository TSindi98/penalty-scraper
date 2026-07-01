"""HTTP-Client für FBref, der Cloudflare via gecachten Cookies umgeht.

Verwendet eine curl_cffi Session, die Response-Cookies (v.a. __cf_bm-Refreshes)
automatisch mitträgt. Beim Skript-Start werden die initialen Cookies aus
cookies.json geladen (Nutzer muss die manuell aus Chrome exportieren).
"""
from __future__ import annotations

import json
from pathlib import Path

from curl_cffi import requests

COOKIES_FILE = Path(__file__).parent / "cookies.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)


class CloudflareBlocked(RuntimeError):
    """Cookies sind expired oder IP ist geblockt — Cookie-Refresh nötig."""


def _make_session() -> requests.Session:
    cookies = json.loads(COOKIES_FILE.read_text())
    session = requests.Session(impersonate="chrome120")
    session.headers.update(
        {
            "user-agent": USER_AGENT,
            "accept-language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
        }
    )
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".fbref.com")
    return session


_SESSION: requests.Session | None = None


def get(url: str) -> str:
    global _SESSION
    if _SESSION is None:
        _SESSION = _make_session()
    r = _SESSION.get(url, timeout=30)
    if "Just a moment" in r.text:
        raise CloudflareBlocked(
            "Cloudflare challenge — cookies abgelaufen. Neue holen (README)."
        )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} für {url}")
    return r.text
