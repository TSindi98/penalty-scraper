"""Parst einen einzelnen Match Report von FBref und extrahiert alle Tor-Events
(inkl. Penalties). Speichert pro Spiel eine JSON-Datei.

Event-Struktur in der Match Summary:
  <div class="event" id="a">  ← Heim
    <div>
      <a href="/en/players/.../Mohamed-Salah">Mohamed Salah</a> (P) · 29'
      <div class="event_icon penalty_goal"></div>
    </div>
    ...
  </div>
  <div class="event" id="b">  ← Auswärts
    ...
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from fbref_client import get

DATA_DIR = Path(__file__).parent / "data" / "raw" / "matches"
MINUTE_RE = re.compile(r"(\d+)(?:\+(\d+))?")

# Goal-relevante Event-Klassen (Spielstand-Änderungen)
GOAL_CLASSES = {"goal", "penalty_goal", "own_goal"}
PENALTY_CLASSES = {"penalty_goal", "penalty_missed"}


def parse_minute(text: str) -> int | None:
    """'29' -> 29, '90+3' -> 93, '45+2' -> 47."""
    m = MINUTE_RE.search(text)
    if not m:
        return None
    base = int(m.group(1))
    stoppage = int(m.group(2)) if m.group(2) else 0
    return base + stoppage


def extract_match_id(url: str) -> str:
    # https://fbref.com/en/matches/99b4737c/Liverpool-Chelsea-...
    return url.split("/matches/")[1].split("/")[0]


def parse_scorebox(soup: BeautifulSoup) -> dict:
    scorebox = soup.find("div", class_="scorebox")
    teams = scorebox.find_all("div", recursive=False)
    # Erste zwei direkten div-Kinder sind Heim/Auswärts mit Team-Name + Score
    home_name = teams[0].find("a").get_text(strip=True)
    away_name = teams[1].find("a").get_text(strip=True)
    home_score = teams[0].find("div", class_="score").get_text(strip=True)
    away_score = teams[1].find("div", class_="score").get_text(strip=True)
    # Datum aus scorebox_meta
    meta = soup.find("div", class_="scorebox_meta")
    meta_text = meta.get_text(" ", strip=True) if meta else ""
    return {
        "home_team": home_name,
        "away_team": away_name,
        "home_score": int(home_score),
        "away_score": int(away_score),
        "meta_text": meta_text,
    }


def parse_events(soup: BeautifulSoup) -> list[dict]:
    events: list[dict] = []
    for side, div_id in [("home", "a"), ("away", "b")]:
        container = soup.find("div", class_="event", id=div_id)
        if not container:
            continue
        for ev_div in container.find_all("div", recursive=False):
            icon = ev_div.find("div", class_="event_icon")
            if not icon:
                continue
            icon_classes = [c for c in icon.get("class", []) if c != "event_icon"]
            event_type = icon_classes[0] if icon_classes else "unknown"
            # Spielername aus dem ersten <a>
            player_link = ev_div.find("a")
            player_name = player_link.get_text(strip=True) if player_link else ""
            # Minute aus dem Text
            text = ev_div.get_text(" ", strip=True)
            minute = parse_minute(text)
            # Penalty-Marker
            is_penalty_marker = "(P)" in text
            events.append(
                {
                    "side": side,
                    "event_type": event_type,
                    "player": player_name,
                    "minute": minute,
                    "is_penalty": event_type in PENALTY_CLASSES or is_penalty_marker,
                    "raw_text": text,
                }
            )
    return events


def parse_player_pk_stats(soup: BeautifulSoup) -> list[dict]:
    """Aus den Player-Stats-Tabellen: pens_made und pens_att pro Spieler pro Team.

    Wird gebraucht, um verschossene Elfmeter zu erkennen (pens_att > pens_made).
    """
    result: list[dict] = []
    for table in soup.find_all("table", id=lambda x: x and x.startswith("stats_") and x.endswith("_summary")):
        # Team-ID steht in der ID: stats_<TEAM_ID>_summary
        team_id = table.get("id").replace("stats_", "").replace("_summary", "")
        # Team-Name aus dem Caption oder Header
        caption = table.find("caption")
        team_name = caption.get_text(strip=True).replace(" Player Stats Table", "") if caption else team_id
        tbody = table.find("tbody")
        if not tbody:
            continue
        for row in tbody.find_all("tr"):
            player_cell = row.find(attrs={"data-stat": "player"})
            pk_cell = row.find(attrs={"data-stat": "pens_made"})
            pkatt_cell = row.find(attrs={"data-stat": "pens_att"})
            if not (player_cell and pk_cell and pkatt_cell):
                continue
            pk = int(pk_cell.get_text(strip=True) or 0)
            pkatt = int(pkatt_cell.get_text(strip=True) or 0)
            if pkatt == 0:
                continue
            result.append(
                {
                    "team_id": team_id,
                    "team_name": team_name,
                    "player": player_cell.get_text(strip=True),
                    "pens_made": pk,
                    "pens_att": pkatt,
                }
            )
    return result


def parse_match(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    scorebox = parse_scorebox(soup)
    events = parse_events(soup)
    player_pk_stats = parse_player_pk_stats(soup)
    return {
        "scorebox": scorebox,
        "events": events,
        "player_pk_stats": player_pk_stats,
    }


def main(url: str) -> int:
    match_id = extract_match_id(url)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_file = DATA_DIR / f"{match_id}.json"

    if out_file.exists():
        print(f"Cached: {out_file}")
        data = json.loads(out_file.read_text())
    else:
        print(f"Fetching {url}", file=sys.stderr)
        html = get(url)
        data = parse_match(html)
        data["match_id"] = match_id
        data["url"] = url
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"Saved {out_file}")

    print(f"\n{data['scorebox']['home_team']} {data['scorebox']['home_score']} - "
          f"{data['scorebox']['away_score']} {data['scorebox']['away_team']}")
    print(f"Total events: {len(data['events'])}")
    penalties = [e for e in data["events"] if e["is_penalty"]]
    print(f"Penalties: {len(penalties)}")
    for p in penalties:
        print(f"  {p['minute']}' {p['side']:5} {p['event_type']:18} {p['player']}")
    return 0


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://fbref.com/en/matches/99b4737c/"
        "Liverpool-Chelsea-October-20-2024-Premier-League"
    )
    sys.exit(main(url))
