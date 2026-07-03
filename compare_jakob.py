"""Vergleich: mein gescrapter Elfmeter-Datensatz vs. Jakobs händische Excel.

Vergleichbar ist nur die Überschneidung: Premier League 2024/25.
Bei Jakob = Liga 1, Saison 2024/25 in Sheet 'Tabelle1' (numerisch codiert).
Bei mir  = das komplette CSV (ist bereits genau diese Teilmenge).

Ablauf:
    mine  = load_mine(csv_path_or_buffer)
    jakob = load_jakob(xlsx_path_or_buffer)
    res   = compare(mine, jakob)

`compare` matcht 1:1 über Datum + Schütze (mit ø-Faltung und Fuzzy-Fallback für
Tippfehler) und vergleicht anschließend Variable für Variable.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher

import pandas as pd

# --------------------------------------------------------------------------- #
# Konstanten
# --------------------------------------------------------------------------- #

JAKOB_SHEET = "Tabelle1"
LEAGUE_PL = 1
SEASON = "2024/25"

# Kanonisches Schema, auf das beide Quellen normalisiert werden.
CANON_COLUMNS = [
    "match_date", "shooter_name", "outcome", "penalty_type", "home_away",
    "league_position", "minute", "score_for", "score_against", "career_pens",
]

# Variablen, die verglichen werden: (key, Anzeigename, numerisch?)
VARIABLES: list[tuple[str, str, bool]] = [
    ("outcome", "Ergebnis (Tor / kein Tor)", False),
    ("penalty_type", "Elfmetertyp", False),
    ("home_away", "Heim / Auswärts", False),
    ("league_position", "Tabellenplatz vor Spieltag", True),
    ("minute", "Minute", True),
    ("score_for", "Spielstand Team", True),
    ("score_against", "Spielstand Gegner", True),
    ("career_pens", "Karriere-Elfmeter vorher", True),
]

_FUZZY_THRESHOLD = 0.82


# --------------------------------------------------------------------------- #
# Namensnormalisierung
# --------------------------------------------------------------------------- #

def normalize_name(name: str) -> str:
    """Kleinschreibung, Whitespace normalisiert, Diakritika/ø entfernt."""
    if not isinstance(name, str):
        return ""
    # ø/Ø zerfällt unter NFKD nicht -> manuell ersetzen
    n = name.replace("ø", "o").replace("Ø", "O")
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.encode("ascii", "ignore").decode("ascii")
    return " ".join(n.lower().split())


def _surname(name: str) -> str:
    norm = normalize_name(name)
    return norm.split()[-1] if norm else ""


# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #

def load_mine(source) -> pd.DataFrame:
    """Liest mein CSV und bringt es aufs kanonische Schema."""
    df = pd.read_csv(source)
    out = pd.DataFrame({
        "match_date": pd.to_datetime(df["match_date"]).dt.date,
        "shooter_name": df["shooter_name"].astype(str),
        "outcome": df["penalty_outcome"],
        "penalty_type": df["penalty_type"],
        "home_away": df["home_away"],
        "league_position": pd.to_numeric(df["league_position_before"], errors="coerce"),
        "minute": pd.to_numeric(df["minute"], errors="coerce"),
        "score_for": pd.to_numeric(df["score_for_before"], errors="coerce"),
        "score_against": pd.to_numeric(df["score_against_before"], errors="coerce"),
        "career_pens": pd.to_numeric(df["prev_penalties_career"], errors="coerce"),
    })
    return out


def load_jakob(source) -> pd.DataFrame:
    """Liest Jakobs 'Tabelle1', filtert auf PL 2024/25 und decodiert die
    numerischen Spalten aufs kanonische Schema."""
    df = pd.read_excel(source, sheet_name=JAKOB_SHEET)
    df = df[(df["Liga"] == LEAGUE_PL) & (df["Saison"].astype(str) == SEASON)].copy()

    out = pd.DataFrame({
        "match_date": pd.to_datetime(df["Datum "]).dt.date,
        "shooter_name": df["Spieler"].astype(str),
        "outcome": df["Tor"].map({1: "Tor", 0: "kein Tor"}),
        "penalty_type": df["Efmetertyp"].map({0: "Im Spiel", 1: "Elfmeterschießen"}),
        "home_away": df["Heim"].map({1: "Heim", 0: "Auswärts"}),
        "league_position": pd.to_numeric(df["Tabellenplatz_vor_Spieltag"], errors="coerce"),
        "minute": pd.to_numeric(df["Minute"], errors="coerce"),
        "score_for": pd.to_numeric(df["Spielstand_Team"], errors="coerce"),
        "score_against": pd.to_numeric(df["Spielstand_Gegner"], errors="coerce"),
        "career_pens": pd.to_numeric(df["Karriere_Elfmeter_vorher"], errors="coerce"),
    })
    return out.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Ergebnis-Datenstrukturen
# --------------------------------------------------------------------------- #

@dataclass
class VariableComparison:
    key: str
    label: str
    n_total: int            # Anzahl gematchter Paare
    n_both_present: int     # beide Seiten haben einen Wert
    n_identical: int
    n_different: int
    n_missing_mine: int     # bei mir NaN, bei Jakob vorhanden
    n_missing_jakob: int
    diffs: pd.DataFrame     # Zeilen mit abweichenden Werten
    gaps: pd.DataFrame      # Zeilen mit Lücke bei mir

    @property
    def match_rate(self) -> float:
        return self.n_identical / self.n_total if self.n_total else 0.0


@dataclass
class ComparisonResult:
    n_mine: int
    n_jakob: int
    n_matched: int
    unmatched_mine: pd.DataFrame
    unmatched_jakob: pd.DataFrame
    variables: list[VariableComparison] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Matching (1:1 über Datum + Name)
# --------------------------------------------------------------------------- #

def _match_indices(mine: pd.DataFrame, jakob: pd.DataFrame) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Greedy 1:1-Matching. Tier 1 exakter Name, Tier 2 Nachname, Tier 3 Fuzzy."""
    mine_keys = [
        (r.match_date, normalize_name(r.shooter_name), _surname(r.shooter_name))
        for r in mine.itertuples()
    ]
    jakob_keys = [
        (r.match_date, normalize_name(r.shooter_name), _surname(r.shooter_name))
        for r in jakob.itertuples()
    ]

    used_jakob: set[int] = set()
    pairs: list[tuple[int, int]] = []
    unmatched_mine: list[int] = []

    for mi, (m_date, m_name, m_surn) in enumerate(mine_keys):
        candidates = [
            ji for ji, (j_date, _, _) in enumerate(jakob_keys)
            if ji not in used_jakob and j_date == m_date
        ]
        match = None
        # Tier 1: exakter Name
        for ji in candidates:
            if jakob_keys[ji][1] == m_name:
                match = ji
                break
        # Tier 2: Nachname
        if match is None:
            for ji in candidates:
                if jakob_keys[ji][2] == m_surn:
                    match = ji
                    break
        # Tier 3: Fuzzy auf Nachname
        if match is None:
            best_ratio = _FUZZY_THRESHOLD
            for ji in candidates:
                ratio = SequenceMatcher(None, m_surn, jakob_keys[ji][2]).ratio()
                if ratio >= best_ratio:
                    best_ratio = ratio
                    match = ji
        if match is not None:
            used_jakob.add(match)
            pairs.append((mi, match))
        else:
            unmatched_mine.append(mi)

    unmatched_jakob = [ji for ji in range(len(jakob_keys)) if ji not in used_jakob]
    return pairs, unmatched_mine, unmatched_jakob


