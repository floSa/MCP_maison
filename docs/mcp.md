# Tutoriel — Le serveur MCP

Ce guide explique ce qu'est MCP, comment ce projet expose ses outils avec
**FastMCP**, et comment écrire vos propres outils. C'est la brique à comprendre
en premier si vous voulez réutiliser ce projet comme socle.

## 1. MCP, en une minute

**MCP (Model Context Protocol)** est un protocole standard qui permet à un
modèle (ou à un agent) de **découvrir** et **d'appeler** des outils exposés par
un serveur, sans rien coder en dur. L'idée clé :

> Côté serveur, vous écrivez des fonctions. Le serveur les publie avec un
> **schéma** (nom, description, paramètres typés). Côté client, l'agent
> demande « quels outils as-tu ? », reçoit la liste, et peut les appeler.

Avantage : l'agent et les outils sont **découplés**. On peut ajouter, retirer ou
remplacer un outil sans toucher à l'agent. On peut aussi brancher le même
serveur sur plusieurs clients (un agent maison, Claude Desktop, l'inspecteur
MCPJam, etc.).

Un serveur MCP expose trois familles de capacités : des **tools** (actions, ce
que l'on utilise ici), des **resources** (données en lecture) et des **prompts**
(modèles de requêtes). Ce projet n'utilise que les *tools*.

## 2. FastMCP : une fonction Python devient un outil

[FastMCP](https://gofastmcp.com) est une bibliothèque Python qui transforme une
fonction décorée en outil MCP. Le nom, la docstring et les annotations de type
deviennent automatiquement le schéma JSON que le client découvre.

Extrait de [`mcp_server/serveur.py`](../mcp_server/serveur.py) :

```python
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
import outils_calcul as oc

mcp = FastMCP(
    name="calculatrice",
    instructions="Calculatrice pas a pas. ...",
)

@mcp.tool
def calculer(gauche: float, operateur: str, droite: float) -> float:
    """Effectue UNE operation entre exactement deux nombres.

    operateur est l'un de : + - * /. Exemple : calculer(3, "*", 4) -> 12.
    """
    try:
        return oc.calculer(gauche, operateur, droite)
    except oc.ErreurCalculatrice as e:
        raise ToolError(str(e)) from None
```

Ce qu'il faut retenir :

- **`@mcp.tool`** publie la fonction. Son nom (`calculer`), sa **docstring**
  (la description vue par le LLM) et ses **annotations** (`gauche: float`,
  `operateur: str`, `droite: float`) forment le schéma. Soignez la docstring :
  c'est elle qui guide le modèle.
- **La logique est séparée** : les fonctions pures vivent dans
  [`outils_calcul.py`](../mcp_server/outils_calcul.py), testables sans serveur ni
  LLM. `serveur.py` ne fait que les exposer. C'est un patron recommandé : on
  teste la logique unitairement, on garde la couche MCP fine.
- **Les erreurs métier deviennent des `ToolError`** : le message remonte
  proprement au client (et donc au LLM, qui peut se corriger). Ici, une division
  par zéro ou un mot non reconnu donne un message lisible plutôt qu'une stack
  trace.

## 3. Les 4 outils de la calculatrice

| Outil | Entrée | Sortie | Rôle |
|---|---|---|---|
| `convertir_texte_en_formule` | `texte: str` | `str` | « trois fois quatre plus deux » donne `3 * 4 + 2` |
| `trouver_calcul_prioritaire` | `formule: str` | `dict` | Indique le calcul binaire à faire en premier |
| `calculer` | `gauche, operateur, droite` | `float` | Une seule opération entre deux nombres |
| `remplacer_calcul_par_resultat` | `formule, sous_expression, valeur` | `str` | Réécrit la formule en injectant le résultat |

La résolution complète est une **boucle** : convertir une fois, puis répéter
(trouver le prioritaire, calculer, remplacer) jusqu'à ce que la formule soit un
seul nombre. C'est l'agent qui orchestre cette boucle (voir
[docs/agent.md](agent.md)).

### Pourquoi `calculer` n'accepte que deux opérandes

C'est volontaire et central. En n'autorisant **qu'une opération binaire à la
fois**, on empêche le modèle de faire un calcul à plusieurs étapes de tête : il
est obligé de passer par `trouver_calcul_prioritaire` puis `calculer`, et
l'arbitre vérifie que l'opération demandée est bien la prioritaire. Deux
garde-fous sont d'ailleurs codés directement dans
`remplacer_calcul_par_resultat` :

- il refuse une sous-expression qui n'est pas LE calcul prioritaire de la
  formule courante ;
- il refuse une valeur qui n'est pas le vrai résultat de ce calcul.

Autrement dit, même en appelant les outils à la main (via MCPJam), on ne peut
pas injecter un faux résultat.

## 4. Le transport : HTTP et l'endpoint /mcp/

En bas de [`serveur.py`](../mcp_server/serveur.py) :

```python
if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
```

Le serveur écoute en HTTP. Les clients MCP s'y connectent sur
**`http://mcp-server:8000/mcp/`** (depuis un autre conteneur du réseau Docker)
ou **`http://localhost:8000/mcp/`** (depuis l'hôte). FastMCP gère le protocole
(handshake, découverte, appels) sur cet endpoint.

FastMCP supporte aussi le transport `stdio` (le serveur est lancé comme
sous-processus par le client) — pratique pour Claude Desktop, mais ici on veut
un service réseau partagé entre plusieurs conteneurs, donc HTTP.

## 5. Une route HTTP hors protocole : /sante

Le healthcheck Docker a besoin d'un point d'entrée simple. FastMCP permet
d'ajouter des routes HTTP classiques à côté du protocole MCP :

```python
from starlette.requests import Request
from starlette.responses import JSONResponse

@mcp.custom_route("/sante", methods=["GET"])
async def sante(request: Request) -> JSONResponse:
    return JSONResponse({"statut": "ok", "service": "calculatrice-mcp"})
```

C'est ce que le `healthcheck` du service `mcp-server` interroge dans le compose.

## 6. Ajouter votre propre outil (pas à pas)

Supposons que vous vouliez un outil `puissance` :

1. **Écrire la logique pure** dans `outils_calcul.py` :
   ```python
   def puissance(base: float, exposant: float) -> float:
       return base ** exposant
   ```
2. **L'exposer** dans `serveur.py` :
   ```python
   @mcp.tool
   def puissance(base: float, exposant: float) -> float:
       """Eleve base a la puissance exposant. Exemple : puissance(2, 3) -> 8."""
       return oc.puissance(base, exposant)
   ```
3. **Reconstruire** le serveur : `docker compose up -d --build mcp-server`.

C'est tout pour le serveur. L'agent **découvre** le nouvel outil
automatiquement (il liste les outils au démarrage de chaque résolution). Si vous
voulez que la calculatrice gère vraiment les puissances, il restera à enseigner
la priorité de cet opérateur à `trouver_calcul_prioritaire` — mais le mécanisme
d'exposition MCP, lui, n'a demandé que ces trois étapes.

## 7. Tester le serveur sans LLM

Deux façons :

- **Par le code**, avec un client FastMCP « en mémoire » (voir
  [tests/test_serveur_mcp.py](../tests/test_serveur_mcp.py)) :
  ```python
  from fastmcp import Client
  import serveur
  async with Client(serveur.mcp) as client:
      outils = await client.list_tools()          # decouverte
      r = await client.call_tool("calculer",
                                 {"gauche": 3, "operateur": "*", "droite": 4})
  ```
- **À la main**, avec l'inspecteur MCPJam : voir [docs/mcpjam.md](mcpjam.md).

## À retenir

- Une fonction + `@mcp.tool` = un outil découvrable. La docstring est sa notice
  pour le LLM.
- Séparez la logique pure (testable) de la couche MCP (fine).
- Les `ToolError` remontent des messages exploitables par le modèle.
- L'agent ne connaît aucun outil en dur : il les découvre. C'est ce qui rend ce
  socle extensible.
