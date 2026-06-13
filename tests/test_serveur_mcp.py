"""Niveau 2 — tests d'intégration du serveur MCP.

Le client FastMCP se connecte ici « en mémoire » directement à l'objet
serveur : on teste le vrai protocole MCP (découverte + appels) sans réseau.
"""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import llm
import serveur
from agent.boucle_react import extraire_donnees


async def test_decouverte_des_outils():
    async with Client(serveur.mcp) as client:
        noms = {outil.name for outil in await client.list_tools()}
    assert noms == {
        "convertir_texte_en_formule",
        "convertir_texte_en_formule_libre",
        "trouver_calcul_prioritaire",
        "calculer",
        "remplacer_calcul_par_resultat",
    }


async def test_scenario_complet_via_mcp():
    """Rejoue à la main la résolution de « trois fois quatre plus deux »."""
    async with Client(serveur.mcp) as client:
        formule = extraire_donnees(await client.call_tool(
            "convertir_texte_en_formule",
            {"texte": "trois fois quatre plus deux"}))
        assert formule == "3 * 4 + 2"

        prio = extraire_donnees(await client.call_tool(
            "trouver_calcul_prioritaire", {"formule": formule}))
        assert (prio["gauche"], prio["operateur"], prio["droite"]) == (3, "*", 4)

        produit = extraire_donnees(await client.call_tool(
            "calculer", {"gauche": 3, "operateur": "*", "droite": 4}))
        assert produit == 12

        formule = extraire_donnees(await client.call_tool(
            "remplacer_calcul_par_resultat",
            {"formule": formule, "sous_expression": "3 * 4", "valeur": 12}))
        assert formule == "12 + 2"

        somme = extraire_donnees(await client.call_tool(
            "calculer", {"gauche": 12, "operateur": "+", "droite": 2}))
        assert somme == 14


async def test_les_erreurs_remontent_au_client():
    async with Client(serveur.mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "calculer", {"gauche": 1, "operateur": "/", "droite": 0})
        with pytest.raises(ToolError):
            await client.call_tool(
                "convertir_texte_en_formule", {"texte": "bonjour le monde"})


# --- l'outil LLM et son garde-fou deterministe -------------------------------
# On simule le LLM (monkeypatch) pour tester le PATRON de robustesse sans
# dependre d'un vrai modele : « le LLM propose, le code deterministe dispose ».

async def test_outil_llm_normalise_une_sortie_valide(monkeypatch):
    # Le LLM propose une formule correcte mais mal espacee.
    monkeypatch.setattr(llm, "proposer_formule", lambda texte: "2*3")
    async with Client(serveur.mcp) as client:
        formule = extraire_donnees(await client.call_tool(
            "convertir_texte_en_formule_libre", {"texte": "le double de trois"}))
    assert formule == "2 * 3"


async def test_outil_llm_rejette_une_sortie_invalide(monkeypatch):
    # Le LLM propose du charabia : l'outil DOIT echouer (jamais de garbage).
    monkeypatch.setattr(llm, "proposer_formule", lambda texte: "patate ( (")
    async with Client(serveur.mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "convertir_texte_en_formule_libre", {"texte": "n importe quoi"})
