"""Serveur MCP « calculatrice », construit avec FastMCP.

Chaque fonction décorée par @mcp.tool devient un outil MCP : son nom, sa
docstring et ses annotations de types sont automatiquement transformés en
schéma JSON que le LLM peut découvrir et appeler.

Lancement : python serveur.py  (transport HTTP, endpoint /mcp/)
"""

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

import outils_calcul as oc

mcp = FastMCP(
    name="calculatrice",
    instructions=(
        "Calculatrice pas à pas. Démarche : 1) convertir_texte_en_formule ; "
        "2) en boucle : trouver_calcul_prioritaire, calculer, "
        "remplacer_calcul_par_resultat ; jusqu'à ce que la formule soit un "
        "seul nombre."
    ),
)


@mcp.tool
def convertir_texte_en_formule(texte: str) -> str:
    """Convertit une question en français en formule mathématique normalisée.

    Exemple : « trois fois quatre plus deux » -> « 3 * 4 + 2 ».
    À appeler en PREMIER, une seule fois, avec la question d'origine.
    """
    try:
        return oc.convertir_texte_en_formule(texte)
    except oc.ErreurCalculatrice as e:
        raise ToolError(str(e)) from None


@mcp.tool
def trouver_calcul_prioritaire(formule: str) -> dict:
    """Indique quel calcul à deux opérandes faire en premier dans la formule.

    Applique les priorités : parenthèses, puis * et /, puis de gauche à droite.
    Renvoie gauche, operateur, droite et sous_expression, ou termine=true si la
    formule est déjà réduite à un seul nombre.
    """
    try:
        return oc.trouver_calcul_prioritaire(formule)
    except oc.ErreurCalculatrice as e:
        raise ToolError(str(e)) from None


@mcp.tool
def calculer(gauche: float, operateur: str, droite: float) -> float:
    """Effectue UNE opération entre exactement deux nombres.

    operateur est l'un de : + - * /. Exemple : calculer(3, "*", 4) -> 12.
    """
    try:
        return oc.calculer(gauche, operateur, droite)
    except oc.ErreurCalculatrice as e:
        raise ToolError(str(e)) from None


@mcp.tool
def remplacer_calcul_par_resultat(formule: str, sous_expression: str, valeur: float) -> str:
    """Remplace le calcul prioritaire par son résultat dans la formule.

    Exemple : remplacer_calcul_par_resultat("3 * 4 + 2", "3 * 4", 12) -> "12 + 2".
    Refuse une sous-expression non prioritaire ou une valeur incorrecte.
    """
    try:
        return oc.remplacer_calcul_par_resultat(formule, sous_expression, valeur)
    except oc.ErreurCalculatrice as e:
        raise ToolError(str(e)) from None


@mcp.custom_route("/sante", methods=["GET"])
async def sante(request: Request) -> JSONResponse:
    """Endpoint de santé pour le healthcheck Docker (hors protocole MCP)."""
    return JSONResponse({"statut": "ok", "service": "calculatrice-mcp"})


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
