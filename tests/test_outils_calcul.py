"""Niveau 1 — tests unitaires des fonctions pures (sans MCP, sans LLM)."""

import pytest

import outils_calcul as oc


# --- convertir_texte_en_formule ---------------------------------------------

@pytest.mark.parametrize("texte, attendu", [
    ("trois fois quatre plus deux", "3 * 4 + 2"),
    ("Combien font 3 fois 4 plus 2 ?", "3 * 4 + 2"),
    ("vingt et un divisé par sept", "21 / 7"),
    ("quatre-vingt-deux moins douze", "82 - 12"),
    ("soixante-dix-sept plus une", "77 + 1"),
    ("dix multiplié par deux", "10 * 2"),
    ("six sur trois", "6 / 3"),
    ("ouvre parenthèse deux plus trois ferme parenthèse fois quatre",
     "( 2 + 3 ) * 4"),
    ("( 2 + 3 ) * 4", "( 2 + 3 ) * 4"),
    ("3,5 plus 1", "3.5 + 1"),
    ("3*4+2", "3 * 4 + 2"),
])
def test_conversion(texte, attendu):
    assert oc.convertir_texte_en_formule(texte) == attendu


@pytest.mark.parametrize("texte", [
    "bonjour le monde",
    "trois plus",
    "plus trois quatre",
    "",
    "ouvre parenthèse deux plus trois",
])
def test_conversion_invalide(texte):
    with pytest.raises(oc.ErreurCalculatrice):
        oc.convertir_texte_en_formule(texte)


# --- trouver_calcul_prioritaire ---------------------------------------------

@pytest.mark.parametrize("formule, gauche, operateur, droite", [
    ("3 * 4 + 2", 3, "*", 4),        # * avant +
    ("3 + 4 * 2", 4, "*", 2),        # * avant +, même plus à droite
    ("3 + 4 - 2", 3, "+", 4),        # sinon de gauche à droite
    ("( 3 + 4 ) * 2", 3, "+", 4),    # parenthèses d'abord
    ("8 / 2 * 3", 8, "/", 2),        # / et * : gauche à droite
    ("10 - -3", 10, "-", -3),        # nombre négatif issu d'une étape
])
def test_priorite(formule, gauche, operateur, droite):
    prio = oc.trouver_calcul_prioritaire(formule)
    assert prio["termine"] is False
    assert (prio["gauche"], prio["operateur"], prio["droite"]) == (gauche, operateur, droite)


def test_priorite_formule_reduite():
    prio = oc.trouver_calcul_prioritaire("14")
    assert prio["termine"] is True
    assert prio["valeur"] == 14


# --- calculer ----------------------------------------------------------------

@pytest.mark.parametrize("gauche, operateur, droite, attendu", [
    (3, "*", 4, 12),
    (12, "+", 2, 14),
    (10, "/", 4, 2.5),
    (2, "-", 5, -3),
])
def test_calculer(gauche, operateur, droite, attendu):
    assert oc.calculer(gauche, operateur, droite) == attendu


def test_calculer_division_par_zero():
    with pytest.raises(oc.ErreurCalculatrice):
        oc.calculer(1, "/", 0)


def test_calculer_operateur_inconnu():
    with pytest.raises(oc.ErreurCalculatrice):
        oc.calculer(1, "^", 2)


# --- remplacer_calcul_par_resultat --------------------------------------------

def test_remplacement():
    assert oc.remplacer_calcul_par_resultat("3 * 4 + 2", "3 * 4", 12) == "12 + 2"


def test_remplacement_supprime_parentheses():
    assert oc.remplacer_calcul_par_resultat("( 3 + 4 ) * 2", "3 + 4", 7) == "7 * 2"


def test_remplacement_refuse_sous_expression_non_prioritaire():
    # Anti-triche : "4 + 2" n'est PAS le calcul prioritaire de "3 * 4 + 2".
    with pytest.raises(oc.ErreurCalculatrice):
        oc.remplacer_calcul_par_resultat("3 * 4 + 2", "4 + 2", 6)


def test_remplacement_refuse_valeur_fausse():
    # Anti-triche : 13 n'est pas le résultat de 3 * 4.
    with pytest.raises(oc.ErreurCalculatrice):
        oc.remplacer_calcul_par_resultat("3 * 4 + 2", "3 * 4", 13)


# --- enchaînement complet (réduction déterministe, sans LLM) -------------------

@pytest.mark.parametrize("texte, attendu", [
    ("trois fois quatre plus deux", 14),
    ("dix moins deux fois trois", 4),
    ("ouvre parenthèse deux plus trois ferme parenthèse fois quatre", 20),
    ("deux moins cinq plus dix", 7),          # passe par un résultat négatif
    ("cent divisé par quatre divisé par cinq", 5),
])
def test_reduction_complete(texte, attendu):
    formule = oc.convertir_texte_en_formule(texte)
    for _ in range(20):
        prio = oc.trouver_calcul_prioritaire(formule)
        if prio["termine"]:
            assert prio["valeur"] == attendu
            return
        resultat = oc.calculer(prio["gauche"], prio["operateur"], prio["droite"])
        formule = oc.remplacer_calcul_par_resultat(formule, prio["sous_expression"], resultat)
    pytest.fail("la formule ne se réduit pas")
