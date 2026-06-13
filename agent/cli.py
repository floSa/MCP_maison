"""CLI de l'agent : affiche la trace ReAct pas à pas, puis la réponse.

Usage (dans le conteneur) :
    docker compose exec agent python -m agent.cli "trois fois quatre plus deux"
"""

import asyncio
import json
import os
import sys

from fastmcp import Client

from agent.boucle_react import AgentReact
from agent.llm_ollama import LLMOllama


def _afficher_etape(etape: dict) -> None:
    if etape["type"] == "pensee":
        print(f"  💭 {etape['contenu'][:300]}")
    elif etape["type"] == "outil":
        args = json.dumps(etape["arguments"], ensure_ascii=False)
        resultat = json.dumps(etape["resultat"], ensure_ascii=False)
        print(f"  🔧 {etape['nom']}({args})")
        print(f"     ↳ {resultat}")
    elif etape["type"] == "refus_arbitre":
        print(f"  ⛔ ARBITRE — {etape['detail']}")
    else:
        print(f"  ⚠️  {etape['nom']} — {etape['detail']}")


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
    print(f"❓ {question}\n")
    resultat = asyncio.run(agent.resoudre(question))
    for etape in resultat["etapes"]:
        _afficher_etape(etape)
    print()
    if resultat["valide"]:
        reponse = resultat["reponse"]
        if float(reponse).is_integer():
            reponse = int(reponse)
        print(f"✅ {resultat['formule']} = {reponse} "
              f"({resultat['iterations']} itérations, réponse validée par l'arbitre)")
    else:
        print(f"❌ Échec : {resultat.get('erreur')}")
        sys.exit(2)


if __name__ == "__main__":
    main()
