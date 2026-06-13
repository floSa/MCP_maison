"""Niveau 4 — tests de bout en bout : stack Docker complète + VRAI petit LLM.

Lancement : docker compose --profile e2e run --rm tests-e2e
(le LLM tourne sur CPU : chaque question prend de quelques secondes à ~2 min)
"""

import os

import httpx
import pytest

pytestmark = pytest.mark.e2e

AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:8080")
UI_URL = os.environ.get("UI_URL", "http://ui:8501")
DELAI = httpx.Timeout(600.0)


def test_sante():
    reponse = httpx.get(f"{AGENT_URL}/sante", timeout=10)
    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "ok"


def test_ui_streamlit_en_ligne():
    reponse = httpx.get(f"{UI_URL}/_stcore/health", timeout=10)
    assert reponse.status_code == 200


def test_trois_fois_quatre_plus_deux():
    reponse = httpx.post(f"{AGENT_URL}/calcul",
                         json={"question": "trois fois quatre plus deux"},
                         timeout=DELAI)
    assert reponse.status_code == 200
    donnees = reponse.json()
    assert donnees["valide"] is True, donnees
    assert abs(donnees["reponse"] - 14) < 1e-6
    assert donnees["formule"] == "3 * 4 + 2"

    # Preuve d'absence de triche : chaque opération vient de l'outil calculer,
    # dans l'ordre des priorités (3*4 d'abord, puis 12+2).
    calculs = [(float(e["arguments"]["gauche"]), e["arguments"]["operateur"],
                float(e["arguments"]["droite"]))
               for e in donnees["etapes"]
               if e["type"] == "outil" and e["nom"] == "calculer"]
    assert calculs == [(3.0, "*", 4.0), (12.0, "+", 2.0)]


def test_priorite_respectee():
    reponse = httpx.post(f"{AGENT_URL}/calcul",
                         json={"question": "dix moins deux fois trois"},
                         timeout=DELAI)
    assert reponse.status_code == 200
    donnees = reponse.json()
    assert donnees["valide"] is True, donnees
    assert abs(donnees["reponse"] - 4) < 1e-6   # 10 - (2*3), pas (10-2)*3
