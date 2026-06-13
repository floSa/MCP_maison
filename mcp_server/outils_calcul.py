"""Fonctions pures de la calculatrice.

Ce module ne dépend de rien : chaque fonction est déterministe et testable
sans serveur MCP ni LLM. Le serveur MCP (serveur.py) ne fait que les exposer.

Représentation d'une formule : des jetons séparés par des espaces, p. ex.
    "3 * 4 + 2"     ou      "( 2 + 3 ) * 4"
"""

import re
import unicodedata


class ErreurCalculatrice(ValueError):
    """Erreur métier, dont le message est destiné à être lu par le LLM."""


# ---------------------------------------------------------------------------
# Normalisation du texte en français
# ---------------------------------------------------------------------------

def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def _normaliser_texte(texte: str) -> str:
    texte = _sans_accents(texte.lower())
    texte = texte.replace("'", " ").replace("’", " ")
    texte = re.sub(r"(\d),(\d)", r"\1.\2", texte)        # 3,5 -> 3.5
    texte = texte.replace("×", "*").replace("÷", "/")
    texte = re.sub(r"[?!;:,]", " ", texte)
    texte = re.sub(r"(?<!\d)\.", " ", texte)              # point final, pas décimal
    texte = re.sub(r"\.(?!\d)", " ", texte)
    texte = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", texte)   # dix-sept -> dix sept
    texte = re.sub(r"([()+\-*/])", r" \1 ", texte)        # padding des symboles
    return re.sub(r"\s+", " ", texte).strip()


# ---------------------------------------------------------------------------
# Nombres en toutes lettres : on génère le dictionnaire 0..100
# ---------------------------------------------------------------------------

_UNITES = ["zero", "un", "deux", "trois", "quatre", "cinq", "six", "sept",
           "huit", "neuf", "dix", "onze", "douze", "treize", "quatorze",
           "quinze", "seize", "dix sept", "dix huit", "dix neuf"]


def _construire_noms_nombres() -> dict:
    noms = {nom: valeur for valeur, nom in enumerate(_UNITES)}
    noms["une"] = 1
    for dizaine, nom in {20: "vingt", 30: "trente", 40: "quarante",
                         50: "cinquante", 60: "soixante"}.items():
        noms[nom] = dizaine
        noms[f"{nom} et un"] = dizaine + 1
        for u in range(2, 10):
            noms[f"{nom} {_UNITES[u]}"] = dizaine + u
    noms["soixante et onze"] = 71
    for u in range(10, 20):                    # soixante dix .. soixante dix neuf
        noms[f"soixante {_UNITES[u]}"] = 60 + u
    noms["quatre vingt"] = 80
    noms["quatre vingts"] = 80
    for u in range(1, 20):                     # quatre vingt un .. quatre vingt dix neuf
        noms[f"quatre vingt {_UNITES[u]}"] = 80 + u
    noms["cent"] = 100
    return noms


_NOMS_NOMBRES = _construire_noms_nombres()

_OPERATEURS_MOTS = {
    "plus": "+",
    "moins": "-",
    "fois": "*",
    "multiplie par": "*",
    "multiplie": "*",
    "x": "*",
    "divise par": "/",
    "divise": "/",
    "sur": "/",
    "ouvre parenthese": "(",
    "ferme parenthese": ")",
    "parenthese ouvrante": "(",
    "parenthese fermante": ")",
}

# Mots de liaison sans valeur mathématique, simplement ignorés.
_MOTS_IGNORES = {
    "combien", "font", "fait", "egal", "egale", "egalent", "vaut", "valent",
    "est", "ce", "que", "qu", "quel", "quelle", "donne", "donnent", "resultat",
    "le", "la", "l", "de", "du", "des", "calcule", "calculer", "calcul",
    "s", "il", "te", "plait", "me", "dis", "dire", "et", "a", "?",
}


def _est_nombre(jeton: str) -> bool:
    return re.fullmatch(r"-?\d+(\.\d+)?", jeton) is not None


def formater_nombre(valeur: float) -> str:
    """12.0 -> '12', 2.5 -> '2.5' (au plus 10 décimales)."""
    if abs(valeur - round(valeur)) < 1e-9:
        return str(int(round(valeur)))
    return str(round(valeur, 10))


# ---------------------------------------------------------------------------
# Outil n°1 : texte français -> formule normalisée
# ---------------------------------------------------------------------------

