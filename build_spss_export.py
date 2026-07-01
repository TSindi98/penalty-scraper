"""Baut aus dem finalen CSV eine SPSS-kompatible Excel-Datei mit numerischer Codierung.

Zwei Sheets:
- "Daten"      — jede Zeile ein Elfmeter, alle Kategorien als Zahlen
- "Codebuch"   — Legende: welcher numerische Wert bedeutet was
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

CSV_PATH = Path(__file__).parent / "data" / "processed" / "penalties_pl_2024_25.csv"
XLSX_PATH = Path(__file__).parent / "data" / "processed" / "penalties_pl_2024_25_spss.xlsx"

# Kodierungs-Tabellen (in SPSS üblich)
OUTCOME_MAP = {"Tor": 1, "kein Tor": 0}
HOME_AWAY_MAP = {"Heim": 1, "Auswärts": 0}
SCORE_STATE_MAP = {"Rückstand": -1, "Unentschieden": 0, "Führung": 1}
PENALTY_TYPE_MAP = {"Im Spiel": 0, "Elfmeterschießen": 1}
LEAGUE_MAP = {"Premier League": 1, "Bundesliga": 2, "LaLiga": 3, "Champions League": 4}


def encode(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["match_date"] = df["match_date"]
    out["gameweek"] = pd.to_numeric(df["gameweek"], errors="coerce")
    out["league"] = df["league"].map(LEAGUE_MAP)
    out["home_team"] = df["home_team"]
    out["away_team"] = df["away_team"]
    out["shooter_team"] = df["shooter_team"]
    out["opponent_team"] = df["opponent_team"]
    out["shooter_name"] = df["shooter_name"]
    out["home_away"] = df["home_away"].map(HOME_AWAY_MAP)
    out["minute"] = pd.to_numeric(df["minute"], errors="coerce")
    out["score_for_before"] = pd.to_numeric(df["score_for_before"], errors="coerce")
    out["score_against_before"] = pd.to_numeric(df["score_against_before"], errors="coerce")
    out["score_state"] = df["score_state"].map(SCORE_STATE_MAP)
    out["penalty_outcome"] = df["penalty_outcome"].map(OUTCOME_MAP)
    out["penalty_type"] = df["penalty_type"].map(PENALTY_TYPE_MAP)
    out["must_score"] = pd.to_numeric(df["must_score"], errors="coerce")
    out["league_position_before"] = pd.to_numeric(df["league_position_before"], errors="coerce")
    out["prev_penalties_season"] = pd.to_numeric(df["prev_penalties_season"], errors="coerce")
    out["prev_penalties_career"] = pd.to_numeric(df["prev_penalties_career"], errors="coerce")
    out["match_id"] = df["match_id"]
    return out


def codebook() -> pd.DataFrame:
    rows = []
    rows.append(("penalty_outcome", "Erfolg des Elfmeters", "1 = Tor · 0 = kein Tor"))
    rows.append(("home_away", "Heim- oder Auswärtsspiel", "1 = Heim · 0 = Auswärts"))
    rows.append(("score_state",
                 "Spielstand vor Elfmeter (Sicht Schützen-Team)",
                 "-1 = Rückstand · 0 = Unentschieden · 1 = Führung · leer = unbekannt (verschossener Elfmeter, Minute fehlt)"))
    rows.append(("penalty_type", "Art des Elfmeters", "0 = Im Spiel · 1 = Elfmeterschießen"))
    rows.append(("must_score",
                 "Must-Score-Situation (nur Elfmeterschießen)",
                 "0 = nein · 1 = ja"))
    rows.append(("league", "Liga",
                 "1 = Premier League · 2 = Bundesliga · 3 = LaLiga · 4 = Champions League"))
    rows.append(("minute", "Spielminute (regulär inkl. Nachspielzeit als 90+X → X drauf gerechnet)", "Integer, leer bei verschossenen Elfmetern ohne Minutenangabe"))
    rows.append(("score_for_before", "Tore Schützen-Team vor Elfmeter", "Integer"))
    rows.append(("score_against_before", "Tore Gegner vor Elfmeter", "Integer"))
    rows.append(("league_position_before",
                 "Tabellenplatz Schützen-Team vor dem Spieltag",
                 "1–20, leer für Spieltag 1"))
    rows.append(("prev_penalties_season",
                 "Bisherige Elfmeter des Schützen in dieser Saison (nur Liga)",
                 "Integer, 0 wenn erster"))
    rows.append(("prev_penalties_career",
                 "Bisherige Elfmeter des Schützen bis vor diesem Elfmeter",
                 "Integer. Karriere-Basis vor 2024/25 aus FBref Standard-Stats (Liga), "
                 "in 2024/25 alle Wettbewerbe aus Match-Logs zeitgenau. "
                 "Leer wenn Karriere-Daten fehlen."))
    rows.append(("gameweek", "Spieltag", "1–38"))
    rows.append(("match_date", "Datum des Spiels", "YYYY-MM-DD"))
    rows.append(("shooter_name", "Name des Schützen", "Text"))
    rows.append(("shooter_team", "Team des Schützen", "Text"))
    rows.append(("opponent_team", "Team des Gegners", "Text"))
    rows.append(("home_team", "Heimteam des Spiels", "Text"))
    rows.append(("away_team", "Auswärtsteam des Spiels", "Text"))
    rows.append(("match_id", "FBref-Match-ID", "Text (Referenz)"))
    return pd.DataFrame(rows, columns=["Variable", "Bedeutung", "Codierung"])


def main() -> None:
    df = pd.read_csv(CSV_PATH)
    encoded = encode(df)
    code = codebook()
    with pd.ExcelWriter(XLSX_PATH, engine="openpyxl") as writer:
        encoded.to_excel(writer, sheet_name="Daten", index=False)
        code.to_excel(writer, sheet_name="Codebuch", index=False)
        # Spaltenbreite anpassen
        for sheet_name, frame in [("Daten", encoded), ("Codebuch", code)]:
            ws = writer.sheets[sheet_name]
            for i, col in enumerate(frame.columns, 1):
                width = min(max(len(str(col)), int(frame[col].astype(str).str.len().max() or 0)) + 2, 60)
                ws.column_dimensions[chr(64 + i) if i <= 26 else "A" + chr(64 + i - 26)].width = width
    print(f"Wrote {XLSX_PATH}")


if __name__ == "__main__":
    main()
