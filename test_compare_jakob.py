"""Tests für die Vergleichslogik (compare_jakob).

Zwei Ebenen:
1. Unit-Tests mit kleinen synthetischen DataFrames — deterministisch, keine
   sensiblen Fremddaten, definieren die API.
2. Ein Integrationstest gegen die echten Dateien — pinnt die Logik auf die im
   Vorgänger-Chat manuell verifizierten Zahlen (83 vs 83, Tor 83/83,
   Karriere 6/83). Wird übersprungen, wenn Jakobs Excel nicht lokal vorliegt
   (die Datei ist Fremd-Forschungsdaten und wird NICHT ins Repo committet).
"""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import compare_jakob as cj

JAKOB_XLSX = Path.home() / "Downloads" / "Datensatz_Bachelorarbeit_Jakob Schneider_Auswertung.xlsx"
MY_CSV = Path(__file__).parent / "data" / "processed" / "penalties_pl_2024_25.csv"


# --------------------------------------------------------------------------- #
# normalize_name
# --------------------------------------------------------------------------- #

def test_normalize_name_folds_oslash():
    # ø darf nicht verloren gehen (Ødegaard-Problem)
    assert cj.normalize_name("Martin Ødegaard") == cj.normalize_name("Martin Odegaard")


def test_normalize_name_is_case_and_space_insensitive():
    assert cj.normalize_name("  Mohamed  SALAH ") == "mohamed salah"


# --------------------------------------------------------------------------- #
# Hilfsfunktion: kanonische Frames bauen
# --------------------------------------------------------------------------- #

def _std_row(**kw):
    base = dict(
        match_date=date(2024, 9, 28),
        shooter_name="Mohamed Salah",
        outcome="Tor",
        penalty_type="Im Spiel",
        home_away="Heim",
        league_position=1.0,
        minute=61.0,
        score_for=1.0,
        score_against=1.0,
        career_pens=52.0,
    )
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #

def test_match_pairs_exact_name_and_date():
    mine = pd.DataFrame([_std_row()])
    jakob = pd.DataFrame([_std_row(career_pens=53.0)])  # andere Werte, gleicher Key
    res = cj.compare(mine, jakob)
    assert res.n_mine == 1
    assert res.n_jakob == 1
    assert res.n_matched == 1
    assert len(res.unmatched_mine) == 0
    assert len(res.unmatched_jakob) == 0


def test_match_folds_oslash_across_sources():
    mine = pd.DataFrame([_std_row(shooter_name="Martin Ødegaard")])
    jakob = pd.DataFrame([_std_row(shooter_name="Martin Odegaard")])
    res = cj.compare(mine, jakob)
    assert res.n_matched == 1


def test_match_fuzzy_recovers_typo_in_surname():
    # "Amstrong" (Jakobs Tippfehler) muss auf "Armstrong" matchen
    mine = pd.DataFrame([_std_row(shooter_name="Adam Armstrong")])
    jakob = pd.DataFrame([_std_row(shooter_name="Adam Amstrong")])
    res = cj.compare(mine, jakob)
    assert res.n_matched == 1


def test_unmatched_when_no_partner():
    mine = pd.DataFrame([_std_row(shooter_name="Erling Haaland")])
    jakob = pd.DataFrame([_std_row(match_date=date(2020, 1, 1), shooter_name="Someone Else")])
    res = cj.compare(mine, jakob)
    assert res.n_matched == 0
    assert len(res.unmatched_mine) == 1
    assert len(res.unmatched_jakob) == 1


# --------------------------------------------------------------------------- #
# Variablenvergleich
# --------------------------------------------------------------------------- #

def _var(res, key):
    return next(v for v in res.variables if v.key == key)


def test_variable_identical_when_values_agree():
    mine = pd.DataFrame([_std_row()])
    jakob = pd.DataFrame([_std_row()])
    res = cj.compare(mine, jakob)
    outcome = _var(res, "outcome")
    assert outcome.n_identical == 1
    assert outcome.n_different == 0
    assert outcome.n_missing_mine == 0


def test_variable_flags_difference_and_lists_it():
    mine = pd.DataFrame([_std_row(home_away="Heim")])
    jakob = pd.DataFrame([_std_row(home_away="Auswärts")])
    res = cj.compare(mine, jakob)
    ha = _var(res, "home_away")
    assert ha.n_identical == 0
    assert ha.n_different == 1
    assert len(ha.diffs) == 1
    row = ha.diffs.iloc[0]
    assert row["wert_jakob"] == "Auswärts"
    assert row["wert_mine"] == "Heim"


def test_variable_counts_gap_when_mine_is_missing():
    # Verschossener Elfmeter: bei mir fehlt die Minute (NaN), Jakob hat sie
    mine = pd.DataFrame([_std_row(outcome="kein Tor", minute=float("nan"))])
    jakob = pd.DataFrame([_std_row(outcome="kein Tor", minute=88.0)])
    res = cj.compare(mine, jakob)
    minute = _var(res, "minute")
    assert minute.n_missing_mine == 1
    assert minute.n_identical == 0
    assert minute.n_different == 0


# --------------------------------------------------------------------------- #
# Integrationstest gegen die echten Daten (skip wenn Excel fehlt)
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not JAKOB_XLSX.exists(), reason="Jakobs Excel nicht lokal vorhanden")
def test_integration_reproduces_ground_truth():
    mine = cj.load_mine(MY_CSV)
    jakob = cj.load_jakob(JAKOB_XLSX)
    res = cj.compare(mine, jakob)

    # Grundgesamtheit
    assert res.n_mine == 83
    assert res.n_jakob == 83
    assert res.n_matched == 83

    # Ergebnis & Elfmetertyp: 100% Übereinstimmung
    assert _var(res, "outcome").n_identical == 83
    assert _var(res, "penalty_type").n_identical == 83

    # Karriere-Elfmeter: bekannter systematischer Versatz -> nur 6 identisch
    assert _var(res, "career_pens").n_identical == 6

    # Heim/Auswärts: 2 Konflikte
    assert _var(res, "home_away").n_different == 2

    # Minute: 14 Lücken bei mir sind exakt die verschossenen Elfmeter
    minute = _var(res, "minute")
    assert minute.n_missing_mine == 14
