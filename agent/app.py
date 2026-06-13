"""API HTTP de l'agent (FastAPI).

Endpoints :
  GET  /sante          healthcheck Docker
  POST /calcul         resolution complete, renvoyee en une fois (JSON)
  POST /calcul/stream  resolution en streaming SSE : chaque etape (pensee du
                       modele, appel MCP, refus de l'arbitre...) est emise des
                       qu'elle se produit. C'est ce que consomme l'UI Streamlit.
  GET  /               page HTML de demonstration minimale (secours)

Les deux endpoints de calcul s'appuient sur la MEME boucle ReAct : /calcul
consomme le generateur en bloquant, /calcul/stream le relaie evenement par
evenement (voir agent/boucle_react.py).
"""

import json
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastmcp import Client
from pydantic import BaseModel

from agent.boucle_react import AgentReact
from agent.llm_ollama import LLMOllama

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MCP_URL = os.environ.get("MCP_URL", "http://localhost:8000/mcp/")
MODELE = os.environ.get("MODELE", "qwen2.5:1.5b")
GUIDAGE = os.environ.get("GUIDAGE", "1") != "0"

app = FastAPI(
    title="Agent calculatrice ReAct",
    description="Un petit LLM local qui calcule UNIQUEMENT via des outils MCP.",
)


class Question(BaseModel):
    question: str


def _nouvel_agent() -> AgentReact:
    """Fabrique un agent neuf par requete (client MCP et etat non partages)."""
    return AgentReact(
        llm=LLMOllama(OLLAMA_URL, MODELE),
        client_mcp=Client(MCP_URL),
        guidage=GUIDAGE,
    )


@app.get("/sante")
async def sante():
    return {"statut": "ok", "service": "calculatrice-agent", "modele": MODELE}


@app.post("/calcul")
async def calcul(q: Question):
    """Resolution complete, renvoyee en une seule reponse JSON."""
    return await _nouvel_agent().resoudre(q.question)


@app.post("/calcul/stream")
async def calcul_stream(q: Question):
    """Resolution en streaming Server-Sent Events (SSE).

    Chaque evenement de la boucle ReAct est envoye au format SSE standard
    (`data: <json>\\n\\n`) des qu'il est produit. L'interface peut ainsi
    afficher le raisonnement et les appels MCP en direct, sans attendre la fin.
    """
    agent = _nouvel_agent()

    async def flux_evenements():
        async for evenement in agent.iter_evenements(q.question):
            yield f"data: {json.dumps(evenement, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        flux_evenements(),
        media_type="text/event-stream",
        # Desactive toute mise en tampon intermediaire pour un vrai temps reel.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Page de demonstration HTML minimale (l'UI principale est Streamlit) -----

PAGE_DEMO = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<title>Calculatrice agent ReAct</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem}
 input{width:70%;padding:.5rem;font-size:1rem}
 button{padding:.5rem 1rem;font-size:1rem;cursor:pointer}
 pre{background:#f4f4f4;padding:1rem;overflow:auto;border-radius:6px}
 .reponse{font-size:1.4rem;margin:1rem 0;font-weight:bold}
</style></head><body>
<h1>Calculatrice agent ReAct</h1>
<p>Le petit LLM ne calcule rien lui-meme : il utilise les outils MCP, sous le
controle d'un arbitre anti-triche. Essayez : <em>trois fois quatre plus deux</em>.
Pour l'interface complete (raisonnement et appels MCP en direct), utilisez
Streamlit sur le port 8501.</p>
<form onsubmit="poser(event)">
 <input id="q" value="trois fois quatre plus deux">
 <button>Calculer</button>
</form>
<div class="reponse" id="r"></div>
<pre id="trace"></pre>
<script>
async function poser(e){
  e.preventDefault();
  document.getElementById('r').textContent = 'Le LLM reflechit...';
  document.getElementById('trace').textContent = '';
  const res = await fetch('/calcul', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({question: document.getElementById('q').value})});
  const d = await res.json();
  document.getElementById('r').textContent =
    d.valide ? `${d.formule} = ${d.reponse}` : `Echec : ${d.erreur||''}`;
  document.getElementById('trace').textContent = JSON.stringify(d.etapes, null, 2);
}
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def accueil():
    return PAGE_DEMO
