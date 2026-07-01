# penalty-scraper

Automatischer Elfmeter-Datensatz für Jakob Schneiders Bachelorarbeit
*Der Einfluss situativer Druckfaktoren auf Elfmeterschüsse im Profifußball*
(Prof. Bühren, RUB, Fakultät für Sportwissenschaft, 2026).

Aktuell abgedeckt: Premier League 2024/25 (83 Elfmeter). Die Pipeline lässt
sich per URL-Wechsel auf jede andere Liga+Saison auf FBref ausdehnen.

## Web-Demo

Streamlit-App zeigt Datensatz, interaktive Charts, SPSS-Export und einen
Live-Scrape-Modus.

```
.venv/bin/streamlit run app.py
```

## Datensatz-Pipeline (CLI)

```
.venv/bin/python scrape_schedule.py     # 1 Fetch, alle 380 Spiele der Saison
.venv/bin/python crawl_season.py        # ~25 Min, ein Match-Report pro Spiel
.venv/bin/python scrape_careers.py      # ~3 Min, Karriere-Statistik pro Schütze
.venv/bin/python scrape_match_logs.py   # ~3 Min, Match-Logs für zeitgenaue Karriere-Elfmeter
.venv/bin/python build_dataset.py       # Klartext-CSV
.venv/bin/python build_spss_export.py   # Excel mit SPSS-Codierung
```

Ergebnisse landen in `data/processed/`.

## Setup

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Cookies

FBref ist hinter Cloudflare. `cookies.json` (gitignored) enthält die aus
Chrome kopierten Session-Cookies. Bei Cloudflare-Block: Chrome öffnen,
DevTools → Network → Reload → erste Zeile → Copy as cURL, hier reinpasten
(die Streamlit-App macht das interaktiv im Live-Scrape-Tab).

## Datensatz-Variablen

Alle 11 Variablen aus Jakobs Methodik-Sektion:

| Spalte | Bedeutung |
|---|---|
| match_date | Datum |
| gameweek | Spieltag |
| league | Liga |
| home_team / away_team | Beteiligte Teams |
| shooter_team / opponent_team | Sicht des Schützen |
| home_away | Heim / Auswärts |
| shooter_name | Spielername |
| minute | Spielminute |
| score_for_before / score_against_before | Spielstand vor Elfmeter |
| score_state | Rückstand / Unentschieden / Führung |
| penalty_outcome | Tor / kein Tor |
| penalty_type | Im Spiel / Elfmeterschießen |
| must_score | Must-Score-Situation |
| league_position_before | Tabellenplatz vor dem Spieltag |
| prev_penalties_season | Bisherige Elfmeter des Schützen in dieser Saison |
| prev_penalties_career | Karriere-Elfmeter bis vor diesem Elfmeter (all comps in aktueller Saison über Match-Logs zeitgenau, Liga-only für Vorsaisons) |
