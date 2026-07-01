"""Für jeden Elfmeter-Schützen: FBref Player-Match-Logs für Saison 2024/25.

Jede Zeile ein Spiel mit Datum + Comp + pens_att + pens_made. Damit lässt sich
für jeden PL-Elfmeter exakt bestimmen, wie viele Elfmeter der Spieler bis vor
diesem Datum in ALLEN Wettbewerben (Liga, CL, EL, Pokal, Nationalmannschaft)
geschossen hatte.

URL-Muster: /en/players/<id>/matchlogs/2024-2025/summary/<Name>-Match-Logs
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup, Comment

from fbref_client import get, CloudflareBlocked

CAREER_DIR = Path(__file__).parent / "data" / "raw" / "careers"
MATCH_LOG_DIR = Path(__file__).parent / "data" / "raw" / "match_logs_2024_25"
SEASON = "2024-2025"
SLEEP_BETWEEN = 4.0


def match_logs_url(player_id: str, player_name_slug: str) -> str:
    return (
        f"https://fbref.com/en/players/{player_id}/matchlogs/{SEASON}/summary/"
        f"{player_name_slug}-Match-Logs"
    )


def parse_match_logs(html: str) -> list[dict]:
    """Aus der Player-Match-Logs-Tabelle: Datum, Comp, PKatt, PK pro Match."""
    soup = BeautifulSoup(html, "lxml")

    def find_matchlogs_table(node):
        for t in node.find_all("table"):
            tid = t.get("id") or ""
            if "matchlogs" in tid.lower() or tid.startswith("matchlogs_"):
                return t
        return None

    table = find_matchlogs_table(soup)
    if not table:
        for c in soup.find_all(string=lambda x: isinstance(x, Comment)):
            if "matchlogs" in str(c).lower():
                inner = BeautifulSoup(str(c), "lxml")
                table = find_matchlogs_table(inner)
                if table:
                    break

    if not table:
        return []

    result = []
    tbody = table.find("tbody")
    if not tbody:
        return []
    for row in tbody.find_all("tr"):
        if "thead" in (row.get("class") or []):
            continue
        date_cell = row.find(attrs={"data-stat": "date"})
        comp_cell = row.find(attrs={"data-stat": "comp"})
        pkatt_cell = row.find(attrs={"data-stat": "pens_att"})
        pk_cell = row.find(attrs={"data-stat": "pens_made"})
        opp_cell = row.find(attrs={"data-stat": "opponent"})
        venue_cell = row.find(attrs={"data-stat": "venue"})
        if not date_cell:
            continue
        d = date_cell.get_text(strip=True)
        if not d:
            continue
        try:
            pkatt = int((pkatt_cell.get_text(strip=True) if pkatt_cell else "") or 0)
            pk = int((pk_cell.get_text(strip=True) if pk_cell else "") or 0)
        except ValueError:
            continue
        result.append(
            {
                "date": d,
                "comp": comp_cell.get_text(strip=True) if comp_cell else "",
                "opponent": opp_cell.get_text(strip=True) if opp_cell else "",
                "venue": venue_cell.get_text(strip=True) if venue_cell else "",
                "pens_att": pkatt,
                "pens_made": pk,
            }
        )
    return result


def main() -> int:
    MATCH_LOG_DIR.mkdir(parents=True, exist_ok=True)
    career_files = sorted(CAREER_DIR.glob("*.json"))
    print(f"Career profiles to fetch match logs for: {len(career_files)}")

    for i, cf in enumerate(career_files, 1):
        career = json.loads(cf.read_text())
        player_id = career["player_id"]
        name_slug = career["url"].split("/")[-1]
        out_file = MATCH_LOG_DIR / f"{player_id}.json"
        if out_file.exists():
            print(f"[{i}/{len(career_files)}] cached: {career['player_name']}", flush=True)
            continue
        url = match_logs_url(player_id, name_slug)
        try:
            html = get(url)
        except CloudflareBlocked:
            print(f"\n[{i}/{len(career_files)}] CLOUDFLARE BLOCK — Cookies neu holen.", flush=True)
            return 2
        logs = parse_match_logs(html)
        pk_matches = [m for m in logs if m["pens_att"] > 0]
        data = {
            "player_name": career["player_name"],
            "player_id": player_id,
            "season": SEASON,
            "url": url,
            "matches_with_pens": pk_matches,
            "total_matches_logged": len(logs),
        }
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        total_pk_att = sum(m["pens_att"] for m in pk_matches)
        print(
            f"[{i}/{len(career_files)}] {career['player_name']:22} "
            f"logs={len(logs)} pk_matches={len(pk_matches)} total_pkatt_season={total_pk_att}",
            flush=True,
        )
        time.sleep(SLEEP_BETWEEN)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
