"""Niveau 3 — tests de la boucle ReAct avec un FAUX LLM scripté.

C'est ici qu'on prouve que l'agent ne peut pas tricher : on scénarise des LLM
honnêtes, tricheurs ou maladroits, et on vérifie que l'arbitre laisse passer
les premiers et bloque les autres. Tout est déterministe (aucun vrai LLM).
"""

from fastmcp import Client

import serveur
from agent.boucle_react import AgentReact


class FauxLLM:
    """Rejoue une liste de messages pré-écrits, comme le ferait un LLM."""

    def __init__(self, scenario):
        self.scenario = list(scenario)

    async def repondre(self, messages, outils):
        if not self.scenario:
            # Un vrai tricheur insiste : il répète sa réponse sans outils.
            return {"role": "assistant", "content": "REPONSE FINALE: 14"}
        return self.scenario.pop(0)


def appel(nom, **arguments):
    """Construit un message « le LLM demande cet outil »."""
    return {"role": "assistant", "content": "",
            "tool_calls": [{"function": {"name": nom, "arguments": arguments}}]}


def reponse(texte):
    return {"role": "assistant", "content": texte}


def agent_avec(scenario, max_iterations=25):
    return AgentReact(llm=FauxLLM(scenario), client_mcp=Client(serveur.mcp),
                      max_iterations=max_iterations)


SCENARIO_HONNETE = [
    appel("convertir_texte_en_formule", texte="trois fois quatre plus deux"),
    appel("trouver_calcul_prioritaire", formule="3 * 4 + 2"),
    appel("calculer", gauche=3, operateur="*", droite=4),
    appel("remplacer_calcul_par_resultat",
          formule="3 * 4 + 2", sous_expression="3 * 4", valeur=12),
    appel("trouver_calcul_prioritaire", formule="12 + 2"),
    appel("calculer", gauche=12, operateur="+", droite=2),
    appel("remplacer_calcul_par_resultat",
          formule="12 + 2", sous_expression="12 + 2", valeur=14),
    reponse("REPONSE FINALE: 14"),
]


async def test_agent_honnete_valide():
    resultat = await agent_avec(SCENARIO_HONNETE).resoudre(
        "trois fois quatre plus deux")
    assert resultat["valide"] is True
    assert resultat["reponse"] == 14
    assert resultat["formule"] == "3 * 4 + 2"
    # La trace prouve que chaque calcul vient bien de l'outil, dans l'ordre.
    calculs = [(e["arguments"]["gauche"], e["arguments"]["operateur"],
                e["arguments"]["droite"])
               for e in resultat["etapes"]
               if e["type"] == "outil" and e["nom"] == "calculer"]
    assert calculs == [(3, "*", 4), (12, "+", 2)]


async def test_tricheur_total_rejete():
    """Le LLM répond « 14 » direct, sans aucun outil : refus jusqu'au bout.

    Même si 14 est numériquement correct, la réponse est invalide car elle
    n'a pas été obtenue par les outils — c'est exactement l'anti-triche.
    """
    resultat = await agent_avec([reponse("REPONSE FINALE: 14")],
                                max_iterations=3).resoudre(
        "trois fois quatre plus deux")
    assert resultat["valide"] is False
    assert resultat["reponse"] is None
    refus = [e for e in resultat["etapes"] if e["type"] == "refus_arbitre"]
    assert len(refus) == 3   # rejeté à chaque itération


async def test_tricheur_partiel_force_a_terminer():
    """Le LLM convertit, puis tente de répondre de tête : l'arbitre refuse,
    et le LLM doit terminer proprement avec les outils."""
    scenario = (
        [SCENARIO_HONNETE[0],                # conversion
         reponse("REPONSE FINALE: 14")]      # tentative de triche
        + SCENARIO_HONNETE[1:]               # puis il fait le travail
    )
    resultat = await agent_avec(scenario).resoudre("trois fois quatre plus deux")
    assert resultat["valide"] is True
    assert resultat["reponse"] == 14
    refus = [e for e in resultat["etapes"] if e["type"] == "refus_arbitre"]
    assert any("pas encore réduite" in e["detail"] for e in refus)


async def test_mauvais_calcul_refuse_puis_corrige():
    """Le LLM tente de calculer 4 + 2 (non prioritaire) : refus de l'arbitre,
    avec un message qui lui indique le calcul attendu."""
    scenario = (
        SCENARIO_HONNETE[:2]
        + [appel("calculer", gauche=4, operateur="+", droite=2)]   # faux
        + SCENARIO_HONNETE[2:]
    )
    resultat = await agent_avec(scenario).resoudre("trois fois quatre plus deux")
    assert resultat["valide"] is True
    assert resultat["reponse"] == 14
    refus = [e for e in resultat["etapes"] if e["type"] == "refus_arbitre"]
    assert any("calcul prioritaire" in e["detail"] for e in refus)


async def test_valeur_inventee_au_remplacement_refusee():
    """Le LLM appelle calculer, mais essaie d'insérer 99 au remplacement."""
    scenario = (
        SCENARIO_HONNETE[:3]
        + [appel("remplacer_calcul_par_resultat",
                 formule="3 * 4 + 2", sous_expression="3 * 4", valeur=99)]
        + SCENARIO_HONNETE[3:]
    )
    resultat = await agent_avec(scenario).resoudre("trois fois quatre plus deux")
    assert resultat["valide"] is True
    refus = [e for e in resultat["etapes"] if e["type"] == "refus_arbitre"]
    assert any("calculer" in e["detail"] for e in refus)


async def test_reponse_finale_fausse_refusee():
    """Tout le travail est fait, mais le LLM annonce 15 au lieu de 14."""
    scenario = SCENARIO_HONNETE[:-1] + [reponse("REPONSE FINALE: 15"),
                                        reponse("REPONSE FINALE: 14")]
    resultat = await agent_avec(scenario).resoudre("trois fois quatre plus deux")
    assert resultat["valide"] is True
    assert resultat["reponse"] == 14
    refus = [e for e in resultat["etapes"] if e["type"] == "refus_arbitre"]
    assert any("ne correspond pas" in e["detail"] for e in refus)
