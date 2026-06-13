"""API HTTP de l'agent (FastAPI) + mini page de démonstration.

POST /calcul  {"question": "trois fois quatre plus deux"}
GET  /        page web de démo
GET  /sante   healthcheck Docker
"""

import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
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


@app.get("/sante")
async def sante():
    return {"statut": "ok", "service": "calculatrice-agent", "modele": MODELE}


@app.post("/calcul")
async def calcul(q: Question):
    agent = AgentReact(
        llm=LLMOllama(OLLAMA_URL, MODELE),
        client_mcp=Client(MCP_URL),
        guidage=GUIDAGE,
    )
    return await agent.resoudre(q.question)


PAGE_DEMO = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<title>Calculatrice agent ReAct</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem}
 input{width:70%;padding:.5rem;font-size:1rem}
 button{padding:.5rem 1rem;font-size:1rem;cursor:pointer}
 pre{background:#f4f4f4;padding:1rem;overflow:auto;border-radius:6px}
 .reponse{font-size:1.4rem;margin:1rem 0}
</style></head><body>
<h1>🧮 Calculatrice agent ReAct</h1>
<p>Le petit LLM ne calcule rien lui-même : il utilise les outils MCP,
sous le contrôle d'un arbitre anti-triche. Essayez :
<em>trois fois quatre plus deux</em></p>
<form onsubmit="poser(event)">
 <input id="q" value="trois fois quatre plus deux">
 <button>Calculer</button>
</form>
<div class="reponse" id="r"></div>
<pre id="trace"></pre>
<script>
async function poser(e){
  e.preventDefault();
  document.getElementById('r').textContent = '… le LLM réfléchit (CPU, patience) …';
  document.getElementById('trace').textContent = '';
  const res = await fetch('/calcul', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({question: document.getElementById('q').value})});
  const d = await res.json();
  document.getElementById('r').textContent =
    d.valide ? `✅ ${d.formule} = ${d.reponse}` : `❌ échec : ${d.erreur||''}`;
  document.getElementById('trace').textContent = JSON.stringify(d.etapes, null, 2);
}
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def accueil():
    return PAGE_DEMO