# --------------------------------------------------------------------------- #
# Vergleich
# --------------------------------------------------------------------------- #

def _values_equal(a, b, numeric: bool) -> bool:
    if numeric:
        return round(float(a), 6) == round(float(b), 6)
    return str(a) == str(b)


def _compare_variable(
    key: str, label: str, numeric: bool,
    mine: pd.DataFrame, jakob: pd.DataFrame, pairs: list[tuple[int, int]],
) -> VariableComparison:
    n_identical = n_different = n_missing_mine = n_missing_jakob = n_both = 0
    diff_rows: list[dict] = []
    gap_rows: list[dict] = []

    for mi, ji in pairs:
        mv = mine.iloc[mi][key]
        jv = jakob.iloc[ji][key]
        m_na = pd.isna(mv)
        j_na = pd.isna(jv)
        meta = {
            "datum": mine.iloc[mi]["match_date"],
            "schütze": mine.iloc[mi]["shooter_name"],
        }
        if m_na and not j_na:
            n_missing_mine += 1
            gap_rows.append({**meta, "wert_jakob": jv})
            continue
        if j_na and not m_na:
            n_missing_jakob += 1
            continue
        if m_na and j_na:
            continue
        n_both += 1
        if _values_equal(mv, jv, numeric):
            n_identical += 1
        else:
            n_different += 1
            diff_rows.append({**meta, "wert_jakob": jv, "wert_mine": mv})

    return VariableComparison(
        key=key, label=label, n_total=len(pairs), n_both_present=n_both,
        n_identical=n_identical, n_different=n_different,
        n_missing_mine=n_missing_mine, n_missing_jakob=n_missing_jakob,
        diffs=pd.DataFrame(diff_rows), gaps=pd.DataFrame(gap_rows),
    )


def compare(mine: pd.DataFrame, jakob: pd.DataFrame) -> ComparisonResult:
    """Vollständiger Vergleich zweier kanonischer Frames."""
    pairs, unmatched_mine_idx, unmatched_jakob_idx = _match_indices(mine, jakob)

    variables = [
        _compare_variable(key, label, numeric, mine, jakob, pairs)
        for key, label, numeric in VARIABLES
    ]

    return ComparisonResult(
        n_mine=len(mine),
        n_jakob=len(jakob),
        n_matched=len(pairs),
        unmatched_mine=mine.iloc[unmatched_mine_idx].reset_index(drop=True),
        unmatched_jakob=jakob.iloc[unmatched_jakob_idx].reset_index(drop=True),
        variables=variables,
    )
