"""Lädt die FBref-Schedule-Seite einer Saison und speichert alle Spiele als JSON."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from fbref_client import get

SCHEDULE_URL = (
    "https://fbref.com/en/comps/9/2024-2025/schedule/"
    "2024-2025-Premier-League-Scores-and-Fixtures"
)
OUT_FILE = Path(__file__).parent / "data" / "raw" / "schedule.json"


def cell_text(row, stat: str) -> str:
    cell = row.find(attrs={"data-stat": stat})
    return cell.get_text(strip=True) if cell else ""


def cell_link(row, stat: str) -> str:
    cell = row.find(attrs={"data-stat": stat})
    if not cell:
        return ""
    a = cell.find("a")
    return a["href"] if a and a.has_attr("href") else ""


def parse_schedule(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id=lambda x: x and x.startswith("sched_"))
    if not table:
        raise RuntimeError("Keine Schedule-Tabelle gefunden")

    matches = []
    for row in table.find("tbody").find_all("tr"):
        if "spacer" in (row.get("class") or []):
            continue
        match_report = cell_link(row, "match_report")
        if not match_report:
            continue
        matches.append(
            {
                "gameweek": cell_text(row, "gameweek"),
                "date": cell_text(row, "date"),
                "time": cell_text(row, "start_time"),
                "home_team": cell_text(row, "home_team"),
                "away_team": cell_text(row, "away_team"),
                "score": cell_text(row, "score"),
                "venue": cell_text(row, "venue"),
                "attendance": cell_text(row, "attendance"),
                "match_report_url": "https://fbref.com" + match_report,
            }
        )
    return matches


def main() -> int:
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"Loading {SCHEDULE_URL}", file=sys.stderr)
    html = get(SCHEDULE_URL)
    matches = parse_schedule(html)
    OUT_FILE.write_text(json.dumps(matches, ensure_ascii=False, indent=2))
    print(f"Saved {len(matches)} matches to {OUT_FILE}")
    if matches:
        print("First match:", matches[0])
        print("Last match:", matches[-1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
