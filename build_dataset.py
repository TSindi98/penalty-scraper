"""Baut aus allen gecrawlten Match-JSONs das finale Elfmeter-Dataset (CSV).

Enthält für jeden Elfmeter alle Variablen aus Jakobs Antragsmethodik:
1  penalty_outcome     Tor / kein Tor
2  penalty_type        Im Spiel / Elfmeterschießen  (Konstant "Im Spiel" für PL Liga)
3  home_away           Heim / Auswärts
4  minute              Spielminute
5  score_state         Rückstand / Unentschieden / Führung (aus Sicht Schütze)
6  must_score          Must-Score im Elfmeterschießen (Konstant 0 für PL Liga)
7  league              Konstant "Premier League"
8  league_position     Tabellenplatz Schützen-Team vor dem Spieltag
9  prev_penalties      Bisherige Elfmeter dieses Spielers in dieser Saison
10 match_date          Datum
11 shooter_name        Spielername
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data" / "raw" / "matches"
CAREER_DIR = Path(__file__).parent / "data" / "raw" / "careers"
MATCH_LOG_DIR = Path(__file__).parent / "data" / "raw" / "match_logs_2024_25"
PLAYER_MAP_FILE = Path(__file__).parent / "data" / "raw" / "player_url_map.json"
SCHEDULE_FILE = Path(__file__).parent / "data" / "raw" / "schedule.json"
OUT_FILE = Path(__file__).parent / "data" / "processed" / "penalties_pl_2024_25.csv"

LEAGUE_NAME = "Premier League"
CURRENT_SEASON_START_YEAR = 2024  # PL 24/25 → alles < 2024 gilt als "vorherige Karriere"


def load_all_matches() -> list[dict]:
    matches = []
    for p in sorted(DATA_DIR.glob("*.json")):
        matches.append(json.loads(p.read_text()))
    return matches


def load_careers() -> dict[str, dict]:
    """Lädt Career-JSONs, Rückgabe: shooter_name → career-dict mit 'seasons'."""
    careers: dict[str, dict] = {}
    if not CAREER_DIR.exists():
        return careers
    for p in sorted(CAREER_DIR.glob("*.json")):
        data = json.loads(p.read_text())
        careers[data["player_name"]] = data
    return careers


def load_match_logs() -> dict[str, list[dict]]:
    """Lädt Match-Logs für Saison 2024/25 pro Spieler.
    Rückgabe: shooter_name → Liste der Elfmeter-Matches [{date, comp, pens_att, ...}]."""
    logs: dict[str, list[dict]] = {}
    if not MATCH_LOG_DIR.exists():
        return logs
    for p in sorted(MATCH_LOG_DIR.glob("*.json")):
        data = json.loads(p.read_text())
        logs[data["player_name"]] = data.get("matches_with_pens", [])
    return logs


def season_start_year(season_str: str) -> int | None:
    """'2023-2024' → 2023, '2019-20' → 2019, '2024' → 2024."""
    m = re.match(r"^(\d{4})", season_str)
    return int(m.group(1)) if m else None


def base_career_pkatt(career: dict, current_season_start_year: int) -> int:
    """Summe PKatt aus allen Saisons *vor* der aktuellen Saison."""
    if not career:
        return 0
    total = 0
    for s in career.get("seasons", []):
        y = season_start_year(s.get("season", ""))
        if y is not None and y < current_season_start_year:
            total += s.get("pens_att", 0)
    return total


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def score_before_penalty(events: list[dict], penalty_event: dict) -> tuple[int, int]:
    """Home/Away Score direkt vor diesem Elfmeter.

    Zählt alle Tor-Events (goal, penalty_goal, own_goal), die vor dem
    Elfmeter stattfanden. Own-goal zählt für die andere Seite.
    """
    home, away = 0, 0
    for e in events:
        if e is penalty_event:
            continue
        # Nur Events vor dem Elfmeter berücksichtigen (chronologisch)
        if e["minute"] is None or penalty_event["minute"] is None:
            continue
        if e["minute"] > penalty_event["minute"]:
            continue
        # Gleiche Minute: konservativ vor dem Elfmeter angerechnet
        # (FBref listet Events innerhalb Minute in chronologischer Reihenfolge,
        # unsere parse_events geht id="a" dann id="b" durch — bei gleicher
        # Minute kann Reihenfolge unsicher sein; für Sonderfälle: skip wenn same object)

        et = e["event_type"]
        if et == "goal" or et == "penalty_goal":
            if e["side"] == "home":
                home += 1
            else:
                away += 1
        elif et == "own_goal":
            # Own goal des home-Spielers zählt für away und umgekehrt
            if e["side"] == "home":
                away += 1
            else:
                home += 1
    return home, away


def compute_standings_before(
    target_date: date, matches: list[dict]
) -> dict[str, dict]:
    """Berechnet Standings anhand aller Match-JSONs mit Datum < target_date.

    Nutzt die vollständigen scorebox-Teamnamen (matchen mit shooter_team).
    """
    stats: dict[str, dict] = defaultdict(
        lambda: {"points": 0, "gf": 0, "ga": 0, "gd": 0, "played": 0}
    )
    for m in matches:
        meta = m.get("schedule_meta") or {}
        date_str = meta.get("date")
        if not date_str:
            continue
        if parse_date(date_str) >= target_date:
            continue
        sb = m["scorebox"]
        h, a = sb["home_team"], sb["away_team"]
        hs, as_ = sb["home_score"], sb["away_score"]
        stats[h]["gf"] += hs
        stats[h]["ga"] += as_
        stats[h]["played"] += 1
        stats[a]["gf"] += as_
        stats[a]["ga"] += hs
        stats[a]["played"] += 1
        if hs > as_:
            stats[h]["points"] += 3
        elif hs < as_:
            stats[a]["points"] += 3
        else:
            stats[h]["points"] += 1
            stats[a]["points"] += 1

    for team in stats:
        stats[team]["gd"] = stats[team]["gf"] - stats[team]["ga"]

    sorted_teams = sorted(
        stats.items(),
        key=lambda kv: (-kv[1]["points"], -kv[1]["gd"], -kv[1]["gf"]),
    )
    for pos, (team, data) in enumerate(sorted_teams, 1):
        data["position"] = pos
    return dict(stats)


def collect_penalties(matches: list[dict]) -> list[dict]:
    """Extrahiert alle Elfmeter aus allen Matches mit vollem Kontext.

    Verwandelte Elfmeter kommen aus dem Match-Summary-Block (mit Minute).
    Verschossene Elfmeter werden aus der Player-Stats-Tabelle abgeleitet
    (pens_att > pens_made), wo die Minute nicht verfügbar ist.
    """
    penalties = []
    for match in matches:
        meta = match.get("schedule_meta") or {}
        scorebox = match["scorebox"]
        # Verwandelte Elfmeter (aus Match Summary)
        made_by_player: dict[str, int] = defaultdict(int)
        for event in match["events"]:
            if not event.get("is_penalty"):
                continue
            made_by_player[event["player"]] += 1
            home_before, away_before = score_before_penalty(match["events"], event)
            shooter_team = scorebox["home_team"] if event["side"] == "home" else scorebox["away_team"]
            opponent_team = scorebox["away_team"] if event["side"] == "home" else scorebox["home_team"]
            score_for = home_before if event["side"] == "home" else away_before
            score_against = away_before if event["side"] == "home" else home_before
            diff = score_for - score_against
            score_state = "Rückstand" if diff < 0 else ("Unentschieden" if diff == 0 else "Führung")
            penalties.append(
                {
                    "match_id": match["match_id"],
                    "match_date": meta.get("date") or "",
                    "gameweek": meta.get("gameweek") or "",
                    "league": LEAGUE_NAME,
                    "home_team": scorebox["home_team"],
                    "away_team": scorebox["away_team"],
                    "shooter_team": shooter_team,
                    "opponent_team": opponent_team,
                    "home_away": "Heim" if event["side"] == "home" else "Auswärts",
                    "shooter_name": event["player"],
                    "minute": event["minute"],
                    "score_for_before": score_for,
                    "score_against_before": score_against,
                    "score_state": score_state,
                    "penalty_outcome": "Tor",
                    "penalty_type": "Im Spiel",
                    "must_score": 0,
                }
            )
        # Verschossene Elfmeter (aus Player-Stats-Tabelle)
        # Nur Home und Away können wir zuordnen — Team-Name aus Player-Stats vs. Scorebox
        for pk_stat in match.get("player_pk_stats", []):
            missed = pk_stat["pens_att"] - pk_stat["pens_made"]
            already_counted = made_by_player.get(pk_stat["player"], 0)
            missed_extra = pk_stat["pens_att"] - already_counted - missed
            # Anzahl "missed" laut Stats = pens_att - pens_made
            # Wir wollen (pens_att - already_counted_as_made_in_events) Zeilen für diesen Spieler
            # davon (pens_att - pens_made) sind verschossen
            # Sanity: already_counted sollte == pens_made sein
            for _ in range(missed):
                is_home = pk_stat["team_name"] == scorebox["home_team"]
                shooter_team = scorebox["home_team"] if is_home else scorebox["away_team"]
                opponent_team = scorebox["away_team"] if is_home else scorebox["home_team"]
                penalties.append(
                    {
                        "match_id": match["match_id"],
                        "match_date": meta.get("date") or "",
                        "gameweek": meta.get("gameweek") or "",
                        "league": LEAGUE_NAME,
                        "home_team": scorebox["home_team"],
                        "away_team": scorebox["away_team"],
                        "shooter_team": shooter_team,
                        "opponent_team": opponent_team,
                        "home_away": "Heim" if is_home else "Auswärts",
                        "shooter_name": pk_stat["player"],
                        "minute": "",
                        "score_for_before": "",
                        "score_against_before": "",
                        "score_state": "",  # ohne Minute nicht rekonstruierbar
                        "penalty_outcome": "kein Tor",
                        "penalty_type": "Im Spiel",
                        "must_score": 0,
                    }
                )
    return penalties


def enrich_with_derived(
    penalties: list[dict],
    matches: list[dict],
    careers: dict[str, dict],
    match_logs: dict[str, list[dict]],
) -> None:
    """Fügt Tabellenplatz vor Spieltag und vorherige Elfmeter (Saison + Karriere) hinzu.

    prev_penalties_career nutzt:
    (a) Career-Historie (Standard Stats): PKatt aus allen Saisons *vor* 2024/25.
    (b) Match-Logs der Saison 2024/25: alle Wettbewerbs-Elfmeter bis vor dem
        aktuellen Datum. Damit sind auch CL / Pokal / Nationalmannschaft in
        derselben Saison exakt zeitlich verortet — kein Data-Leakage.
    """
    penalties.sort(
        key=lambda p: (
            p["match_date"],
            p["minute"] if isinstance(p["minute"], int) else 0,
        )
    )

    standings_cache: dict[str, dict[str, dict]] = {}
    for p in penalties:
        d = p["match_date"]
        if d not in standings_cache:
            standings_cache[d] = compute_standings_before(parse_date(d), matches)
        team_stats = standings_cache[d].get(p["shooter_team"], {})
        p["league_position_before"] = team_stats.get("position", "")

    # Base-Career pro Schütze aus Standard-Stats (alle Saisons vor 24/25, alle Comps)
    career_base: dict[str, int] = {}
    has_career_data: dict[str, bool] = {}
    for p in penalties:
        name = p["shooter_name"]
        if name not in career_base:
            career_base[name] = base_career_pkatt(
                careers.get(name, {}), CURRENT_SEASON_START_YEAR
            )
            has_career_data[name] = name in careers

    # Chronologisches Zählen für Saison-Elfmeter (nur PL — kommt aus unserem Datensatz)
    prev_season: dict[str, int] = defaultdict(int)

    # Match-Log-basierte Zählung aller Saison-Elfmeter aller Wettbewerbe bis Datum
    def pens_all_comps_before(name: str, target_date: str) -> int:
        return sum(
            m["pens_att"]
            for m in match_logs.get(name, [])
            if m["date"] and m["date"] < target_date
        )

    for p in penalties:
        name = p["shooter_name"]
        p["prev_penalties_season"] = prev_season[name]
        if has_career_data.get(name):
            base = career_base[name]
            in_season_all_comps = pens_all_comps_before(name, p["match_date"])
            p["prev_penalties_career"] = base + in_season_all_comps
        else:
            p["prev_penalties_career"] = ""  # keine Karriere-Daten verfügbar
        prev_season[name] += 1


COLUMNS = [
    "match_date",
    "gameweek",
    "league",
    "home_team",
    "away_team",
    "shooter_team",
    "opponent_team",
    "home_away",
    "shooter_name",
    "minute",
    "score_for_before",
    "score_against_before",
    "score_state",
    "penalty_outcome",
    "penalty_type",
    "must_score",
    "league_position_before",
    "prev_penalties_season",
    "prev_penalties_career",
    "match_id",
]


def main() -> int:
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    matches = load_all_matches()
    print(f"Loaded {len(matches)} matches")
    careers = load_careers()
    print(f"Loaded {len(careers)} career profiles")
    match_logs = load_match_logs()
    print(f"Loaded {len(match_logs)} player match-logs (season 24/25)")
    penalties = collect_penalties(matches)
    print(f"Found {len(penalties)} penalties")
    enrich_with_derived(penalties, matches, careers, match_logs)

    with OUT_FILE.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(penalties)
    print(f"Wrote {OUT_FILE}")

    # Sanity summary
    tor = sum(1 for p in penalties if p["penalty_outcome"] == "Tor")
    print(f"Tor: {tor}, kein Tor: {len(penalties) - tor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
