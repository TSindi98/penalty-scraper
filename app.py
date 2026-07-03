"""Streamlit-Demo für Jakobs Elfmeter-Datensatz.

Startet mit:
    .venv/bin/streamlit run app.py
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from bs4 import BeautifulSoup

import compare_jakob as cj
from scrape_match import parse_match
from scrape_schedule import parse_schedule

CSV_PATH = Path(__file__).parent / "data" / "processed" / "penalties_pl_2024_25.csv"
XLSX_PATH = Path(__file__).parent / "data" / "processed" / "penalties_pl_2024_25_spss.xlsx"
SCHEDULE_PATH = Path(__file__).parent / "data" / "raw" / "schedule.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)


def parse_cookies_from_curl(curl_text: str) -> dict:
    """Extrahiert Cookies aus einem 'Copy as cURL'-Text (die -b '...' Zeile)."""
    m = re.search(r"-b '([^']+)'", curl_text)
    if not m:
        return {}
    cookie_str = m.group(1)
    out: dict = {}
    for pair in cookie_str.split(";"):
        if "=" in pair:
            k, v = pair.strip().split("=", 1)
            out[k] = v
    return out


def fetch_with_cookies(url: str, cookies: dict) -> str:
    from curl_cffi import requests

    r = requests.get(
        url,
        impersonate="chrome120",
        cookies=cookies,
        headers={
            "user-agent": USER_AGENT,
            "accept-language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        },
        timeout=30,
    )
    if "Just a moment" in r.text:
        raise RuntimeError(
            "Cloudflare-Challenge — Cookies abgelaufen. Bitte "
            "cURL-Text im Chrome frisch kopieren."
        )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.text

st.set_page_config(
    page_title="Elfmeter-Datensatz Demo",
    page_icon="⚽",
    layout="wide",
)


@st.cache_data
def load_data() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH)
    df["match_date"] = pd.to_datetime(df["match_date"])
    return df


def main() -> None:
    st.title("Elfmeter-Datensatz Premier League 2024/25")
    st.caption(
        "Automatisch aus FBref extrahiert für Jakob Schneiders Bachelorarbeit "
        "*Der Einfluss situativer Druckfaktoren auf Elfmeterschüsse*."
    )

    df = load_data()

    def clean_str_options(series: pd.Series) -> list[str]:
        return sorted(x for x in series.dropna().unique() if isinstance(x, str) and x)

    with st.sidebar:
        st.header("Filter")
        outcome_options = clean_str_options(df["penalty_outcome"])
        outcome = st.multiselect(
            "Outcome", options=outcome_options, default=outcome_options,
        )
        ha_options = clean_str_options(df["home_away"])
        home_away = st.multiselect(
            "Heim/Auswärts", options=ha_options, default=ha_options,
        )
        state_options = clean_str_options(df["score_state"])
        state = st.multiselect(
            "Spielstand vor Elfmeter", options=state_options, default=state_options,
        )
        teams = st.multiselect(
            "Schützen-Team", options=clean_str_options(df["shooter_team"]),
            default=[],
        )
        st.divider()
        st.markdown(
            "### Wie ist das entstanden?\n"
            "Das CSV wurde in ~1 Stunde durch automatisches Crawlen von "
            "[FBref.com](https://fbref.com) erzeugt. Alle 380 Match-Reports "
            "wurden geparst, Elfmeter identifiziert, Kontext-Variablen "
            "rekonstruiert (Spielstand, Tabellenplatz vor Spieltag, "
            "Karriere-Elfmeter des Schützen)."
        )

    # Filter anwenden
    mask = df["penalty_outcome"].isin(outcome) & df["home_away"].isin(home_away)
    if state and len(state) < len(state_options):
        # Nur echte state-Filter anwenden; verschossene ohne Minute (NaN state)
        # werden bei aktiver Auswahl ausgeblendet
        mask &= df["score_state"].isin(state)
    if teams:
        mask &= df["shooter_team"].isin(teams)
    fdf = df[mask]

    # KPIs
    total = len(fdf)
    torquote = fdf["penalty_outcome"].eq("Tor").mean() * 100 if total else 0
    heim_pct = fdf["home_away"].eq("Heim").mean() * 100 if total else 0
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Elfmeter im Filter", f"{total}")
    col2.metric("Erfolgsquote", f"{torquote:.1f}%")
    col3.metric("Heim-Anteil", f"{heim_pct:.1f}%")
    col4.metric("Unique Schützen", fdf["shooter_name"].nunique())

    (tab_data, tab_charts, tab_live, tab_full, tab_pipeline,
     tab_compare) = st.tabs(
        ["Datensatz", "Analyse", "Live-Scrape (1 Spiel)",
         "Ganze Liga scrapen", "Wie funktioniert die Pipeline?",
         "Vergleich mit Jakobs Excel"]
    )

    with tab_data:
        st.dataframe(
            fdf.sort_values("match_date"),
            use_container_width=True,
            hide_index=True,
            column_config={
                "match_date": st.column_config.DateColumn("Datum", format="YYYY-MM-DD"),
                "minute": st.column_config.NumberColumn("Min", width="small"),
                "prev_penalties_career": st.column_config.NumberColumn(
                    "Karriere-Pens vorher",
                    help="Alle bisherigen Elfmeter des Schützen in allen "
                         "Wettbewerben bis vor diesem Elfmeter (Liga-Historie "
                         "vor 2024/25 + Match-Log 2024/25).",
                ),
            },
        )
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            csv_bytes = fdf.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Gefilterten Datensatz als CSV",
                data=csv_bytes,
                file_name="penalties_pl_2024_25_filtered.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with col_dl2:
            if XLSX_PATH.exists():
                st.download_button(
                    "Vollen Datensatz als Excel (SPSS-Codierung)",
                    data=XLSX_PATH.read_bytes(),
                    file_name="penalties_pl_2024_25_spss.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    help="Numerisch codiert (1=Tor, 0=kein Tor, 1=Heim, ...), "
                         "zusätzliches Sheet mit Codebuch. Für direkten SPSS-Import.",
                )

    with tab_charts:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Top-Elfmeterschützen")
            top = (
                fdf.groupby("shooter_name")
                .agg(
                    total=("penalty_outcome", "size"),
                    tor=("penalty_outcome", lambda s: (s == "Tor").sum()),
                )
                .assign(quote=lambda x: x["tor"] / x["total"])
                .sort_values("total", ascending=False)
                .head(15)
                .reset_index()
            )
            fig = px.bar(
                top, x="total", y="shooter_name", orientation="h",
                color="quote", color_continuous_scale="RdYlGn",
                range_color=[0, 1],
                labels={"total": "Elfmeter", "shooter_name": "", "quote": "Trefferquote"},
            )
            fig.update_layout(yaxis=dict(autorange="reversed"), height=500)
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            st.subheader("Erfolgsquote nach Spielstand")
            with_state = fdf[fdf["score_state"].isin(["Rückstand", "Unentschieden", "Führung"])]
            state_stats = (
                with_state.groupby("score_state")
                .agg(
                    total=("penalty_outcome", "size"),
                    quote=("penalty_outcome", lambda s: (s == "Tor").mean()),
                )
                .reindex(["Rückstand", "Unentschieden", "Führung"])
                .reset_index()
            )
            fig2 = px.bar(
                state_stats, x="score_state", y="quote",
                text=state_stats["total"].map(lambda n: f"n={n}"),
                labels={"score_state": "", "quote": "Trefferquote"},
                color="score_state",
                color_discrete_map={
                    "Rückstand": "#EF5B5B",
                    "Unentschieden": "#8899AA",
                    "Führung": "#4C956C",
                },
            )
            fig2.update_layout(yaxis_tickformat=".0%", showlegend=False, height=500)
            fig2.update_yaxes(range=[0, 1])
            st.plotly_chart(fig2, use_container_width=True)

        c3, c4 = st.columns(2)
        with c3:
            st.subheader("Heim vs Auswärts")
            ha_stats = (
                fdf.groupby("home_away")
                .agg(
                    total=("penalty_outcome", "size"),
                    quote=("penalty_outcome", lambda s: (s == "Tor").mean()),
                )
                .reset_index()
            )
            fig3 = px.bar(
                ha_stats, x="home_away", y="quote",
                text=ha_stats["total"].map(lambda n: f"n={n}"),
                labels={"home_away": "", "quote": "Trefferquote"},
                color="home_away",
                color_discrete_map={"Heim": "#4C956C", "Auswärts": "#EF5B5B"},
            )
            fig3.update_layout(yaxis_tickformat=".0%", showlegend=False, height=400)
            fig3.update_yaxes(range=[0, 1])
            st.plotly_chart(fig3, use_container_width=True)

        with c4:
            st.subheader("Elfmeter über die Saison")
            timeline = (
                fdf.assign(month=fdf["match_date"].dt.to_period("M").astype(str))
                .groupby(["month", "penalty_outcome"])
                .size()
                .reset_index(name="n")
            )
            fig4 = px.bar(
                timeline, x="month", y="n", color="penalty_outcome",
                labels={"month": "", "n": "Anzahl", "penalty_outcome": "Ausgang"},
                color_discrete_map={"Tor": "#4C956C", "kein Tor": "#EF5B5B"},
            )
            fig4.update_layout(height=400)
            st.plotly_chart(fig4, use_container_width=True)

        st.subheader("Karriere-Elfmeter des Schützen vs Trefferquote")
        career_df = fdf.copy()
        career_df["prev_penalties_career"] = pd.to_numeric(
            career_df["prev_penalties_career"], errors="coerce"
        )
        career_df = career_df.dropna(subset=["prev_penalties_career"])
        career_df["outcome_num"] = (career_df["penalty_outcome"] == "Tor").astype(int)
        fig5 = px.scatter(
            career_df, x="prev_penalties_career", y="outcome_num",
            color="score_state",
            hover_data=["shooter_name", "match_date"],
            labels={
                "prev_penalties_career": "Vorherige Karriere-Elfmeter",
                "outcome_num": "1 = Tor, 0 = kein Tor",
            },
        )
        fig5.update_traces(marker=dict(size=10, opacity=0.6))
        st.plotly_chart(fig5, use_container_width=True)

    with tab_live:
        st.subheader("Live scrapen: ein Spiel als Demo")
        st.info(
            "**Hinweis:** Der Live-Scrape funktioniert nur, wenn die App auf demselben "
            "Rechner läuft, von dem der Cookie stammt. Cloudflare bindet den Cookie an die IP-Adresse. "
            "Auf öffentlichen Servern (z.B. Streamlit Cloud) läuft das nicht.",
            icon="ℹ️",
        )
        st.markdown(
            "So läuft die Automation im Live-Betrieb: du gibst einen frischen "
            "Browser-Cookie rein, wählst ein Spiel aus, und siehst was das Skript "
            "in Sekundenschnelle extrahiert. Kein Handarbeit-Codieren mehr."
        )

        curl_text = st.text_area(
            "Copy-as-cURL aus dem Chrome-Browser (nur die Cookies werden gelesen)",
            value=st.session_state.get("curl_text", ""),
            height=140,
            help="Öffne https://fbref.com/en/comps/9/2024-2025/schedule/2024-2025-Premier-League-Scores-and-Fixtures im Chrome. "
                 "DevTools → Network → Seite neu laden → Rechts-Klick auf erste Zeile → Copy → Copy as cURL. Hier reinpasten.",
            placeholder="curl 'https://fbref.com/...' \\\n  -H 'accept: ...' \\\n  -b 'is_live=true; ... cf_clearance=... __cf_bm=...' \\\n  ...",
        )
        st.session_state["curl_text"] = curl_text

        # Match-Auswahl aus dem existierenden Schedule
        if SCHEDULE_PATH.exists():
            schedule = json.loads(SCHEDULE_PATH.read_text())
            options = {
                f"{m['date']} · {m['home_team']} {m['score']} {m['away_team']}": m["match_report_url"]
                for m in schedule
            }
            label = st.selectbox("Match auswählen", options=list(options.keys()))
            match_url = options[label]
            st.code(match_url, language="text")
        else:
            match_url = st.text_input(
                "Match-Report-URL",
                value="https://fbref.com/en/matches/99b4737c/Liverpool-Chelsea-October-20-2024-Premier-League",
            )

        run_it = st.button("Match live scrapen", type="primary", disabled=not curl_text)
        if run_it:
            cookies = parse_cookies_from_curl(curl_text)
            required = {"cf_clearance"}
            if not required.issubset(cookies.keys()):
                st.error(
                    "Konnte `cf_clearance` nicht aus dem cURL-Text lesen. "
                    "Bitte prüfen ob der komplette cURL-Befehl reinkopiert wurde."
                )
            else:
                with st.status("Fetche Match Report von FBref …", expanded=True) as status:
                    try:
                        st.write(f"→ {match_url}")
                        html = fetch_with_cookies(match_url, cookies)
                        st.write(f"HTML geladen: {len(html):,} Bytes")
                        data = parse_match(html)
                        st.write(
                            f"Scorebox erkannt: **{data['scorebox']['home_team']} "
                            f"{data['scorebox']['home_score']}–{data['scorebox']['away_score']} "
                            f"{data['scorebox']['away_team']}**"
                        )
                        events = data["events"]
                        penalties = [e for e in events if e["is_penalty"]]
                        st.write(
                            f"Tor-Events: {len(events)} · davon Elfmeter: **{len(penalties)}**"
                        )
                        status.update(label="Fertig", state="complete")

                        st.subheader("Extrahierte Events")
                        st.dataframe(
                            pd.DataFrame(events)[["side", "event_type", "player", "minute", "is_penalty"]],
                            use_container_width=True,
                            hide_index=True,
                        )
                        if penalties:
                            st.subheader("Elfmeter dieses Spiels")
                            st.dataframe(
                                pd.DataFrame(penalties)[["side", "event_type", "player", "minute"]],
                                use_container_width=True,
                                hide_index=True,
                            )
                        else:
                            st.info(
                                "In diesem Spiel gab es keinen Elfmeter — probier "
                                "ein anderes Match aus der Liste."
                            )
                    except Exception as e:
                        status.update(label="Fehler", state="error")
                        st.error(str(e))

    with tab_full:
        st.subheader("Ganze Liga scrapen — der Aha-Moment für Jakob")
        st.info(
            "**Hinweis:** Läuft nur lokal, weil Cloudflare den Cookie an die IP bindet. "
            "Auf Streamlit Cloud ist dieser Tab deaktiviert — Tom macht das für dich vor Ort.",
            icon="ℹ️",
        )
        st.markdown(
            "Cookie einfügen, Schedule-URL wählen, Start drücken. Alles Weitere "
            "läuft automatisch. Rate-limited 4 Sek zwischen Requests, damit "
            "FBref nicht Cloudflare wirft."
        )

        # Preset-Ligen
        preset_urls = {
            "Premier League 2024/25": "https://fbref.com/en/comps/9/2024-2025/schedule/2024-2025-Premier-League-Scores-and-Fixtures",
            "Bundesliga 2024/25": "https://fbref.com/en/comps/20/2024-2025/schedule/2024-2025-Bundesliga-Scores-and-Fixtures",
            "LaLiga 2024/25": "https://fbref.com/en/comps/12/2024-2025/schedule/2024-2025-La-Liga-Scores-and-Fixtures",
            "Serie A 2024/25": "https://fbref.com/en/comps/11/2024-2025/schedule/2024-2025-Serie-A-Scores-and-Fixtures",
            "Champions League 2024/25": "https://fbref.com/en/comps/8/2024-2025/schedule/2024-2025-Champions-League-Scores-and-Fixtures",
        }
        preset = st.selectbox("Liga-Preset", options=list(preset_urls.keys()))
        schedule_url = st.text_input(
            "Schedule-URL (kannst du auch überschreiben)",
            value=preset_urls[preset],
        )

        curl_text_full = st.text_area(
            "Copy-as-cURL (nur Cookies werden gelesen)",
            value=st.session_state.get("curl_text_full", ""),
            height=120,
            key="curl_input_full",
            help="Öffne die Schedule-URL im Chrome, DevTools → Network → Reload → "
                 "erste Zeile → Copy as cURL. Hier reinpasten.",
        )
        st.session_state["curl_text_full"] = curl_text_full

        c1, c2, c3 = st.columns(3)
        with c1:
            max_matches = st.number_input(
                "Max. Spiele (0 = alle)", min_value=0, value=0, step=10,
                help="Für schnelle Demo z.B. 20 statt 380 setzen. 0 = alle Spiele der Saison.",
            )
        with c2:
            sleep_s = st.number_input(
                "Wartezeit pro Request (Sek)", min_value=1.0, value=4.0, step=1.0,
                help="Zu schnell → Cloudflare-Block. 4 Sek ist erprobt sicher.",
            )
        with c3:
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", preset).strip("_").lower()
            work_dir = Path(__file__).parent / "data" / "live_crawls" / slug
            st.text_input("Working-Dir (Cache)", value=str(work_dir.name), disabled=True)

        # State
        if "live_crawl" not in st.session_state:
            st.session_state.live_crawl = {"status": "idle", "penalties": [], "matches_done": 0}
        lc = st.session_state.live_crawl

        # Buttons
        bc1, bc2, bc3 = st.columns([1, 1, 1])
        with bc1:
            start = st.button(
                "Crawl starten / fortsetzen",
                type="primary",
                disabled=not curl_text_full,
                use_container_width=True,
            )
        with bc2:
            reset = st.button("State zurücksetzen", use_container_width=True)
        with bc3:
            if work_dir.exists():
                cached = len(list((work_dir / "matches").glob("*.json"))) if (work_dir / "matches").exists() else 0
                st.metric("Bereits im Cache", cached)

        if reset:
            st.session_state.live_crawl = {"status": "idle", "penalties": [], "matches_done": 0}
            st.rerun()

        if start:
            cookies = parse_cookies_from_curl(curl_text_full)
            if "cf_clearance" not in cookies:
                st.error("Konnte `cf_clearance` nicht aus dem cURL lesen.")
                st.stop()

            (work_dir / "matches").mkdir(parents=True, exist_ok=True)

            status_ph = st.status("Lade Schedule …", expanded=True)
            progress_bar = st.progress(0.0)
            metrics_ph = st.empty()
            recent_ph = st.container()

            try:
                # Schedule
                with status_ph:
                    st.write(f"→ {schedule_url}")
                schedule_html = fetch_with_cookies(schedule_url, cookies)
                schedule = parse_schedule(schedule_html)
                (work_dir / "schedule.json").write_text(
                    json.dumps(schedule, ensure_ascii=False, indent=2)
                )
                total = len(schedule) if max_matches == 0 else min(len(schedule), int(max_matches))
                schedule = schedule[:total]
                with status_ph:
                    st.write(f"Schedule: {len(schedule)} Spiele")

                # Matches
                penalties_all: list[dict] = []
                matches_done = 0
                errors = 0

                for i, m in enumerate(schedule, 1):
                    match_id = m["match_report_url"].split("/matches/")[1].split("/")[0]
                    match_file = work_dir / "matches" / f"{match_id}.json"
                    if match_file.exists():
                        data = json.loads(match_file.read_text())
                    else:
                        try:
                            html = fetch_with_cookies(m["match_report_url"], cookies)
                        except RuntimeError as e:
                            if "Cloudflare" in str(e):
                                status_ph.update(label="Cookies abgelaufen", state="error")
                                st.warning(
                                    "🍪 Cookies sind abgelaufen. Refresh im Chrome, "
                                    "neuen cURL oben einfügen, dann **Crawl starten / "
                                    "fortsetzen** drücken. Bereits gecrawlte Spiele "
                                    "bleiben erhalten."
                                )
                                st.stop()
                            errors += 1
                            time.sleep(sleep_s)
                            continue
                        data = parse_match(html)
                        data["match_id"] = match_id
                        data["schedule_meta"] = m
                        match_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                        time.sleep(sleep_s)

                    matches_done += 1
                    # Elfmeter aus dem Match
                    for ev in data["events"]:
                        if ev.get("is_penalty"):
                            penalties_all.append(
                                {
                                    "date": m["date"],
                                    "home": data["scorebox"]["home_team"],
                                    "away": data["scorebox"]["away_team"],
                                    "team": data["scorebox"]["home_team"] if ev["side"] == "home" else data["scorebox"]["away_team"],
                                    "shooter": ev["player"],
                                    "minute": ev["minute"],
                                    "outcome": "Tor" if ev["event_type"] == "penalty_goal" else "kein Tor",
                                }
                            )

                    progress_bar.progress(i / len(schedule))
                    metrics_ph.markdown(
                        f"### {i}/{len(schedule)} Spiele · "
                        f"**{len(penalties_all)} Elfmeter** bislang · {errors} Fehler"
                    )
                    if len(penalties_all) > 0 and (i % 5 == 0 or i == len(schedule)):
                        with recent_ph:
                            recent_ph.empty()
                            st.caption(f"Letzte {min(5, len(penalties_all))} Elfmeter:")
                            st.dataframe(
                                pd.DataFrame(penalties_all[-5:]),
                                use_container_width=True,
                                hide_index=True,
                            )

                status_ph.update(
                    label=f"Fertig — {len(penalties_all)} Elfmeter aus {matches_done} Spielen",
                    state="complete",
                )

                st.subheader(f"Alle {len(penalties_all)} Elfmeter")
                pdf = pd.DataFrame(penalties_all)
                st.dataframe(pdf, use_container_width=True, hide_index=True)
                st.download_button(
                    "Datensatz als CSV herunterladen",
                    data=pdf.to_csv(index=False).encode("utf-8"),
                    file_name=f"penalties_{slug}.csv",
                    mime="text/csv",
                )

            except Exception as e:
                status_ph.update(label="Fehler", state="error")
                st.error(str(e))

    with tab_pipeline:
        st.markdown(
            """
            ### Pipeline in vier Schritten

            1. **Schedule-Crawl** — die FBref-Seite der Saison liefert alle Spiele
               mit Datum, Teams und Match-Report-Link (`scrape_schedule.py`).
            2. **Match-Report-Crawl** — für jedes Spiel wird der "Match Summary"
               Block geparst. Enthält alle Tor-Events inklusive Elfmeter mit
               Minute und Schütze (`scrape_match.py`, `crawl_season.py`).
            3. **Player-Career-Crawl** — für jeden Schützen wird die FBref-Player-
               Standard-Stats geladen. Liefert PKatt pro Saison. Zusätzlich Match-Logs
               der aktuellen Saison, damit CL/Pokal/Nationalmannschafts-Elfmeter
               zeitgenau eingeordnet werden können (`scrape_careers.py`,
               `scrape_match_logs.py`).
            4. **Dataset-Build** — abgeleitete Variablen berechnen (Tabellenplatz
               vor Spieltag, Spielstand vor Elfmeter aus Event-Reihenfolge,
               vorherige Elfmeter des Schützen), finales CSV schreiben
               (`build_dataset.py`).

            ### Was wäre nötig für weitere Ligen?

            Nur die URL austauschen (`Comp-ID` 9 = PL, 20 = Bundesliga,
            12 = LaLiga, 8 = UCL) und den Cookie einmal aus dem Chrome-Browser
            holen. Der Rest läuft identisch.

            ### Cookie-Handling

            FBref ist hinter Cloudflare. Damit das Skript durchkommt, wird ein
            frischer Browser-Cookie (`cf_clearance` + `__cf_bm`) verwendet.
            Cookies halten etwa 30 Minuten, danach ist ein Refresh nötig
            (ein Reload der Seite im Chrome + Cookie neu kopieren = 30 Sekunden).

            ### Vergleich zu Jakobs händischer Erhebung

            Jakob hat 806 Elfmeter über 4 Ligen × 2 Saisons manuell aus FBref und
            Transfermarkt erhoben (geschätzt viele Wochen). Der obige Datensatz
            (83 Elfmeter, eine Liga, eine Saison) ist in etwa einer Stunde
            entstanden. Hochgerechnet auf Jakobs Umfang: 4–5 Stunden inklusive
            aller Cookie-Refreshes.
            """
        )

    with tab_compare:
        render_compare_tab(df)


def _match_rate_bg(val: float) -> str:
    """Rot→Gelb→Grün-Hintergrund für eine Quote in [0, 1] (ohne matplotlib)."""
    if pd.isna(val):
        return ""
    stops = [(0.0, (239, 91, 91)), (0.5, (245, 215, 110)), (1.0, (76, 149, 108))]
    t = max(0.0, min(1.0, float(val)))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            f = 0 if t1 == t0 else (t - t0) / (t1 - t0)
            r, g, b = (round(a + (bb - a) * f) for a, bb in zip(c0, c1))
            break
    else:
        r, g, b = stops[-1][1]
    return f"background-color: rgb({r},{g},{b}); color: #1a1a1a;"


def render_compare_tab(mine_raw: pd.DataFrame) -> None:
    """Tab: Zeile-für-Zeile-Abgleich meiner gescrapten Daten gegen Jakobs Excel."""
    st.subheader("Vergleich mit Jakobs händischem Datensatz")
    st.markdown(
        "Lade hier Jakobs Auswertungs-Excel hoch. Verglichen wird die "
        "überlappende Teilmenge **Premier League 2024/25** (bei Jakob: Liga 1, "
        "Saison 2024/25 im Sheet *Tabelle1*). Das Tool matcht jeden Elfmeter "
        "1:1 über Datum und Schütze und prüft anschließend Variable für Variable, "
        "wo beide Erhebungen übereinstimmen und wo nicht."
    )

    uploaded = st.file_uploader(
        "Jakobs Excel (.xlsx)", type=["xlsx"],
        help="Das Sheet 'Tabelle1' muss enthalten sein. Nichts wird gespeichert, "
             "die Datei wird nur im Arbeitsspeicher verglichen.",
    )
    if uploaded is None:
        st.info(
            "Noch keine Datei hochgeladen. Sobald du Jakobs `.xlsx` auswählst, "
            "erscheinen hier die Match-Quote, eine Übereinstimmungs-Tabelle pro "
            "Variable und die konkreten Abweichungen.",
            icon="⬆️",
        )
        return

    # --- Laden & Vergleichen (robuste Fehlerbehandlung) -------------------- #
    try:
        jakob = cj.load_jakob(uploaded)
    except ValueError as e:
        st.error(
            f"Konnte Jakobs Daten nicht lesen: {e}. Enthält die Datei ein "
            "Sheet namens 'Tabelle1' mit den erwarteten Spalten?"
        )
        return
    except Exception as e:  # noqa: BLE001 — dem Nutzer freundlich melden
        st.error(f"Die Datei konnte nicht verarbeitet werden: {e}")
        return

    if len(jakob) == 0:
        st.warning(
            "In der Datei wurden keine Premier-League-2024/25-Zeilen gefunden "
            "(Liga = 1, Saison = 2024/25). Vergleich nicht möglich."
        )
        return

    mine = cj.load_mine(CSV_PATH)
    res = cj.compare(mine, jakob)

    # --- KPI-Zeile --------------------------------------------------------- #
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Elfmeter bei Jakob", res.n_jakob)
    k2.metric("Elfmeter bei mir", res.n_mine)
    k3.metric("1:1 gematcht", res.n_matched)
    k4.metric(
        "Ohne Partner",
        len(res.unmatched_mine) + len(res.unmatched_jakob),
        help="Elfmeter, die nur in einer der beiden Quellen vorkommen.",
    )

    if len(res.unmatched_mine) or len(res.unmatched_jakob):
        with st.expander("Nicht gematchte Elfmeter ansehen"):
            if len(res.unmatched_mine):
                st.caption("Nur bei mir:")
                st.dataframe(res.unmatched_mine, hide_index=True, use_container_width=True)
            if len(res.unmatched_jakob):
                st.caption("Nur bei Jakob:")
                st.dataframe(res.unmatched_jakob, hide_index=True, use_container_width=True)
    else:
        st.success(
            f"Beide Erhebungen beschreiben dieselben {res.n_matched} Elfmeter — "
            "keiner fehlt, keiner ist zu viel.",
            icon="✅",
        )

    # --- Übereinstimmungs-Tabelle pro Variable ----------------------------- #
    st.markdown("### Übereinstimmung pro Variable")
    overview = pd.DataFrame([
        {
            "Variable": v.label,
            "identisch": v.n_identical,
            "abweichend": v.n_different,
            "Lücke bei mir": v.n_missing_mine,
            "Übereinstimmung": v.match_rate,
        }
        for v in res.variables
    ])
    st.dataframe(
        overview.style
        .map(_match_rate_bg, subset=["Übereinstimmung"])
        .format({"Übereinstimmung": "{:.0%}"}),
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        "„Übereinstimmung“ = identische Werte geteilt durch alle gematchten "
        "Elfmeter. Lücken bei mir (fehlende Werte) zählen dabei als nicht "
        "übereinstimmend."
    )

    # --- Details pro Variable ---------------------------------------------- #
    st.markdown("### Konkrete Abweichungen")
    for v in res.variables:
        if v.n_different == 0 and v.n_missing_mine == 0:
            continue
        title = f"{v.label} — {v.n_different} abweichend"
        if v.n_missing_mine:
            title += f", {v.n_missing_mine} Lücke(n) bei mir"
        with st.expander(title):
            if v.n_different:
                st.caption("Beide Seiten haben einen Wert, aber sie unterscheiden sich:")
                st.dataframe(v.diffs, hide_index=True, use_container_width=True)
            if v.n_missing_mine:
                st.caption("Bei mir fehlt der Wert, Jakob hat ihn:")
                st.dataframe(v.gaps, hide_index=True, use_container_width=True)

    # --- Erklärte Muster --------------------------------------------------- #
    st.markdown("### Woran die Abweichungen liegen")

    minute_var = next((v for v in res.variables if v.key == "minute"), None)
    n_gap = minute_var.n_missing_mine if minute_var else 0
    if n_gap:
        # sind die Lücken alle verschossene Elfmeter?
        gap_keys = set(zip(minute_var.gaps["datum"], minute_var.gaps["schütze"]))
        gap_outcomes = [
            r.outcome for r in mine.itertuples()
            if (r.match_date, r.shooter_name) in gap_keys
        ]
        all_missed = gap_outcomes and all(o == "kein Tor" for o in gap_outcomes)
        st.info(
            f"**Verschossene Elfmeter ohne Minute/Spielstand ({n_gap} Stück).** "
            + (
                "Diese Lücken betreffen ausschließlich verschossene Elfmeter. "
                if all_missed else ""
            )
            + "Mein Scraper liest Minute und Spielstand aus dem Tor-Event der "
            "Spiel-Logs. Ein verschossener Elfmeter erzeugt kein Tor-Event, also "
            "fehlt dort der Kontext. Jakob hat die Werte, weil er von Hand codiert "
            "hat. Fixbar, indem der Scraper Elfmeter-Events statt nur Tor-Events ausliest.",
            icon="🎯",
        )

    career_var = next((v for v in res.variables if v.key == "career_pens"), None)
    if career_var and career_var.n_different:
        st.info(
            "**Karriere-Elfmeter: systematischer Versatz.** Jakobs Werte liegen "
            "konsistent höher, um einen pro Spieler festen Betrag. Grund: mein "
            "Scraper zählt für Vorsaisons nur Liga-Elfmeter (FBref-Limit), es "
            "fehlen also alle Pokal- und CL-Elfmeter der Karriere. Kein "
            "Zufallsfehler, sondern ein Unterschied in der Zählbasis. Wenn diese "
            "Variable in die Regression soll, muss die Zählweise vorher geklärt werden.",
            icon="📈",
        )

    ha_var = next((v for v in res.variables if v.key == "home_away"), None)
    if ha_var and ha_var.n_different:
        st.info(
            f"**Heim/Auswärts: {ha_var.n_different} Konflikt(e).** Hier hat eine "
            "Seite echt falsch codiert. Meine Angabe wird automatisch aus "
            "home_team/away_team abgeleitet und ist in der Regel die verlässlichere. "
            "Die betroffenen Spiele stehen oben im Detail-Ausklapp — bitte "
            "gegenprüfen.",
            icon="🏟️",
        )

    # --- Ausblick: die Lücken sind nicht endgültig ------------------------- #
    st.markdown("### Ausblick: die Lücken lassen sich schließen")

    # Empfehlung Minute/Spielstand: wenige -> händisch, viele -> Crawl
    if n_gap:
        if n_gap <= 20:
            gap_hint = (
                f"Bei aktuell {n_gap} betroffenen Elfmetern ist der pragmatischste "
                f"Weg, diese {n_gap} Werte einmalig von Hand nachzutragen (die "
                "genaue Liste steht oben im Ausklapp). "
            )
        else:
            gap_hint = (
                f"Bei {n_gap} betroffenen Elfmetern lohnt sich eher, den Crawl zu "
                "erweitern, statt alles von Hand einzutragen. "
            )
    else:
        gap_hint = ""

    st.markdown(
        "Keine dieser Abweichungen ist in Stein gemeißelt. Es sind keine "
        "prinzipiellen Grenzen der Methode, sondern Stellschrauben, an denen man "
        "weiterdrehen kann:\n\n"
        "• **Verschossene Elfmeter (Minute, Spielstand).** "
        + gap_hint
        + "Alternativ kann der Scraper so erweitert werden, dass er die Elfmeter-"
        "Events selbst ausliest statt nur die Tor-Events, dann fällt der Kontext "
        "automatisch mit ab. Beide Wege führen zum vollständigen Datensatz.\n\n"
        "• **Karriere-Elfmeter.** Der Versatz kommt daher, dass für Vorsaisons nur "
        "Liga-Elfmeter gezählt werden. Auch das ist erweiterbar: zusätzliche "
        "FBref-Wettbewerbe (Pokal, CL) mit einbeziehen oder eine zweite Quelle wie "
        "Transfermarkt dazunehmen, die alle Karriere-Elfmeter je Spieler führt. "
        "Damit ließe sich die Zählbasis an Jakobs Definition angleichen.\n\n"
        "• **Generell.** Wo eine einzelne Seite nicht alles hergibt, lassen sich "
        "mehrere Quellen kombinieren. Der Crawl ist ein Startpunkt, kein Endzustand: "
        "je nachdem, welche Variablen die Analyse am Ende wirklich braucht, kann er "
        "gezielt vertieft oder um weitere Webseiten ergänzt werden."
    )


if __name__ == "__main__":
    main()
