"""CLI de l'agent : affiche la trace ReAct pas a pas, puis la reponse.

Usage (dans le conteneur) :
    docker compose exec agent python -m agent.cli "trois fois quatre plus deux"

Pratique pour observer le raisonnement et les appels MCP directement dans le
terminal, sans interface graphique.
"""

import asyncio
import json
import os
import sys

from fastmcp import Client

from agent.boucle_react import AgentReact
from agent.llm_ollama import LLMOllama


def _afficher_etape(etape: dict) -> None:
    """Affiche une etape de la trace, prefixee par un libelle texte."""
    type_etape = etape["type"]
    if type_etape == "pensee":
        print(f"  [pensee]  {etape['contenu'][:300]}")
    elif type_etape == "outil":
        args = json.dumps(etape["arguments"], ensure_ascii=False)
        resultat = json.dumps(etape["resultat"], ensure_ascii=False)
        print(f"  [MCP]     {etape['nom']}({args})")
        print(f"            -> {resultat}")
    elif type_etape == "refus_arbitre":
        print(f"  [ARBITRE] refuse : {etape['detail']}")
    else:  # erreur_outil
        print(f"  [ERREUR]  {etape['nom']} : {etape['detail']}")


def main() -> None:
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print('Usage : python -m agent.cli "trois fois quatre plus deux"')
        sys.exit(1)

    agent = AgentReact(
        llm=LLMOllama(os.environ.get("OLLAMA_URL", "http://localhost:11434"),
                      os.environ.get("MODELE", "qwen2.5:1.5b")),
        client_mcp=Client(os.environ.get("MCP_URL", "http://localhost:8000/mcp/")),
        guidage=os.environ.get("GUIDAGE", "1") != "0",
    )
    print(f"Question : {question}\n")
    resultat = asyncio.run(agent.resoudre(question))
    for etape in resultat["etapes"]:
        _afficher_etape(etape)
    print()
    if resultat["valide"]:
        reponse = resultat["reponse"]
        if float(reponse).is_integer():
            reponse = int(reponse)
        print(f"[OK] {resultat['formule']} = {reponse} "
              f"({resultat['iterations']} iterations, reponse validee par l'arbitre)")
    else:
        print(f"[ECHEC] {resultat.get('erreur')}")
        sys.exit(2)


if __name__ == "__main__":
    main()