def convertir_texte_en_formule(texte: str) -> str:
    """« trois fois quatre plus deux » -> « 3 * 4 + 2 »."""
    if not texte or not texte.strip():
        raise ErreurCalculatrice("Le texte est vide.")
    mots = _normaliser_texte(texte).split()
    jetons = []
    i = 0
    while i < len(mots):
        correspondance = None
        # Correspondance gloutonne, de la phrase la plus longue à la plus courte
        # ("quatre vingt dix neuf" avant "quatre", "multiplie par" avant "multiplie").
        for longueur in range(min(4, len(mots) - i), 0, -1):
            phrase = " ".join(mots[i:i + longueur])
            if phrase in _NOMS_NOMBRES:
                correspondance = (str(_NOMS_NOMBRES[phrase]), longueur)
                break
            if phrase in _OPERATEURS_MOTS:
                correspondance = (_OPERATEURS_MOTS[phrase], longueur)
                break
        if correspondance is None:
            mot = mots[i]
            if re.fullmatch(r"\d+(\.\d+)?", mot):
                correspondance = (formater_nombre(float(mot)), 1)
            elif mot in ("+", "-", "*", "/", "(", ")"):
                correspondance = (mot, 1)
            elif mot in _MOTS_IGNORES:
                i += 1
                continue
            else:
                raise ErreurCalculatrice(f"Mot non reconnu : « {mot} ».")
        jetons.append(correspondance[0])
        i += correspondance[1]
    _valider_jetons(jetons)
    return " ".join(jetons)


# ---------------------------------------------------------------------------
# Tokenisation / validation d'une formule déjà écrite en symboles
# ---------------------------------------------------------------------------

def _tokeniser_formule(formule: str) -> list:
    """Découpe une formule en jetons, en tolérant « 3*4+2 » sans espaces.

    Un « - » collé devant un nombre en début de formule, après un opérateur ou
    une parenthèse ouvrante est un signe (nombre négatif), pas une soustraction.
    """
    if not formule or not str(formule).strip():
        raise ErreurCalculatrice("La formule est vide.")
    morceaux = re.sub(r"([()+\-*/])", r" \1 ", str(formule)).split()
    jetons = []
    i = 0
    while i < len(morceaux):
        m = morceaux[i]
        if (m == "-" and (not jetons or jetons[-1] in ("+", "-", "*", "/", "("))
                and i + 1 < len(morceaux) and _est_nombre(morceaux[i + 1])):
            jetons.append("-" + morceaux[i + 1])
            i += 2
            continue
        if not (_est_nombre(m) or m in ("+", "-", "*", "/", "(", ")")):
            raise ErreurCalculatrice(f"Jeton invalide dans la formule : « {m} ».")
        jetons.append(m)
        i += 1
    _valider_jetons(jetons)
    return jetons


def _valider_jetons(jetons: list) -> None:
    if not jetons:
        raise ErreurCalculatrice("Aucun nombre ni opérateur trouvé.")
    profondeur = 0
    attendu_nombre = True            # on attend un nombre ou une '('
    for j in jetons:
        if j == "(":
            if not attendu_nombre:
                raise ErreurCalculatrice("Il manque un opérateur avant la parenthèse ouvrante.")
            profondeur += 1
        elif j == ")":
            if attendu_nombre:
                raise ErreurCalculatrice("Parenthèse fermante mal placée.")
            profondeur -= 1
            if profondeur < 0:
                raise ErreurCalculatrice("Parenthèse fermante sans parenthèse ouvrante.")
        elif j in ("+", "-", "*", "/"):
            if attendu_nombre:
                raise ErreurCalculatrice(f"Opérateur « {j} » mal placé.")
            attendu_nombre = True
        elif _est_nombre(j):
            if not attendu_nombre:
                raise ErreurCalculatrice("Deux nombres se suivent sans opérateur.")
            attendu_nombre = False
        else:
            raise ErreurCalculatrice(f"Jeton invalide : « {j} ».")
    if profondeur != 0:
        raise ErreurCalculatrice("Parenthèse ouvrante non refermée.")
    if attendu_nombre:
        raise ErreurCalculatrice("La formule se termine par un opérateur.")


def normaliser_formule(formule: str) -> str:
    """Réécrit une formule sous forme canonique (jetons séparés par espaces)."""
    return " ".join(_tokeniser_formule(formule))


# ---------------------------------------------------------------------------
# Outil n°2 : trouver le calcul prioritaire
# ---------------------------------------------------------------------------

