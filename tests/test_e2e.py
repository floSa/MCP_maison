"""Niveau 4 — tests de bout en bout : stack Docker complète + VRAI petit LLM.

Lancement : docker compose --profile e2e run --rm tests-e2e
(sur GPU une question prend quelques secondes ; sur CPU jusqu'à ~2 min)
"""

import json
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


def test_streaming_sse():
    """L'endpoint /calcul/stream emet bien des evenements SSE au fil de l'eau,
    dont au moins un appel d'outil MCP et un evenement final valide."""
    evenements = []
    with httpx.stream("POST", f"{AGENT_URL}/calcul/stream",
                      json={"question": "trois fois quatre plus deux"},
                      timeout=DELAI) as reponse:
        assert reponse.status_code == 200
        for ligne in reponse.iter_lines():
            if ligne.startswith("data: "):
                evenements.append(json.loads(ligne[len("data: "):]))

    types = [e["type"] for e in evenements]
    assert "outil" in types          # au moins un appel MCP a ete emis
    assert types[-1] == "fin"        # le dernier evenement resume le resultat
    final = evenements[-1]
    assert final["valide"] is True, final
    assert abs(final["reponse"] - 14) < 1e-6
