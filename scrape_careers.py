"""Holt für jeden Elfmeter-Schützen die Karriere-Elfmeter-Statistik von FBref.

Schritt 1: Liga-Player-Stats-Seite laden → Mapping Spielername → FBref-Player-URL.
Schritt 2: Pro Schütze: FBref-Player-Standard-Stats-Seite laden → Season-History-Tabelle
          mit PKatt pro Saison (Vereinsspiele) parsen. In JSON pro Spieler speichern.

build_dataset.py nutzt das später, um die Karriere-Elfmeter *bis zum Zeitpunkt*
jedes Elfmeters zu berechnen.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup, Comment

from fbref_client import get, CloudflareBlocked

DATASET_CSV = Path(__file__).parent / "data" / "processed" / "penalties_pl_2024_25.csv"
PLAYER_MAP_FILE = Path(__file__).parent / "data" / "raw" / "player_url_map.json"
CAREER_DIR = Path(__file__).parent / "data" / "raw" / "careers"

LEAGUE_STATS_URL = (
    "https://fbref.com/en/comps/9/2024-2025/2024-2025-Premier-League-Stats"
)

# Referenz-Saison, ab der wir "vorherige" Karriere-Elfmeter zählen:
# Für einen Elfmeter in Saison 2024/25 summieren wir PKatt aller Saisons *vor* 2024/25.
CURRENT_SEASON = "2024-2025"

SLEEP_BETWEEN = 4.0


def load_shooter_names() -> list[str]:
    rows = list(csv.DictReader(DATASET_CSV.open()))
    seen: dict[str, None] = {}
    for r in rows:
        seen.setdefault(r["shooter_name"], None)
    return list(seen)


def _extract_player_links(soup_like) -> dict[str, str]:
    """Sammelt name → /en/players/... Links aus einem Soup-Fragment."""
    m: dict[str, str] = {}
    for a in soup_like.find_all("a", href=lambda h: h and h.startswith("/en/players/")):
        name = a.get_text(strip=True)
        href = a["href"]
        if name:
            m.setdefault(name, "https://fbref.com" + href)
    return m


def build_player_url_map() -> dict[str, str]:
    """Ein Request auf die PL-Season-Stats-Seite; gibt name → player_url für alle Spieler zurück.
    Sucht auch in HTML-Kommentaren, weil FBref viele Tabellen dort versteckt."""
    if PLAYER_MAP_FILE.exists():
        return json.loads(PLAYER_MAP_FILE.read_text())
    print(f"Loading {LEAGUE_STATS_URL}", file=sys.stderr)
    html = get(LEAGUE_STATS_URL)
    soup = BeautifulSoup(html, "lxml")
    mapping = _extract_player_links(soup)
    # HTML-Kommentare aufmachen und dort auch suchen
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        if "/en/players/" in str(c):
            inner = BeautifulSoup(str(c), "lxml")
            for name, url in _extract_player_links(inner).items():
                mapping.setdefault(name, url)
    PLAYER_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLAYER_MAP_FILE.write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
    print(f"Mapped {len(mapping)} players")
    return mapping


STANDARD_TABLE_IDS = [
    "stats_standard_dom_lg",     # Domestic League
    "stats_standard_dom_cup",    # Domestic Cup (DFB-Pokal, FA Cup, ...)
    "stats_standard_intl_cup",   # International Club (CL, EL, Conference)
    "stats_standard_natl_tm",    # National Team
]


def parse_career_pkatt(html: str) -> list[dict]:
    """Sammelt Elfmeter-Statistik aus allen Standard-Stats-Tabellen einer Player-Page
    (Liga, Pokal, internationale Klub-Comps, Nationalmannschaft). Eine Zeile pro
    (Season, Comp)."""
    soup = BeautifulSoup(html, "lxml")

    def find_table(node, tid: str):
        # Erst direkt, dann in HTML-Kommentaren suchen (FBref versteckt viele Tabellen dort)
        t = node.find("table", id=tid)
        if t:
            return t
        for c in node.find_all(string=lambda x: isinstance(x, Comment)):
            if tid in str(c):
                inner = BeautifulSoup(str(c), "lxml")
                t = inner.find("table", id=tid)
                if t:
                    return t
        return None

    result = []
    for tid in STANDARD_TABLE_IDS:
        table = find_table(soup, tid)
        if not table:
            continue
        tbody = table.find("tbody")
        if not tbody:
            continue
        for row in tbody.find_all("tr"):
            if "thead" in (row.get("class") or []):
                continue
            season_cell = row.find(attrs={"data-stat": "year_id"})
            pkatt_cell = row.find(attrs={"data-stat": "pens_att"})
            pk_cell = row.find(attrs={"data-stat": "pens_made"})
            squad_cell = row.find(attrs={"data-stat": "team"})
            comp_cell = row.find(attrs={"data-stat": "comp_level"})
            if not season_cell:
                continue
            season = season_cell.get_text(strip=True)
            try:
                pkatt = int((pkatt_cell.get_text(strip=True) if pkatt_cell else "") or 0)
                pk = int((pk_cell.get_text(strip=True) if pk_cell else "") or 0)
            except ValueError:
                continue
            result.append(
                {
                    "season": season,
                    "team": squad_cell.get_text(strip=True) if squad_cell else "",
                    "comp": comp_cell.get_text(strip=True) if comp_cell else "",
                    "source_table": tid,
                    "pens_att": pkatt,
                    "pens_made": pk,
                }
            )
    return result


def crawl_careers() -> int:
    CAREER_DIR.mkdir(parents=True, exist_ok=True)
    shooter_names = load_shooter_names()
    try:
        player_map = build_player_url_map()
    except CloudflareBlocked:
        print("CLOUDFLARE BLOCK — Cookies neu holen.", file=sys.stderr)
        return 2
    print(f"Shooters to look up: {len(shooter_names)}")

    misses = []
    for i, name in enumerate(shooter_names, 1):
        url = player_map.get(name)
        if not url:
            misses.append(name)
            print(f"[{i}/{len(shooter_names)}] MISS name-lookup: {name}", flush=True)
            continue
        # File-safe id from URL
        player_id = url.split("/players/")[1].split("/")[0]
        out_file = CAREER_DIR / f"{player_id}.json"
        if out_file.exists():
            print(f"[{i}/{len(shooter_names)}] cached: {name}", flush=True)
            continue
        try:
            html = get(url)
        except CloudflareBlocked:
            print(
                f"\n[{i}/{len(shooter_names)}] CLOUDFLARE BLOCK — Cookies neu holen.",
                flush=True,
            )
            return 2
        seasons = parse_career_pkatt(html)
        data = {"player_name": name, "player_id": player_id, "url": url, "seasons": seasons}
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        total_pkatt = sum(s["pens_att"] for s in seasons)
        print(f"[{i}/{len(shooter_names)}] {name}: {len(seasons)} seasons, "
              f"total PKatt across FBref history = {total_pkatt}", flush=True)
        time.sleep(SLEEP_BETWEEN)

    if misses:
        print(f"\n{len(misses)} shooters not found in league mapping:")
        for m in misses:
            print(f"  - {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(crawl_careers())