def _position_prioritaire(jetons: list):
    """Index de l'opérateur à calculer en premier, ou None si formule réduite.

    Règles : parenthèses les plus profondes d'abord, puis * et / avant + et -,
    puis de gauche à droite.
    """
    if len(jetons) == 1:
        return None
    profondeur, profondeur_max = 0, 0
    for j in jetons:
        if j == "(":
            profondeur += 1
            profondeur_max = max(profondeur_max, profondeur)
        elif j == ")":
            profondeur -= 1
    debut, fin = 0, len(jetons)
    if profondeur_max > 0:
        profondeur = 0
        for i, j in enumerate(jetons):
            if j == "(":
                profondeur += 1
                if profondeur == profondeur_max:
                    debut = i + 1
            elif j == ")":
                if profondeur == profondeur_max:
                    fin = i
                    break
                profondeur -= 1
    segment = jetons[debut:fin]
    for prioritaires in (("*", "/"), ("+", "-")):
        for i, j in enumerate(segment):
            if j in prioritaires:
                return debut + i
    raise ErreurCalculatrice(
        "Parenthèses inutiles autour d'un nombre seul : simplifie d'abord la formule."
    )


def trouver_calcul_prioritaire(formule: str) -> dict:
    """Quel calcul à deux opérandes faut-il faire en premier ?"""
    jetons = _tokeniser_formule(formule)
    position = _position_prioritaire(jetons)
    if position is None:
        return {
            "termine": True,
            "valeur": float(jetons[0]),
            "explication": "La formule est déjà réduite à un seul nombre : "
                           "c'est la réponse finale.",
        }
    gauche, operateur, droite = jetons[position - 1], jetons[position], jetons[position + 1]
    entre_parentheses = position > 0 and "(" in jetons[:position]
    if entre_parentheses:
        explication = "Les parenthèses sont prioritaires : on calcule d'abord à l'intérieur."
    elif operateur in ("*", "/"):
        explication = "« * » et « / » sont prioritaires sur « + » et « - »."
    else:
        explication = "Plus d'opération prioritaire : on calcule de gauche à droite."
    return {
        "termine": False,
        "gauche": float(gauche),
        "operateur": operateur,
        "droite": float(droite),
        "sous_expression": f"{gauche} {operateur} {droite}",
        "explication": explication,
    }


# ---------------------------------------------------------------------------
# Outil n°3 : calculer avec exactement deux opérandes
# ---------------------------------------------------------------------------

def calculer(gauche: float, operateur: str, droite: float) -> float:
    """Une seule opération à la fois : gauche <opérateur> droite."""
    operations = {
        "+": lambda a, b: a + b,
        "-": lambda a, b: a - b,
        "*": lambda a, b: a * b,
        "/": lambda a, b: a / b,
    }
    if operateur not in operations:
        raise ErreurCalculatrice(
            f"Opérateur inconnu : « {operateur} ». Opérateurs valides : + - * /."
        )
    try:
        return operations[operateur](float(gauche), float(droite))
    except ZeroDivisionError:
        raise ErreurCalculatrice("Division par zéro impossible.") from None


# ---------------------------------------------------------------------------
# Outil n°4 : remplacer le calcul prioritaire par son résultat
# ---------------------------------------------------------------------------

def _supprimer_parentheses_inutiles(jetons: list) -> list:
    """( 12 ) -> 12, répété tant que nécessaire."""
    modifie = True
    while modifie:
        modifie = False
        for i in range(len(jetons) - 2):
            if jetons[i] == "(" and _est_nombre(jetons[i + 1]) and jetons[i + 2] == ")":
                jetons = jetons[:i] + [jetons[i + 1]] + jetons[i + 3:]
                modifie = True
                break
    return jetons


def remplacer_calcul_par_resultat(formule: str, sous_expression: str, valeur: float) -> str:
    """« 3 * 4 + 2 » + (« 3 * 4 », 12) -> « 12 + 2 ».

    Garde-fous anti-triche intégrés à l'outil :
    - refuse une sous-expression qui n'est pas LE calcul prioritaire ;
    - refuse une valeur qui n'est pas le vrai résultat de ce calcul.
    """
    jetons = _tokeniser_formule(formule)
    position = _position_prioritaire(jetons)
    if position is None:
        raise ErreurCalculatrice("La formule est déjà réduite à un nombre, rien à remplacer.")
    prioritaire = " ".join(jetons[position - 1:position + 2])
    if normaliser_formule(sous_expression) != prioritaire:
        raise ErreurCalculatrice(
            f"« {sous_expression} » n'est pas le calcul prioritaire de "
            f"« {formule} ». Utilise d'abord trouver_calcul_prioritaire."
        )
    resultat_reel = calculer(float(jetons[position - 1]), jetons[position],
                             float(jetons[position + 1]))
    if abs(float(valeur) - resultat_reel) > 1e-6:
        raise ErreurCalculatrice(
            f"La valeur fournie n'est pas le résultat de « {prioritaire} ». "
            "Utilise l'outil calculer, ne devine pas."
        )
    nouveaux = (jetons[:position - 1] + [formater_nombre(resultat_reel)]
                + jetons[position + 2:])
    return " ".join(_supprimer_parentheses_inutiles(nouveaux))
